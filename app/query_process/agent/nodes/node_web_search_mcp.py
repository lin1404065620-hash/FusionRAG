import asyncio
import json
import sys
from agents.mcp import MCPServerStreamableHttp
from app.core.logger import logger

from app.conf.bailian_mcp_config import mcp_config
from app.utils.task_utils import add_running_task, add_done_task

DASHSCOPE_BASE_URL = mcp_config.mcp_base_url
DASHSCOPE_API_KEY = mcp_config.api_key


async def mcp_call_search(query):
    """
    通过 MCP 连接调用百炼网络搜索工具。
    """
    search_mcp = MCPServerStreamableHttp(
        name="search_mcp",
        params={
            "url": DASHSCOPE_BASE_URL,
            "headers": {"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
            "timeout": 10,
        },
        max_retry_attempts=3
    )
    try:
        await search_mcp.connect()
        tools = await search_mcp.list_tools()
        logger.debug(f"MCP 可用工具列表：{tools}")
        result = await search_mcp.call_tool(
            tool_name="bailian_web_search",
            arguments={
                "query": query,
                "count": 5,
            }
        )
        return result
    except Exception:
        logger.exception("MCP 网络搜索调用失败")
        raise
    finally:
        await search_mcp.cleanup()


def node_web_search_mcp(state):
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state["is_stream"])

    query = state.get("rewritten_query")
    result = asyncio.run(mcp_call_search(query))

    web_documents = json.loads(result.content[0].text).get("pages", [])

    logger.info(f"mcp搜索的结果为:{web_documents}")
    add_done_task(state["session_id"], sys._getframe().f_code.co_name, state["is_stream"])
    return {
        "web_search_docs": web_documents
    }
