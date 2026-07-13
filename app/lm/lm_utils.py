from langchain_openai import ChatOpenAI
from langchain_core.exceptions import LangChainException
from typing import Optional

from app.conf.lm_config import lm_config
from app.core.logger import logger

# 全局缓存，避免重复初始化客户端
_llm_client_cache = {}


def get_llm_client(model: Optional[str] = None, json_mode: bool = False) -> ChatOpenAI:
    """
    获取带全局缓存的LangChain ChatOpenAI客户端实例
    适配OpenAI兼容API，支持自定义模型和JSON标准化输出

    :param model: 模型名称，优先级：传入参数 > 配置文件 > 内置默认qwen3-32b
    :param json_mode: 是否开启JSON输出模式
    :return: ChatOpenAI实例
    :raise ValueError: 缺失API密钥/基础地址等核心配置
    """
    target_model = model or lm_config.llm_model or "qwen3-32b"
    cache_key = (target_model, json_mode)

    if cache_key in _llm_client_cache:
        logger.debug(f"[LLM客户端] 缓存命中：模型={target_model}，JSON模式={json_mode}")
        return _llm_client_cache[cache_key]

    if not lm_config.api_key:
        raise ValueError("[LLM客户端] 配置缺失：请在.env中配置OPENAI_API_KEY")
    if not lm_config.base_url:
        raise ValueError("[LLM客户端] 配置缺失：请在.env中配置OPENAI_API_BASE")

    logger.info(f"[LLM客户端] 开始初始化新实例：模型={target_model}，JSON模式={json_mode}")

    model_kwargs = {}
    extra_body = {}
    if json_mode:
        model_kwargs["response_format"] = {"type": "json_object"}

    try:
        llm_client = ChatOpenAI(
            model=target_model,
            temperature=lm_config.llm_temperature or 0.1,
            api_key=lm_config.api_key,
            base_url=lm_config.base_url,
            extra_body=extra_body,
            model_kwargs=model_kwargs,
        )
    except LangChainException as e:
        raise Exception(f"[LLM客户端] 模型【{target_model}】初始化失败（LangChain层）：{str(e)}") from e

    _llm_client_cache[cache_key] = llm_client
    logger.info(f"[LLM客户端] 实例初始化成功并缓存：模型={target_model}，JSON模式={json_mode}")

    return llm_client
