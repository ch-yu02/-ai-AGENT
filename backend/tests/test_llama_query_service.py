import unittest
from unittest.mock import patch

from backend.app.rag import (
    LlamaIndexQueryService,
    QueryService,
    build_query_service,
)
from backend.app.rag.documents import RagDocument


class FakeLlamaDocument:
    """测试用 LlamaIndex Document 替身。"""

    def __init__(self, text: str, metadata: dict) -> None:
        self.text = text
        self.metadata = metadata

    def get_content(self) -> str:
        return self.text


class FakeSourceNode:
    """模拟 LlamaIndex response.source_nodes 里的包装对象。"""

    def __init__(self, node: FakeLlamaDocument) -> None:
        self.node = node


class FakeResponse:
    """模拟 query engine 返回对象。"""

    def __init__(self, text: str, source_nodes: list[FakeSourceNode]) -> None:
        self.text = text
        self.source_nodes = source_nodes

    def __str__(self) -> str:
        return self.text


class FakeQueryEngine:
    """模拟 LlamaIndex QueryEngine。"""

    def __init__(self, documents: list[FakeLlamaDocument]) -> None:
        self.documents = documents

    def query(self, prompt: str) -> FakeResponse:
        return FakeResponse(
            text=f"基于 LlamaIndex 的回答：{prompt}",
            source_nodes=[FakeSourceNode(self.documents[0])],
        )


class FakeVectorStoreIndex:
    """模拟 VectorStoreIndex.from_documents。"""

    def __init__(self, documents: list[FakeLlamaDocument]) -> None:
        self.documents = documents

    @classmethod
    def from_documents(cls, documents: list[FakeLlamaDocument]) -> "FakeVectorStoreIndex":
        return cls(documents)

    def as_query_engine(self, similarity_top_k: int) -> FakeQueryEngine:
        return FakeQueryEngine(self.documents[:similarity_top_k])


class FailingVectorStoreIndex:
    """模拟 LlamaIndex 初始化失败，用于验证 fallback。"""

    @classmethod
    def from_documents(cls, documents: list[FakeLlamaDocument]) -> "FailingVectorStoreIndex":
        raise RuntimeError("index unavailable")


class LlamaIndexQueryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = [
            RagDocument(
                text="[1.00s-3.00s] 傅里叶变换可以把时域信号转换到频域。",
                metadata={
                    "session_id": "lec_llama_001",
                    "type": "segment",
                    "source_id": "seg_001",
                    "ts": 1.0,
                },
            )
        ]

    def test_query_maps_llamaindex_sources_to_rag_refs(self) -> None:
        service = LlamaIndexQueryService(
            document_factory=FakeLlamaDocument,
            index_factory=FakeVectorStoreIndex,
        )

        result = service.query("傅里叶变换讲了什么？", self.documents)

        self.assertIn("基于 LlamaIndex", result.answer)
        self.assertEqual(result.source_refs[0].id, "seg_001")
        self.assertEqual(result.source_refs[0].type, "segment")
        self.assertEqual(result.source_refs[0].ts, 1.0)

    def test_query_falls_back_to_lexical_when_llamaindex_fails(self) -> None:
        service = LlamaIndexQueryService(
            fallback=QueryService(),
            document_factory=FakeLlamaDocument,
            index_factory=FailingVectorStoreIndex,
        )

        result = service.query("傅里叶变换", self.documents)

        self.assertIn("我在课堂资料中找到", result.answer)
        self.assertEqual(result.source_refs[0].id, "seg_001")
        self.assertTrue(any("已回退词法检索" in warning for warning in result.warnings))

    def test_factory_selects_llamaindex_backend_from_environment(self) -> None:
        with patch.dict("os.environ", {"RAG_QUERY_BACKEND": "llamaindex"}):
            service = build_query_service()

        self.assertIsInstance(service, LlamaIndexQueryService)


if __name__ == "__main__":
    unittest.main()
