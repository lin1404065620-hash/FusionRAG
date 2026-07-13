import sys
import re

from app.utils.task_utils import add_running_task, add_done_task, set_task_result
from app.utils.sse_utils import push_to_session, SSEEvent
from app.core.logger import logger
from app.core.load_prompt import load_prompt
from app.lm.lm_utils import get_llm_client
from app.clients.mongo_history_utils import save_chat_message


MAX_CONTEXT_CHARS = 12000


def step_1_check_answer(state):
    """
    检查 state 中是否已有明确的 answer（例如 item_name 无法确认时提前设置的提示）。
    如果有，则根据是否流式输出，通过 SSE 推送或保存为任务结果。
    """
    answer = state.get("answer")
    is_stream = state.get("is_stream", False)
    if answer:
        if is_stream:
            push_to_session(state["session_id"], SSEEvent.DELTA, {"delta": answer})
        else:
            set_task_result(state["session_id"], "answer", answer)
        return True
    else:
        return False


def step_2_load_prompt(state):
    """
    组装最终回答用的提示词：将检索文档、历史对话、商品名称、用户问题
    填入 answer_out 模板，生成大模型输入 prompt。
    """
    rewritten_query = state.get("rewritten_query") or state.get("original_query")
    reranked_docs = state.get("reranked_docs", [])
    item_names = state.get("item_names", [])
    history = state.get("history", [])

    docs = []
    used_length = 0

    for i, doc in enumerate(reranked_docs, start=1):
        text = doc.get("text")
        source = doc.get("source")
        title = doc.get("title")
        score = doc.get("score")
        content = f"[{i}][source={source}][title={title}][score={score}]\n\n{text}"

        if used_length + len(content) > MAX_CONTEXT_CHARS:
            logger.info(f"本次内容停止追加了！已经大于限制长度！")
            break
        docs.append(content)
        used_length += len(content)

    final_context = "\n\n".join(docs)

    history_str = ""
    if history and len(history) > 0:
        for i, message in enumerate(history, start=1):
            role = message.get("role")
            text = message.get("text")
            current_history = ""
            if role == "user" and text:
                current_history = f"【用户】: {text}\n"
            elif role == "assistant" and text:
                current_history = f"【助手】: {text}\n"
            history_str += current_history
            used_length += len(current_history)
            if used_length > MAX_CONTEXT_CHARS:
                logger.info(f"本次内容停止追加了！已经大于限制长度！")
                break
    else:
        history_str = "没有历史对话记录！"

    item_names_str = ",".join(item_names)

    answer_out_prompt = load_prompt("answer_out",
                                    context=final_context,
                                    history=history_str,
                                    item_names=item_names_str,
                                    question=rewritten_query)
    logger.info(f"已经完成了提示词生成：{answer_out_prompt}")
    return answer_out_prompt


def step_3_create_answer(state, prompt):
    """
    调用大模型生成最终答案，支持流式和非流式输出。
    """
    model = get_llm_client()
    is_stream = state.get("is_stream", False)
    answer = ''

    if is_stream:
        for chunk in model.stream(prompt):
            delta = chunk.content
            answer += delta
            push_to_session(state["session_id"], SSEEvent.DELTA, {"delta": delta})
    else:
        response = model.invoke(prompt)
        content = response.content
        answer = content
        set_task_result(state["session_id"], "answer", content)

    state['answer'] = answer
    logger.info(f"lm模型最终返回的结果：{answer}")
    return answer


def step_4_extract_images_url(state):
    """
    从 reranked_docs 中提取图片链接：
      - doc["url"] 本身就是图片地址（web 搜索结果）
      - doc["text"] 中的 Markdown 图片语法 ![xxx](url)
    """
    images = []
    set_images = set()

    image_reg = re.compile(r"!\[.*?\]\((.*?)\)")

    reranked_docs = state.get("reranked_docs", [])
    for doc in reranked_docs:
        url = doc.get("url")
        if url:
            if url.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                if url not in set_images:
                    images.append(url)
                    set_images.add(url)

        text = doc.get("text")
        if text:
            matches = image_reg.findall(text)
            for image_url in matches:
                if image_url not in set_images:
                    images.append(image_url)
                    set_images.add(image_url)

    logger.info(f"已经完成图片提取。reranked_docs总数:{len(reranked_docs)}, 图片数量:{len(images)},提取内容：{images}")
    state['image_urls'] = images
    return images


def step_4b_extract_images_from_answer(answer):
    """
    从 LLM 答案的【图片】区块中补充提取 URL。
    因为 LLM 可能重构了被分块截断的 Markdown 图片链接。
    """
    images = []
    if not answer:
        return images

    image_block_reg = re.compile(r"【图片】\s*\n((?:\s*https?://[^\s]+\s*\n?)+)")
    block_match = image_block_reg.search(answer)
    if block_match:
        urls_text = block_match.group(1)
        url_reg = re.compile(r"https?://[^\s]+")
        for url_match in url_reg.finditer(urls_text):
            url = url_match.group(0)
            if any(url.lower().endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                images.append(url)

    image_reg = re.compile(r"!\[.*?\]\((https?://[^\s\)]+)\)")
    for match in image_reg.finditer(answer):
        url = match.group(1)
        if url not in images:
            images.append(url)

    logger.info(f"从答案中额外提取到图片: {len(images)} 张, {images}")
    return images


def step_5_write_history(state):
    """
    将本轮助手回答保存到 MongoDB 历史记录。
    MongoDB 不可用时仅记录警告，不影响主流程。
    """
    session_id = state.get("session_id")
    answer = state.get("answer")
    rewritten_query = state.get("rewritten_query") or state.get("original_query")
    item_names = state.get("item_names", [])

    try:
        if answer:
            save_chat_message(
                session_id=session_id,
                role="assistant",
                text=answer,
                item_names=item_names,
                rewritten_query=rewritten_query
            )
        logger.info(f"完成了本次对话的记录存储！")
    except Exception as e:
        logger.warning(f"历史记录存储失败（MongoDB 不可用），不影响查询功能: {e}")


def node_answer_output(state):
    """
    最终答案输出节点。

    流程：
      1. 检查 state 中是否已有现成 answer（如 item_name 无法确认）
      2. 如果没有，组装 prompt 并调用大模型生成答案
      3. 从检索文档中提取图片 URL
      4. 补充从 LLM 答案中提取的图片链接
      5. 如果有图片且为流式输出，通过 SSE FINAL 事件返回
      6. 保存聊天历史到 MongoDB
    """
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))

    answer_exists = step_1_check_answer(state)
    if not answer_exists:
        prompt = step_2_load_prompt(state)
        state["prompt"] = prompt
        answer = step_3_create_answer(state, prompt)
        images_url = step_4_extract_images_url(state)
        answer_images = step_4b_extract_images_from_answer(answer)
        for img in answer_images:
            if img not in images_url:
                images_url.append(img)
        set_task_result(state["session_id"], "image_urls", images_url)
        if images_url and state.get("is_stream", False):
            push_to_session(state["session_id"],
                            SSEEvent.FINAL,
                            {"answer": answer,
                             "status": "completed",
                             "image_urls": images_url})

    step_5_write_history(state)
    add_done_task(state['session_id'], sys._getframe().f_code.co_name, state.get("is_stream"))
    return state
