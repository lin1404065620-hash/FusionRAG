import sys

from pymilvus import DataType

from app.import_process.agent.state import ImportGraphState
from app.clients.milvus_utils import get_milvus_client
from app.utils.task_utils import add_running_task, add_done_task
from app.core.logger import logger
from app.conf.milvus_config import milvus_config

CHUNKS_COLLECTION_NAME = milvus_config.chunks_collection


def step_2_prepare_collections(state):
    """创建 chunks 对应的 Milvus 集合（如果不存在）。"""
    milvus_client = get_milvus_client()
    if not milvus_client.has_collection(collection_name=milvus_config.chunks_collection):
        schema = milvus_client.create_schema(
            auto_id=True,
            enable_dynamic_field=True,
        )
        schema.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="parent_title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="part", datatype=DataType.INT8)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=1024)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

        index_params = milvus_client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_name="dense_vector_index",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 32, "efConstruction": 300},
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_type="SPARSE_INVERTED_INDEX",
            index_name="sparse_vector_index",
            metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE"},
        )
        milvus_client.create_collection(
            collection_name=milvus_config.chunks_collection,
            schema=schema,
            index_params=index_params
        )
    return milvus_client


def step_3_delete_old_data(milvus_client, item_name):
    """根据 item_name 删除旧数据，实现幂等导入。"""
    milvus_client.delete(collection_name=CHUNKS_COLLECTION_NAME,
                         filter=f"item_name=='{item_name}'")
    milvus_client.load_collection(collection_name=CHUNKS_COLLECTION_NAME)


def step_4_insert_collections(milvus_client, chunks):
    """批量插入 chunks 到 Milvus，并回显主键 ID。"""
    insert_result = milvus_client.insert(collection_name=CHUNKS_COLLECTION_NAME, data=chunks)
    insert_count = insert_result.get("insert_count", 0)
    logger.info(f"完成了数据插入，成功插入了 {insert_count} 条数据")

    ids = insert_result.get("ids", [])
    if ids and len(ids) == len(chunks):
        for index, chunk in enumerate(chunks):
            chunk['chunk_id'] = ids[index]

    return chunks


def node_import_milvus(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 导入向量库 (node_import_milvus)
    将处理好的向量数据写入 Milvus 数据库，支持根据 item_name 幂等覆盖。
    """
    function_name = sys._getframe().f_code.co_name
    logger.info(f">>> [{function_name}]开始执行了！现在的状态为：{state}")
    add_running_task(state['task_id'], function_name)
    try:
        chunks = state.get('chunks')
        if not chunks:
            logger.error(f">>> [{function_name}]没有chunks数据，请检查！")
            raise ValueError("没有chunks数据")

        milvus_client = step_2_prepare_collections(state)
        step_3_delete_old_data(milvus_client, chunks[0]['item_name'])
        with_id_chunks = step_4_insert_collections(milvus_client, chunks)

        state['chunks'] = with_id_chunks
    except Exception as e:
        logger.error(f">>> [{function_name}]导入chunks对应的向量数据库发生了异常，异常信息：{e}")
        raise
    finally:
        logger.info(f">>> [{function_name}]开始结束了！现在的状态为：{state}")
        add_done_task(state['task_id'], function_name)
    return state
