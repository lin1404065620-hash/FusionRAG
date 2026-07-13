import sys

from app.conf.milvus_config import milvus_config
from app.utils.task_utils import add_running_task, add_done_task
from app.lm.embedding_utils import generate_embeddings
from app.clients.milvus_utils import create_hybrid_search_requests, hybrid_search, get_milvus_client
from app.core.logger import logger


def node_search_embedding(state):
    """
    对重写后的问题进行向量内容检索，返回匹配的 chunks 切片。
    """
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))

    rewritten_query = state.get("rewritten_query")
    item_names = state.get("item_names")

    embeddings = generate_embeddings([rewritten_query])

    item_name_str = ', '.join(f'"{item}"' for item in item_names)
    hybrid_search_requests = create_hybrid_search_requests(
        dense_vector=embeddings['dense'][0],
        sparse_vector=embeddings['sparse'][0],
        expr=f"item_name in [{item_name_str}]"
    )

    milvus_client = get_milvus_client()
    resp = hybrid_search(
        client=milvus_client,
        collection_name=milvus_config.chunks_collection,
        reqs=hybrid_search_requests,
        ranker_weights=(0.9, 0.1),
        norm_score=True,
        limit=5,
        output_fields=["chunk_id", "content", "file_title", "title", "parent_title", "item_name"]
    )

    embedding_chunks = resp[0] if resp else []

    add_done_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))
    return {"embedding_chunks": embedding_chunks}
