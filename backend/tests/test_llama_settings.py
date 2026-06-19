import unittest
from unittest.mock import patch

from backend.app.rag import llama_settings


class FakeSettings:
    llm = object()
    embed_model = None


class LlamaSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        llama_settings._CONFIGURED_SIGNATURE = None
        FakeSettings.llm = object()
        FakeSettings.embed_model = None

    def test_can_disable_llamaindex_llm_without_embedding_imports(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RAG_EMBEDDING_BACKEND": "default",
                "RAG_LLAMAINDEX_LLM": "disabled",
            },
            clear=False,
        ):
            llama_settings.configure_llamaindex_settings(FakeSettings)

        self.assertIsNone(FakeSettings.llm)
        self.assertIsNone(FakeSettings.embed_model)

    def test_rejects_unknown_embedding_backend(self) -> None:
        with patch.dict(
            "os.environ",
            {"RAG_EMBEDDING_BACKEND": "mystery"},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "Unsupported"):
                llama_settings.configure_llamaindex_settings(FakeSettings)


if __name__ == "__main__":
    unittest.main()
