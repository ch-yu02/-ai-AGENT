import unittest
import tempfile
from pathlib import Path
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
        self.storage_context = FakePersistableStorageContext()

    @classmethod
    def from_documents(cls, documents: list[FakeLlamaDocument]) -> "FakeVectorStoreIndex":
        return cls(documents)

    def as_query_engine(self, similarity_top_k: int) -> FakeQueryEngine:
        return FakeQueryEngine(self.documents[:similarity_top_k])


class FakePersistableStorageContext:
    """模拟可 persist 的 LlamaIndex storage_context。"""

    def persist(self, persist_dir: str) -> None:
        path = Path(persist_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "docstore.json").write_text("{}", encoding="utf-8")


class FakeStorageContext:
    """模拟 StorageContext.from_defaults(persist_dir=...)。"""

    loaded_dirs: list[str] = []

    @classmethod
    def from_defaults(cls, persist_dir: str) -> "FakeStorageContext":
        cls.loaded_dirs.append(persist_dir)
        return cls()


def fake_load_index_from_storage(storage_context: FakeStorageContext) -> FakeVectorStoreIndex:
    """模拟 load_index_from_storage，返回一个可查询索引。"""
    return FakeVectorStoreIndex(
        [
            FakeLlamaDocument(
                text="已加载的持久化索引内容",
                metadata={
                    "session_id": "lec_llama_001",
                    "type": "segment",
                    "source_id": "seg_loaded",
                    "ts": 9.0,
                },
            )
        ]
    )


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
        FakeStorageContext.loaded_dirs = []

    def _service(self, **kwargs) -> LlamaIndexQueryService:
        return LlamaIndexQueryService(
            document_factory=FakeLlamaDocument,
            index_factory=FakeVectorStoreIndex,
            storage_context_factory=FakeStorageContext,
            load_index_func=fake_load_index_from_storage,
            **kwargs,
        )

    def test_query_maps_llamaindex_sources_to_rag_refs(self) -> None:
        service = self._service()

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
            storage_context_factory=FakeStorageContext,
            load_index_func=fake_load_index_from_storage,
        )

        result = service.query("傅里叶变换", self.documents)

        self.assertIn("我在课堂资料中找到", result.answer)
        self.assertEqual(result.source_refs[0].id, "seg_001")
        self.assertTrue(any("已回退词法检索" in warning for warning in result.warnings))

    def test_build_and_persist_writes_index_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self._service(
                index_dir_resolver=lambda session_id: Path(temp_dir) / session_id / "llama_index"
            )

            index_dir = service.build_and_persist(self.documents)

            self.assertTrue(index_dir.exists())
            self.assertTrue((index_dir / "docstore.json").exists())

    def test_query_loads_persisted_index_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_dir = Path(temp_dir) / "lec_llama_001" / "llama_index"
            index_dir.mkdir(parents=True)
            (index_dir / "docstore.json").write_text("{}", encoding="utf-8")
            service = self._service(
                index_dir_resolver=lambda session_id: Path(temp_dir) / session_id / "llama_index"
            )

            result = service.query("傅里叶变换", self.documents)

            self.assertEqual(result.source_refs[0].id, "seg_loaded")
            self.assertEqual(FakeStorageContext.loaded_dirs, [str(index_dir)])

    def test_factory_selects_llamaindex_backend_from_environment(self) -> None:
        with patch.dict("os.environ", {"RAG_QUERY_BACKEND": "llamaindex"}):
            service = build_query_service()

        self.assertIsInstance(service, LlamaIndexQueryService)


if __name__ == "__main__":
    unittest.main()
