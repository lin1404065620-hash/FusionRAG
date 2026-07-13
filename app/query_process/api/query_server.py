import uuid

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from app.core.logger import logger
from app.query_process.agent.state import create_query_default_state
from app.utils.path_util import PROJECT_ROOT

from app.utils.task_utils import *
from app.utils.sse_utils import create_sse_queue, SSEEvent, sse_generator
from app.clients.mongo_history_utils import *
from app.query_process.agent.main_graph import query_app


app = FastAPI(title="query service", description="掌柜智库查询服务！")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    logger.info(f"触发后台检测检查接口，数据一切正常！！")
    return {"status": "ok"}


@app.get("/chat.html")
async def chat_html():
    chat_html_path = PROJECT_ROOT / 'app' / 'query_process' / 'page' / 'chat.html'
    if not chat_html_path.exists():
        raise HTTPException(status_code=404, detail="chat.html文件不存在")
    return FileResponse(chat_html_path)


class QueryRequest(BaseModel):
    query: str = Field(..., title="查询内容,必须传递")
    session_id: str = Field(None, title="会话id，可以不传递，后台uuid生成第一个！")
    is_stream: bool = Field(False, title="是否流式返回结果")


def run_query_graph(query: str, session_id: str, is_stream: bool):
    update_task_status(session_id, "processing", is_stream)

    state = create_query_default_state(
        session_id=session_id,
        original_query=query,
        is_stream=is_stream
    )
    try:
        query_app.invoke(state)
        update_task_status(session_id, "completed", is_stream)
    except Exception as e:
        logger.exception(f"---session_id = {session_id},查询流程出现异常！！{str(e)}")
        update_task_status(session_id, "failed", is_stream)
        push_to_session(session_id, SSEEvent.ERROR, {"error": str(e)})


@app.post("/query")
async def query(request: QueryRequest, background_tasks: BackgroundTasks):
    query_text = request.query
    session_id = request.session_id or str(uuid.uuid4())
    is_stream = request.is_stream

    if is_stream:
        create_sse_queue(session_id)
        background_tasks.add_task(run_query_graph, query_text, session_id, is_stream)
        logger.info(f"query:{query_text}已经开启了异步和流式处理！！")
        return {
            "session_id": session_id,
            "message": "本次查询处理中...."
        }
    else:
        run_query_graph(query_text, session_id, is_stream)
        answer = get_task_result(session_id, "answer")
        image_urls = get_task_result(session_id, "image_urls") or []
        logger.info(f"query:{query_text}开启同步处理！处理结果为：{answer}!")
        return {
            "answer": answer,
            "session_id": session_id,
            "message": "本次查询处理完毕！",
            "image_urls": image_urls,
            "done_list": []
        }


@app.get("/stream/{session_id}")
async def stream(session_id: str, request: Request):
    logger.info(f"session_id = {session_id}客户端，已经和后台建立了长连接！")
    return StreamingResponse(
        sse_generator(session_id, request),
        media_type="text/event-stream"
    )


@app.get("/history/{session_id}")
async def history(session_id: str, limit: int = 10):
    chats = get_recent_messages(session_id, limit)
    logger.info(f"查询历史对话，session_id = {session_id}成功！查询数据为：{chats}")
    return {
        "session_id": session_id,
        "items": chats
    }


@app.delete("/history/{session_id}")
async def delete_history(session_id: str):
    delete_count = clear_history(session_id)
    logger.info(f"删除历史对话，session_id = {session_id}成功,删除数量：{delete_count}！")
    return {
        "deleted_count": delete_count,
        "message": f"{session_id}聊天记录删除成功！"
    }


@app.on_event("startup")
async def startup():
    logger.info("导入文档页面: http://127.0.0.1:8000/import")
