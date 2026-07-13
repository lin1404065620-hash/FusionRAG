import shutil
import uuid
from typing import List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.utils.path_util import PROJECT_ROOT
from app.utils.task_utils import (
    add_running_task,
    add_done_task,
    get_done_task_list,
    get_running_task_list,
    update_task_status,
    get_task_status,
)
from app.import_process.agent.state import get_default_state
from app.import_process.agent.main_graph import kb_import_app
from app.core.logger import logger


app = FastAPI(
    title="File Import Service",
    description="Web service for uploading files to Knowledge Base (PDF/MD -> 解析 -> 切分 -> 向量化 -> Milvus入库)"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/import", response_class=FileResponse)
async def get_import_page():
    import_html_path = PROJECT_ROOT / "app" / "import_process" / "page" / "import.html"
    if not import_html_path.exists():
        raise HTTPException(status_code=404, detail="导入页面不存在！！")
    return FileResponse(path=import_html_path, media_type="text/html")


def run_import_graph(task_id: str, local_file_path: str, local_dir: str):
    """
    在后台异步执行 LangGraph 导入全流程。
    """
    add_done_task(task_id, "upload_file")
    add_running_task(task_id, "upload_file")
    try:
        update_task_status(task_id, "processing")
        init_state = get_default_state()
        init_state["task_id"] = task_id
        init_state["local_file_path"] = local_file_path
        init_state["local_dir"] = local_dir
        for event in kb_import_app.stream(init_state):
            for node_name, result in event.items():
                logger.info(f"节点：{node_name}已经完成执行，执行结果为：{result}")
        update_task_status(task_id, "completed")
        logger.info(f"{task_id}:图状态执行完毕！！")
    except Exception as e:
        logger.exception("====图执行失败！发生异常====")
        update_task_status(task_id, "failed")


@app.post("/upload")
async def upload_file(background_tasks: BackgroundTasks,
                      files: List[UploadFile] = File(...)):
    """
    上传文件接口：接收文件存储到 /output/日期/uuid/ 目录，
    并异步开启 LangGraph 导入流程。
    """
    today_str = datetime.now().strftime("%Y%m%d")
    base_out_path = PROJECT_ROOT / "output" / today_str
    task_ids = []

    for file in files:
        task_id = str(uuid.uuid4())
        task_ids.append(task_id)
        add_running_task(task_id, "upload_file")

        dir_path = base_out_path / task_id
        dir_path.mkdir(parents=True, exist_ok=True)
        local_file_path = dir_path / file.filename
        with local_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        background_tasks.add_task(run_import_graph, task_id, str(local_file_path), str(dir_path))
        logger.info(f"{task_id}:完成文件上传，并开启了对应的异步任务！！")
        add_done_task(task_id, "upload_file")

    return {
        "code": 200,
        "message": f"完成了文件上传，并开启了异步任务！文件数量为: {len(files)}",
        "task_ids": task_ids
    }


@app.get("/status/{task_id}", summary="任务状态查询", description="根据TaskID查询单个文件的处理进度和全局状态")
async def get_task_progress(task_id: str):
    """
    任务状态查询接口，前端轮询此接口获取任务的实时处理进度。
    """
    task_status_info: Dict[str, Any] = {
        "code": 200,
        "task_id": task_id,
        "status": get_task_status(task_id),
        "done_list": get_done_task_list(task_id),
        "running_list": get_running_task_list(task_id)
    }
    logger.info(
        f"[{task_id}] 任务状态查询，当前状态：{task_status_info['status']}，已完成节点：{task_status_info['done_list']}")
    return task_status_info
