import asyncio
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 核心优化：用异步队列存储每个会话的待推送数据（替代列表+轮询）
task_queues = {}


async def long_task(session_id: str):
    queue = asyncio.Queue()
    task_queues[session_id] = queue

    for i in range(5):
        msg = f"会话{session_id}处理结果{i + 1}"
        await queue.put(msg)
        await asyncio.sleep(1)

    # 关键：丢一个"结束标记"，告诉SSE可以停止了
    await queue.put(None)


@app.get("/submit/{session_id}")
async def submit_task(session_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(long_task, session_id)
    return {"message": "任务已启动", "session_id": session_id}


# 简化后的SSE接口：直接从队列取数据，没有轮询！
@app.get("/stream/{session_id}")
async def stream_result(session_id: str):
    async def event_generator():
        while session_id not in task_queues:
            await asyncio.sleep(0.1)
        queue = task_queues[session_id]

        while True:
            msg = await queue.get()  # 阻塞等待队列数据（比轮询高效）
            if msg is None:
                break
            yield f"data: {msg}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
