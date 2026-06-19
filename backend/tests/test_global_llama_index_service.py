import tempfile
import unittest
from pathlib import Path

from backend.app.rag.documents import RagDocument
from backend.app.rag.global_index_service import GlobalLlamaIndexService


class FakeLlamaDocument:
    def __init__(self, text: str, metadata: dict) -> None:
        self.text = text
        self.metadata = metadata

    def get_content(self) -> str:
        return self.text


class FakeSourceNode:
    def __init__(self, node: FakeLlamaDocument, score: float = 0.91) -> None:
        self.node = node
        self.score = score


class FakeRetriever:
    def __init__(self, documents: list[FakeLlamaDocument]) -> None:
        self.documents = documents

    def retrieve(self, query: str) -> list[FakeSourceNode]:
        return [FakeSourceNode(document) for document in self.documents]


class FakeStorageContext:
    @classmethod
    def from_defaults(cls, persist_dir: str) -> "FakeStorageContext":
        return cls()


class FakePersistableStorageContext:
    def persist(self, persist_dir: str) -> None:
        path = Path(persist_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "docstore.json").write_text("{}", encoding="utf-8")


class FakeRetrieverVectorStoreIndex:
    def __init__(self, documents: list[FakeLlamaDocument]) -> None:
        self.documents = documents
        self.storage_context = FakePersistableStorageContext()

    @classmethod
    def from_documents(
        cls,
        documents: list[FakeLlamaDocument],
    ) -> "FakeRetrieverVectorStoreIndex":
        return cls(documents)

    def as_retriever(self, similarity_top_k: int) -> FakeRetriever:
        return FakeRetriever(self.documents[:similarity_top_k])


def fake_load_index_from_storage(
    storage_context: FakeStorageContext,
) -> FakeRetrieverVectorStoreIndex:
    return FakeRetrieverVectorStoreIndex([])


class GlobalLlamaIndexServiceTest(unittest.TestCase):
    def test_search_prefers_vector_retriever_and_maps_hits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = GlobalLlamaIndexService(
                index_root=Path(temp_dir),
                document_factory=FakeLlamaDocument,
                index_factory=FakeRetrieverVectorStoreIndex,
                storage_context_factory=FakeStorageContext,
                load_index_func=fake_load_index_from_storage,
            )
            documents = [
                RagDocument(
                    text="[1.00s-3.00s] 信道编码用于提高通信可靠性。",
                    metadata={
                        "session_id": "lec_global_vector",
                        "title": "通信原理第9讲",
                        "course": "通信原理",
                        "type": "segment",
                        "source_id": "seg_001",
                        "ts": 1.0,
                    },
                )
            ]
            records = [
                {
                    "session_id": "lec_global_vector",
                    "text": documents[0].text,
                    "metadata": documents[0].metadata,
                }
            ]

            hits = service.search(
                query="可靠性",
                records=records,
                documents=documents,
                limit=3,
            )

            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].session_id, "lec_global_vector")
            self.assertEqual(hits[0].source_id, "seg_001")
            self.assertGreater(hits[0].score, 1)


if __name__ == "__main__":
    unittest.main()
