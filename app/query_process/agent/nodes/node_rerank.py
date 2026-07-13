import sys

from app.lm.reranker_utils import get_reranker_model
from app.core.logger import logger
from app.utils.task_utils import add_running_task, add_done_task

# 动态 TopK 硬上限
RERANK_MAX_TOPK: int = 10
# 最小保留数量
RERANK_MIN_TOPK: int = 1
# 断崖阈值（相对）
RERANK_GAP_RATIO: float = 0.25
# 断崖阈值（绝对）
RERANK_GAP_ABS: float = 0.5


def step_1_merge_rrf_mcp(state):
    """
    将 RRF 本地结果与 MCP/Web 搜索结果合并为统一格式。
    """
    rrf_chunks = state.get("rrf_chunks", [])
    web_search_docs = state.get("web_search_docs", [])
    chunks_list = []

    for chunk in rrf_chunks:
        entity = chunk.get('entity')
        chunk_id = entity.get('chunk_id')
        content = entity.get('content')
        title = entity.get('title')
        chunks_list.append({
            "chunk_id": chunk_id,
            "text": content,
            "title": title,
            "source": "local",
            "url": ""
        })

    for doc in web_search_docs:
        text = doc.get("snippet")
        url = doc.get("url")
        title = doc.get("title")
        chunks_list.append({
            "chunk_id": "",
            "text": text,
            "title": title,
            "source": "web",
            "url": url
        })

    logger.info(f"多路数据融合，最终结果为:{chunks_list}")
    return chunks_list


def step_2_rerank_doc_list(doc_list, state):
    """
    使用 Cross-Encoder Reranker 模型对合并后的文档进行精排打分。
    """
    rewritten_query = state.get("rewritten_query") or state.get("original_query")
    text_list = [doc['text'] for doc in doc_list]
    rerank = get_reranker_model()

    questions_pairs = [[rewritten_query, text] for text in text_list]
    scores = rerank.compute_score(questions_pairs, normalize=True)

    doc_list_with_score = []
    for score, item in zip(scores, doc_list):
        item['score'] = score
        doc_list_with_score.append(item)

    doc_list_with_score.sort(key=lambda x: x['score'], reverse=True)
    logger.info(f"已经完成排序和打分！最终结果为：{doc_list_with_score}")
    return doc_list_with_score


def step_3_topk_and_gap(rerank_score_list):
    """
    对 rerank 打分后的有序集合进行动态 TopK 截断。

    从第 (min_topk) 条开始，比较相邻两条的分数差（gap），
    若 gap 超过绝对阈值或相对阈值，则视为"断崖"，在该位置截断。
    """
    max_topk = RERANK_MAX_TOPK
    min_topk = RERANK_MIN_TOPK
    gap_abs = RERANK_GAP_ABS
    gap_ratio = RERANK_GAP_RATIO

    topk = min(max_topk, len(rerank_score_list))

    if topk > min_topk:
        for index in range(min_topk - 1, topk - 1):
            score_1 = rerank_score_list[index].get("score", 0.0)
            score_2 = rerank_score_list[index + 1].get("score", 0.0)
            gap = score_1 - score_2
            rel = gap / (abs(score_1) + 1e-6)
            if gap >= gap_abs or rel >= gap_ratio:
                logger.info(f"数据集合{index}和{index+1}的位置发生了断崖，结束循环！！")
                topk = index + 1
                break

    topk_doc_list = rerank_score_list[:topk]
    logger.info(f"最终截取的长度：{topk},截取的内容:{topk_doc_list}")
    return topk_doc_list


def node_rerank(state):
    """
    Rerank 节点：

    流程：
      1. 合并 RRF 本地结果与 MCP/Web 搜索结果
      2. 使用 Cross-Encoder Reranker 模型精排打分
      3. 动态 TopK 截断（断崖检测算法）
    """
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))

    doc_list = step_1_merge_rrf_mcp(state)
    rerank_score_list = step_2_rerank_doc_list(doc_list, state)
    final_doc_list = step_3_topk_and_gap(rerank_score_list)

    state["reranked_docs"] = final_doc_list
    add_done_task(state['session_id'], sys._getframe().f_code.co_name, state.get("is_stream"))
    return state
