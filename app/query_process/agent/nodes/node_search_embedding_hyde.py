import sys

from langchain_core.messages import HumanMessage

from app.utils.task_utils import add_running_task, add_done_task
from app.lm.lm_utils import *
from app.lm.embedding_utils import *
from app.clients.milvus_utils import *
from app.core.logger import logger
from app.core.load_prompt import load_prompt


def step_1_create_hyde_doc(rewritten_query):
    """
    调用 LLM 根据问题生成一份假设性答案（HyDE）。
    """
    llm = get_llm_client()
    hyde_prompt = load_prompt("hyde_prompt", rewritten_query=rewritten_query)
    messages = [
        HumanMessage(content=hyde_prompt)
    ]
    response = llm.invoke(messages)
    hyde_doc = response.content
    logger.info(f"使用模型生成假设性答案，问题：{rewritten_query},答案：{hyde_doc}")
    return hyde_doc


def step_2_search_embedding_hyde(rewritten_query, hyde_doc, item_names):
    """
    将问题+假设性答案拼接后查询向量数据库（混合查询）。
    """
    query_str = rewritten_query + hyde_doc
    embeddings = generate_embeddings([query_str])

    item_name_str = ', '.join(f'"{item}"' for item in item_names)
    reqs = create_hybrid_search_requests(
        dense_vector=embeddings['dense'][0],
        sparse_vector=embeddings['sparse'][0],
        expr=f"item_name in [{item_name_str}]"
    )

    milvus_client = get_milvus_client()
    resp = hybrid_search(
        client=milvus_client,
        collection_name=milvus_config.chunks_collection,
        reqs=reqs,
        ranker_weights=(0.9, 0.1),
        output_fields=["item_name", "content", "title", "parent_title", "chunk_id"]
    )

    result = resp[0] if resp else []
    logger.info(f"假设性问题检索结果：{result}")
    return result


def node_search_embedding_hyde(state):
    """
    HyDE (Hypothetical Document Embedding) 节点：
    先让 LLM 生成假设性答案，再用"问题+假设性答案"进行向量检索，提高召回率。
    """
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))

    rewritten_query = state.get("rewritten_query")
    item_names = state.get("item_names")

    hyde_doc = step_1_create_hyde_doc(rewritten_query)
    resp = step_2_search_embedding_hyde(rewritten_query, hyde_doc, item_names)

    add_done_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))
    return {"hyde_embedding_chunks": resp}
