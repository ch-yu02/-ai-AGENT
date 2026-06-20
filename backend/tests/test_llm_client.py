import unittest
from unittest.mock import patch

from backend.app.llm import CloudLLMClient, CloudLLMError, LLMSettings, load_llm_settings


class CloudLLMClientTest(unittest.TestCase):
    def test_settings_without_api_key_disables_llm(self) -> None:
        with patch.dict("os.environ", {"LLM_PROVIDER": "deepseek", "LLM_API_KEY": ""}, clear=True):
            settings = load_llm_settings()

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.provider, "deepseek")
        self.assertEqual(settings.model, "deepseek-v4-flash")
        self.assertEqual(settings.base_url, "https://api.deepseek.com")

    def test_local_provider_is_enabled_without_api_key(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "local",
                "LLM_API_KEY": "",
                "LLM_MODEL": "",
                "LLM_BASE_URL": "",
            },
            clear=True,
        ):
            settings = load_llm_settings()

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.provider, "local")
        self.assertEqual(settings.model, "llama3.1")
        self.assertEqual(settings.base_url, "http://127.0.0.1:11434/v1")

    def test_kimi_provider_defaults_to_moonshot_api(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "kimi",
                "LLM_API_KEY": "test-key",
                "LLM_MODEL": "",
                "LLM_BASE_URL": "",
            },
            clear=True,
        ):
            settings = load_llm_settings()

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.provider, "kimi")
        self.assertEqual(settings.model, "kimi-k2.6")
        self.assertEqual(settings.base_url, "https://api.moonshot.cn/v1")

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

    def test_local_provider_request_omits_authorization_without_api_key(self) -> None:
        client = CloudLLMClient(
            LLMSettings(
                provider="local",
                api_key=None,
                model="llama3.1",
                base_url="http://127.0.0.1:11434/v1",
                timeout_seconds=1,
                max_retries=0,
            )
        )
        captured_headers: dict[str, str] = {}

        def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
            captured_headers.update(request.headers)
            return _FakeHttpResponse(
                b'{"choices":[{"message":{"content":"local ok"}}]}'
            )

        with patch("urllib.request.urlopen", fake_urlopen):
            response = client.complete("system", "user")

        self.assertEqual(response.content, "local ok")
        self.assertNotIn("Authorization", captured_headers)

    def test_kimi_provider_forces_temperature_to_one(self) -> None:
        client = CloudLLMClient(
            LLMSettings(
                provider="kimi",
                api_key="test-key",
                model="kimi-k2.6",
                base_url="https://api.moonshot.cn/v1",
                timeout_seconds=1,
                max_retries=0,
            )
        )
        captured_payload: dict[str, object] = {}

        def fake_post(path, payload):  # type: ignore[no-untyped-def]
            captured_payload.update(payload)
            return {
                "model": "kimi-k2.6",
                "choices": [
                    {"message": {"content": '{"caption":"ok"}'}},
                ],
            }

        client._post_json = fake_post  # type: ignore[method-assign]

        result = client.complete_json_with_image(
            "system",
            "user",
            image_bytes=b"fake-image",
            media_type="image/jpeg",
            temperature=0.1,
        )

        self.assertEqual(result["caption"], "ok")
        self.assertEqual(captured_payload["temperature"], 1)

    def _settings(self) -> LLMSettings:
        return LLMSettings(
            provider="fake",
            api_key="test-key",
            model="fake-model",
            base_url="https://example.invalid/v1",
            timeout_seconds=1,
            max_retries=0,
        )


class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


if __name__ == "__main__":
    unittest.main()
