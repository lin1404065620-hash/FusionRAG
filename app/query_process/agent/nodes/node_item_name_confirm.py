import sys
import json

from langchain_core.messages import HumanMessage

from app.conf.milvus_config import milvus_config
from app.core.load_prompt import load_prompt
from app.query_process.agent.state import QueryGraphState
from app.utils.task_utils import add_running_task, add_done_task
from app.clients.mongo_history_utils import get_recent_messages, save_chat_message
from app.lm.lm_utils import get_llm_client
from app.lm.embedding_utils import generate_embeddings
from app.clients.milvus_utils import get_milvus_client, create_hybrid_search_requests, hybrid_search
from app.core.logger import logger


def step_3_llm_item_name_and_rewrite_query(original_query, history_chats):
    """
    根据历史记录识别 item_names 并重写问题。
    """
    history_text = ""
    for chat in history_chats:
        history_text += f"聊天角色：{chat['role']}，回答内容： {chat['text']}，重写问题： {chat['rewritten_query']}，关联主体： {','.join(chat.get('item_names',[]))},时间： {chat['ts']}\n"

    prompt = load_prompt("rewritten_query_and_itemnames", history_text=history_text, query=original_query)
    lm_client = get_llm_client(json_mode=True)
    messages = [
        HumanMessage(content=prompt)
    ]
    response = lm_client.invoke(messages)
    content = response.content
    if content.startswith("```json"):
        content = content.replace("```json", "").replace("```", "")
    dict_content = json.loads(content)

    if "item_names" not in dict_content:
        dict_content["item_names"] = []
    if "rewritten_query" not in dict_content:
        dict_content["rewritten_query"] = original_query

    logger.info(f"已经完成问题的重写和item_name的提取！ 结果为：{dict_content}")
    return dict_content


def step_4_query_milvus_item_names(item_names):
    """
    通过混合查询（稠密向量 + 稀疏向量）在向量数据库中确定 item_name。
    """
    final_result = []
    milvus_client = get_milvus_client()
    embeddings = generate_embeddings(item_names)

    for index, item_name in enumerate(item_names):
        dense_vector = embeddings["dense"][index]
        sparse_vector = embeddings["sparse"][index]
        reqs = create_hybrid_search_requests(
            dense_vector=dense_vector,
            sparse_vector=sparse_vector
        )
        response = hybrid_search(
            client=milvus_client,
            collection_name=milvus_config.item_name_collection,
            reqs=reqs,
            ranker_weights=(0.8, 0.2),
            norm_score=True
        )

        matches = []
        if response and len(response) > 0:
            for hit in response[0]:
                entity = hit.get("entity", {})
                hit_name = entity.get("item_name")
                score = hit.get("distance", 0)
                if hit_name:
                    matches.append({
                        "item_name": hit_name,
                        "score": score
                    })
        final_result.append({
            "extracted": item_name,
            "matches": matches
        })

    logger.info(f"查询向量数据库结果为：{final_result}")
    return final_result


def step_5_confirmed_and_optional_item_name(query_milvus_results):
    """
    根据向量数据库查询的分数归纳出确定和可选的 item_name 列表。

    评分规则：
      - >=0.85: 确定 item_name
      - >=0.40: 可选 item_name
      - 小于0.40: 忽略
    """
    confirmed_item_names = []
    options_item_names = []

    for item_name_meta in query_milvus_results:
        extracted_name = item_name_meta.get("extracted")
        matches = item_name_meta.get("matches", [])
        matches.sort(key=lambda x: x.get("score", 0), reverse=True)

        high_score_matches = [x for x in matches if x.get("score", 0) >= 0.6]
        middle_score_matches = [x for x in matches if x.get("score", 0) >= 0.4]

        if len(high_score_matches) >= 1:
            # 将所有高分匹配都纳入确认列表，覆盖同一产品的不同名称变体。
            # 例如 "HAK 180烫金机" 和 "HAK 180 烫金机" 都应加入，确保 Milvus 过滤能命中。
            for item in high_score_matches:
                if item.get("score", 0) >= 0.85:
                    confirmed_item_names.append(item.get("item_name"))
            if not any(item.get("score", 0) >= 0.85 for item in high_score_matches):
                confirmed_item_names.append(high_score_matches[0].get("item_name"))
            continue

        if len(middle_score_matches) > 0:
            for item in middle_score_matches[:2]:
                options_item_names.append(item.get("item_name"))
            continue
        logger.info(f"没有匹配的item_name，忽略：{extracted_name}")

    result = {
        "confirmed_item_names": list(set(confirmed_item_names)),
        "options_item_names": list(set(options_item_names))
    }
    logger.info(f"处理结果为：{result}")
    return result


def step_6_deal_list(state, item_results, history_chats, rewritten_query):
    """
    根据确认/可选集合判定是否要赋值 answer 提前返回。
    """
    confirmed_item_names = item_results.get("confirmed_item_names", [])
    options_item_names = item_results.get("options_item_names", [])

    if len(confirmed_item_names) > 0:
        state['item_names'] = confirmed_item_names
        state['rewritten_query'] = rewritten_query
        state['history'] = history_chats
        if "answer" in state:
            del state['answer']
        logger.info(f"有确定的item_name:{confirmed_item_names}")
        return state

    if len(options_item_names) > 0:
        option_names = '、'.join(options_item_names)
        answer = f"您是想咨询以下哪个商品：{option_names}?请下次提问明确商品名称！！"
        state['answer'] = answer
        logger.info(f"有可选的item_name:{options_item_names}")
        return state

    answer = "没有匹配的商品名，请重新提问！！"
    state['answer'] = answer
    logger.info(f"没有匹配的的item_name")
    return state


def node_item_name_confirm(state):
    """
    确认用户问题中的核心商品名称。

    流程：
      1. 从历史对话和本次提问中提取 item_name
      2. 重写用户问题以提高后续召回率
      3. 通过 Milvus 向量库验证 item_name 并打分分类
      4. 如能确认则继续后续节点，否则提前返回提示
    """
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state["is_stream"])

    history_chats = get_recent_messages(session_id=state["session_id"], limit=10)

    item_names_and_rewritten_query = step_3_llm_item_name_and_rewrite_query(state["original_query"], history_chats)
    item_names = item_names_and_rewritten_query.get("item_names", [])
    rewritten_query = item_names_and_rewritten_query.get("rewritten_query", "")
    item_results = {}

    if len(item_names) > 0:
        query_milvus_results = step_4_query_milvus_item_names(item_names)
        item_results = step_5_confirmed_and_optional_item_name(query_milvus_results)

    state = step_6_deal_list(state, item_results, history_chats, rewritten_query)

    save_chat_message(
        session_id=state["session_id"],
        role="user",
        text=state["original_query"],
        rewritten_query=state.get("rewritten_query", ""),
        item_names=state.get("item_names", []),
        image_urls=[]
    )

    add_done_task(state["session_id"], sys._getframe().f_code.co_name, state["is_stream"])
    return state
