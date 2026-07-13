"""
data_agent — 通用 AI 数据代理

提供可复用的数据处理、分析和 AI 交互能力。
"""

from .agent import Agent
from .config import AgentConfig

__all__ = ["Agent", "AgentConfig"]
__version__ = "0.1.0"
