"""云端 LLM 配置读取。

配置只从后端环境变量读取，避免 API key 出现在前端 bundle、浏览器请求或
本地保存的课堂文件里。没有配置 API key 时，系统保持离线规则版能力。
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMSettings:
    """一次模型客户端初始化所需的配置。"""

    provider: str
    """供应商标识，例如 deepseek / openai / openai_compatible。"""
    api_key: str | None
    """后端私有 API key。为空表示禁用云端模型。"""
    model: str
    """模型名称。不同 provider 有不同默认值。"""
    base_url: str
    """OpenAI-compatible API 根地址，不含末尾斜杠。"""
    timeout_seconds: float
    """单次请求超时时间。"""
    max_retries: int
    """失败后的重试次数。0 表示不重试。"""

    @property
    def enabled(self) -> bool:
        """是否启用云端模型。

        只要没有 API key，就视为禁用。这样开发、测试和离线演示都不会误触发
        网络请求。
        """
        return bool(self.api_key)


def load_llm_settings() -> LLMSettings:
    """从环境变量读取 LLM 配置。

    支持的变量：
    - ``LLM_PROVIDER``：默认 deepseek。
    - ``LLM_API_KEY``：为空时禁用云端模型。
    - ``LLM_MODEL``：为空时按 provider 选择默认模型。
    - ``LLM_BASE_URL``：为空时按 provider 选择 OpenAI-compatible 地址。
    - ``LLM_TIMEOUT_SECONDS``：默认 30。
    - ``LLM_MAX_RETRIES``：默认 1。
    """
    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower() or "deepseek"
    api_key = os.getenv("LLM_API_KEY") or None
    model = os.getenv("LLM_MODEL") or _default_model(provider)
    base_url = os.getenv("LLM_BASE_URL") or _default_base_url(provider)
    timeout_seconds = _float_env("LLM_TIMEOUT_SECONDS", 30.0)
    max_retries = _int_env("LLM_MAX_RETRIES", 1)

    return LLMSettings(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url.rstrip("/"),
        timeout_seconds=timeout_seconds,
        max_retries=max(0, max_retries),
    )


def _default_model(provider: str) -> str:
    """按 provider 选择保守默认模型。"""
    if provider == "openai":
        return "gpt-4o-mini"
    if provider == "deepseek":
        return "deepseek-chat"
    return "chat"


def _default_base_url(provider: str) -> str:
    """按 provider 选择 OpenAI-compatible API 地址。"""
    if provider == "openai":
        return "https://api.openai.com/v1"
    if provider == "deepseek":
        return "https://api.deepseek.com/v1"
    return "https://api.deepseek.com/v1"


def _float_env(name: str, default: float) -> float:
    """读取 float 环境变量，格式错误时回退默认值。"""
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    """读取 int 环境变量，格式错误时回退默认值。"""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
