from typing_extensions import TypedDict
from typing import List
import copy

class QueryGraphState(TypedDict):
    """定义了整个查询流程中流转的数据结构。"""
    session_id: str
    original_query: str

    embedding_chunks: list
    hyde_embedding_chunks: list
    web_search_docs: list

    rrf_chunks: list
    reranked_docs: list

    prompt: str
    answer: str

    item_names: List[str]
    rewritten_query: str
    history: list
    is_stream: bool


query_graph_default_state: QueryGraphState = {
    "session_id": "",
    "original_query": "",
    "embedding_chunks": [],
    "hyde_embedding_chunks": [],
    "web_search_docs": [],
    "rrf_chunks": [],
    "reranked_docs": [],
    "prompt": "",
    "answer": "",
    "item_names": [],
    "rewritten_query": "",
    "history": [],
    "is_stream": False
}


def create_query_default_state(**overrides) -> QueryGraphState:
    """创建查询流程的默认状态，支持覆盖字段。"""
    state = copy.deepcopy(query_graph_default_state)
    state.update(overrides)
    return state


def get_query_default_state() -> QueryGraphState:
    return copy.deepcopy(query_graph_default_state)


def copy_query_state(state: QueryGraphState, **overrides) -> QueryGraphState:
    """复制现有状态并可覆盖字段，深拷贝，不污染原数据。"""
    new_state = copy.deepcopy(state)
    new_state.update(overrides)
    return new_state
