import sys
from app.utils.task_utils import add_running_task, add_done_task
from app.core.logger import logger


def step_3_reciprocal_rank_fusion(source_with_weight, top_k: int = 5):
    """
    对多路召回结果进行 Reciprocal Rank Fusion 排序。

    RRF 不是简单合并，而是先保留每个 chunk 在各路结果中的排名，
    根据排名计算 RRF 分数（score = 1/(60+rank) * weight），
    同一 chunk 在多路出现的分数累加，最后按总分排序取 top_k。
    """
    score_dict = {}
    chunk_dict = {}

    for source, weight in source_with_weight:
        for rank, chunk in enumerate(source, start=1):
            chunk_id = chunk.get("id") or chunk.get("entity").get("chunk_id")
            score_dict[chunk_id] = score_dict.get(chunk_id, 0.0) + (1.0 / (60 + rank)) * weight
            chunk_dict.setdefault(chunk_id, chunk)

    merged = []
    for chunk_id, score in score_dict.items():
        chunk = chunk_dict.get(chunk_id)
        merged.append((chunk, score))
    merged.sort(key=lambda x: x[1], reverse=True)
    merged = merged[:top_k]

    rank_chunks = [chunk for chunk, score in merged]
    logger.info(f"完成了rrf排序处理完毕，结果为：{rank_chunks}")
    return rank_chunks


def node_rrf(state):
    """
    Reciprocal Rank Fusion 节点：
    将多路召回的结果（向量、HyDE）进行加权融合排序。
    RRF 仅处理本地检索的两路结果，MCP/Web 结果在后续 Rerank 阶段才加入。
    """
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))

    embedding_chunks = state.get("embedding_chunks")
    hyde_embedding_chunks = state.get("hyde_embedding_chunks")

    source_with_weight = [
        (embedding_chunks, 1.0),
        (hyde_embedding_chunks, 1.0)
    ]

    rrf_response = step_3_reciprocal_rank_fusion(source_with_weight)
    state["rrf_chunks"] = rrf_response
    add_done_task(state['session_id'], sys._getframe().f_code.co_name, state.get("is_stream"))
    return state
