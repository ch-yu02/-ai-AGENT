import unittest
from unittest.mock import patch

from backend.app.llm import CloudLLMClient, CloudLLMError, LLMSettings, load_llm_settings


class CloudLLMClientTest(unittest.TestCase):
    def test_settings_without_api_key_disables_llm(self) -> None:
        with patch.dict("os.environ", {"LLM_API_KEY": ""}, clear=False):
            settings = load_llm_settings()

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.provider, "deepseek")
        self.assertEqual(settings.model, "deepseek-chat")

    def test_complete_json_accepts_markdown_json_fence(self) -> None:
        client = CloudLLMClient(self._settings())

        # 单元测试不访问真实网络，而是替换客户端内部 POST 方法，模拟
        # OpenAI-compatible /chat/completions 返回。
        client._post_json = lambda path, payload: {  # type: ignore[method-assign]
            "model": "fake-model",
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"summary_markdown":"课堂重点"}\n```'
                    }
                }
            ],
        }

        payload = client.complete_json("system", "user")

        self.assertEqual(payload["summary_markdown"], "课堂重点")

    def test_complete_raises_for_empty_choices(self) -> None:
        client = CloudLLMClient(self._settings())
        client._post_json = lambda path, payload: {"choices": []}  # type: ignore[method-assign]

        with self.assertRaises(CloudLLMError):
            client.complete("system", "user")

    def _settings(self) -> LLMSettings:
        return LLMSettings(
            provider="fake",
            api_key="test-key",
            model="fake-model",
            base_url="https://example.invalid/v1",
            timeout_seconds=1,
            max_retries=0,
        )


if __name__ == "__main__":
    unittest.main()
