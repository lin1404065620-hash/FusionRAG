"""核心代理逻辑"""

from typing import Any, Callable
from .config import AgentConfig
from .tools import ToolRegistry, default_tools


class Agent:
    """通用 AI 数据代理

    提供数据处理、分析和 AI 交互的核心调度能力。
    """

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self.tools = ToolRegistry()
        self._register_default_tools()
        self._history: list[dict] = []

    def _register_default_tools(self) -> None:
        for tool in default_tools:
            self.tools.register(tool)

    def register_tool(self, name: str, fn: Callable, description: str = "") -> None:
        """注册自定义工具"""
        self.tools.register({"name": name, "fn": fn, "description": description})

    def run(self, task: str, **kwargs: Any) -> dict[str, Any]:
        """执行任务

        Args:
            task: 任务描述
            **kwargs: 传递给工具的额外参数

        Returns:
            执行结果字典，包含 status 和 data
        """
        self._history.append({"task": task, "kwargs": kwargs})

        if task == "read_csv":
            return self._execute_read_csv(kwargs)
        if task == "analyze":
            return self._execute_analyze(kwargs)
        if task == "transform":
            return self._execute_transform(kwargs)

        return {"status": "unknown_task", "data": None, "message": f"未知任务: {task}"}

    def _execute_read_csv(self, kwargs: dict) -> dict:
        if not kwargs.get("path"):
            return {"status": "error", "data": None, "message": "缺少 path 参数"}
        return self.tools.call("read_csv", **kwargs)

    def _execute_analyze(self, kwargs: dict) -> dict:
        if kwargs.get("dataframe") is None:
            return {"status": "error", "data": None, "message": "缺少 dataframe 参数"}
        return self.tools.call("analyze", **kwargs)

    def _execute_transform(self, kwargs: dict) -> dict:
        if kwargs.get("dataframe") is None:
            return {"status": "error", "data": None, "message": "缺少 dataframe 参数"}
        tool_kwargs = {k: v for k, v in kwargs.items() if k not in ("dataframe",)}
        return self.tools.call("transform", dataframe=kwargs["dataframe"], **tool_kwargs)

    @property
    def history(self) -> list[dict]:
        return self._history

    def __repr__(self) -> str:
        return f"Agent(name={self.config.name}, tools={len(self.tools)})"
