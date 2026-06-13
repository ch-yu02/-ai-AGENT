"""OpenAI-compatible 云端 LLM 客户端。

第一版不引入额外 SDK，直接使用标准库 ``urllib`` 请求
``/chat/completions``。这样后端依赖保持轻量，也方便 DeepSeek、OpenAI 或
其他兼容 OpenAI Chat Completions 协议的供应商复用同一套代码。
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .settings import LLMSettings


class CloudLLMError(Exception):
    """云端模型调用失败时抛出的领域错误。

    skills 层会捕获这个错误并回退规则版实现，避免模型故障影响课堂数据保存。
    """


@dataclass(frozen=True)
class CloudLLMResponse:
    """一次模型调用的规范化结果。"""

    content: str
    """模型返回的文本内容。"""
    model: str
    """实际使用的模型名。"""
    provider: str
    """供应商标识。"""


class CloudLLMClient:
    """统一封装云端 Chat Completions 调用。"""

    def __init__(self, settings: LLMSettings) -> None:
        if not settings.enabled:
            raise CloudLLMError("LLM_API_KEY is not configured")
        self.settings = settings

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
    ) -> CloudLLMResponse:
        """请求模型返回普通文本。

        重试策略保持克制：网络波动或 5xx 等错误会按 ``max_retries`` 重试；
        每次重试之间做一个很短的线性退避，避免本地测试时等待太久。
        """
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                payload = self._request_payload(system_prompt, user_prompt, temperature)
                response_payload = self._post_json("/chat/completions", payload)
                content = self._extract_message_content(response_payload)
                return CloudLLMResponse(
                    content=content,
                    model=str(response_payload.get("model", self.settings.model)),
                    provider=self.settings.provider,
                )
            except (CloudLLMError, OSError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                time.sleep(0.2 * (attempt + 1))

        raise CloudLLMError(f"Cloud LLM request failed: {last_error}") from last_error

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """请求模型返回 JSON object，并做最小结构校验。

        很多模型即使被要求输出 JSON，也可能包一层 Markdown code fence。这里先
        解析完整文本，失败后再提取第一个 ``{...}`` 片段，尽量兼容常见输出。
        """
        response = self.complete(
            system_prompt,
            user_prompt,
            temperature=temperature,
        )
        return _parse_json_object(response.content)

    def _request_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> dict[str, Any]:
        """构造 OpenAI-compatible Chat Completions 请求体。"""
        return {
            "model": self.settings.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON POST 请求并返回 JSON object。"""
        headers = {"Content-Type": "application/json"}
        # 本地 OpenAI-compatible 服务通常不需要 API key；云端 provider 才附加
        # Authorization。这样 ``LLM_PROVIDER=local`` 可以直接连 Ollama/vLLM。
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        request = urllib.request.Request(
            f"{self.settings.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - URL 来自后端受控配置。
                request,
                timeout=self.settings.timeout_seconds,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise CloudLLMError(f"Cloud LLM HTTP {exc.code}: {body}") from exc
        except json.JSONDecodeError as exc:
            raise CloudLLMError("Cloud LLM returned non-JSON response") from exc

        if not isinstance(data, dict):
            raise CloudLLMError("Cloud LLM response must be a JSON object")
        return data

    def _extract_message_content(self, payload: dict[str, Any]) -> str:
        """从 Chat Completions 响应中提取 assistant 文本。"""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise CloudLLMError("Cloud LLM response missing choices")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise CloudLLMError("Cloud LLM choice must be an object")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise CloudLLMError("Cloud LLM choice missing message")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise CloudLLMError("Cloud LLM message content is empty")
        return content.strip()


def _parse_json_object(content: str) -> dict[str, Any]:
    """把模型文本解析成 JSON object。"""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = _strip_code_fence(stripped)

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise CloudLLMError("Cloud LLM did not return JSON object")
        data = json.loads(stripped[start : end + 1])

    if not isinstance(data, dict):
        raise CloudLLMError("Cloud LLM JSON output must be an object")
    return data


def _strip_code_fence(content: str) -> str:
    """去掉常见 Markdown JSON code fence。"""
    lines = content.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return content
