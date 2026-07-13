import sys

from app.core.logger import logger
from app.import_process.agent.state import ImportGraphState
from app.lm.embedding_utils import generate_embeddings


def node_bge_embedding(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 向量化 (node_bge_embedding)
    对每个 chunk 的 content 生成稠密+稀疏向量，存入 state["embeddings_content"]
    """
    function_name = sys._getframe().f_code.co_name
    logger.info(f">>> [{function_name}] 开始执行，chunk 数量: {len(state['chunks'])}")

    chunks = state["chunks"]
    if not chunks:
        logger.warning(f">>> [{function_name}] 没有切片数据，跳过")
        return state

    texts = [c["content"] for c in chunks]
    embeddings = generate_embeddings(texts)

    for i, chunk in enumerate(chunks):
        chunk["chunk_id"] = i + 1
        chunk["dense_vector"] = embeddings["dense"][i]
        chunk["sparse_vector"] = embeddings["sparse"][i]

    state["embeddings_content"] = chunks

    logger.info(f">>> [{function_name}] 完成，{len(chunks)} 个切片已生成向量")
    return state
