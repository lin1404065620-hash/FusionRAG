import os
import sys
import time

from pymilvus import DataType
from langchain_core.messages import SystemMessage, HumanMessage

from app.conf.milvus_config import milvus_config
from app.import_process.agent.state import ImportGraphState
from app.clients.milvus_utils import get_milvus_client
from app.lm.lm_utils import get_llm_client
from app.lm.embedding_utils import generate_embeddings
from app.utils.task_utils import add_running_task, add_done_task
from app.core.logger import logger
from app.core.load_prompt import load_prompt

DEFAULT_ITEM_NAME_CHUNK_K = 5
SINGLE_CHUNK_CONTENT_MAX_LEN = 220
CONTEXT_TOTAL_MAX_CHARS = 190


def step_1_get_chunks(state):
    """获取 chunks 和 file_title，file_title 缺失时从 md_path 提取。"""
    chunks = state.get('chunks')
    file_title = state.get('file_title')

    if not chunks:
        raise ValueError("chunks没有值，无法继续进行，抛出异常处理！")
    if not file_title:
        file_title = os.path.basename(state.get('md_path'))
        logger.info(f"file_title缺失，获取md_path进行截取！{file_title}")
        state['file_title'] = file_title
    return chunks, file_title


def step_2_build_context(chunks):
    """
    截取前 top 个 chunk 的内容拼接成上下文，总字符数不超过 CONTEXT_TOTAL_MAX_CHARS。
    """
    parts = []
    total_chars = 0
    for index, chunk in enumerate(chunks[:DEFAULT_ITEM_NAME_CHUNK_K], start=1):
        data = f"切片：{index}，标题:{chunk['title']},内容：{chunk['content']}"
        parts.append(data)
        total_chars += len(data)
        if total_chars >= CONTEXT_TOTAL_MAX_CHARS:
            logger.info(f"已经达到最大字符数:{total_chars}，停止拼接！")
            break

    context = "\n\n".join(parts)
    final_context = context[:SINGLE_CHUNK_CONTENT_MAX_LEN]
    return final_context


def step_3_call_llm(context, file_title):
    """调用 LLM 识别 item_name，失败时用 file_title 兜底。"""
    human_prompt = load_prompt("item_name_recognition", file_title=file_title, context=context)
    system_prompt = load_prompt("product_recognition_system")
    llm = get_llm_client(json_mode=False)
    messages = [
        HumanMessage(content=human_prompt),
        SystemMessage(content=system_prompt)
    ]
    for attempt in range(3):
        try:
            response = llm.invoke(messages)
            item_name = response.content
            if not item_name:
                item_name = file_title
            return item_name
        except Exception as e:
            if attempt < 2:
                wait = 2 ** attempt
                logger.warning(f"LLM调用失败(第{attempt + 1}次): {e}，{wait}秒后重试...")
                time.sleep(wait)
            else:
                logger.error(f"LLM调用已达最大重试次数，使用文件标题兜底: {file_title}")
                return file_title


def step_4_update_chunks_and_state(state, item_name, chunks):
    """将识别出的 item_name 写入 state 和每个 chunk。"""
    state['item_name'] = item_name
    for chunk in chunks:
        chunk['item_name'] = item_name
    state['chunks'] = chunks
    logger.info("完成了chunks和state[item_name]的赋值和修改！！")


def step_5_generate_embeddings(item_name):
    """根据 item_name 生成稠密和稀疏向量。"""
    result = generate_embeddings([item_name])
    dense_vector, sparse_vector = result['dense'][0], result['sparse'][0]
    return dense_vector, sparse_vector


def step_6_save_to_vector_db(file_title, item_name, dense_vector, sparse_vector):
    """将 item_name 及其向量保存到 Milvus 的 item_name 集合中，支持幂等覆盖。"""
    milvus_client = get_milvus_client()
    if not milvus_client.has_collection(collection_name=milvus_config.item_name_collection):
        schema = milvus_client.create_schema(
            auto_id=True,
            enable_dynamic_field=True,
        )
        schema.add_field(field_name="pk", datatype=DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=1024)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

        index_params = milvus_client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_name="dense_vector_index",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_type="SPARSE_INVERTED_INDEX",
            index_name="sparse_vector_index",
            metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE"},
        )
        milvus_client.create_collection(
            collection_name=milvus_config.item_name_collection,
            schema=schema,
            index_params=index_params
        )

    milvus_client.load_collection(collection_name=milvus_config.item_name_collection)
    milvus_client.delete(collection_name=milvus_config.item_name_collection,
                         filter=f"item_name=='{item_name}'")

    item = {
        "file_title": file_title,
        "item_name": item_name,
        "dense_vector": dense_vector,
        "sparse_vector": sparse_vector
    }
    milvus_client.insert(collection_name=milvus_config.item_name_collection, data=[item])
    milvus_client.load_collection(collection_name=milvus_config.item_name_collection)
    logger.info(f"保存了item_name:{item_name}的数据到向量数据库中！！")


def node_item_name_recognition(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 主体识别 (node_item_name_recognition)
    识别文档核心描述的物品/商品名称，并将 item_name 存入每个 chunk 和 Milvus。
    """
    function_name = sys._getframe().f_code.co_name
    logger.info(f">>> [{function_name}]开始执行了！现在的状态为：{state}")
    add_running_task(state['task_id'], function_name)
    try:
        chunks, file_title = step_1_get_chunks(state)
        context = step_2_build_context(chunks)
        item_name = step_3_call_llm(context, file_title)
        step_4_update_chunks_and_state(state, item_name, chunks)
        dense_vector, sparse_vector = step_5_generate_embeddings(item_name)
        step_6_save_to_vector_db(file_title, item_name, dense_vector, sparse_vector)
    except Exception as e:
        logger.error(f">>> [{function_name}]主体识别发生了异常，异常信息：{e}")
        raise
    finally:
        logger.info(f">>> [{function_name}]开始结束了！现在的状态为：{state}")
        add_done_task(state['task_id'], function_name)
    return state
