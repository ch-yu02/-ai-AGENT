import unittest

from backend.app.rag import QueryService, RagDocument


class RagQueryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = QueryService()

    def test_query_returns_ranked_source_refs(self) -> None:
        documents = [
            RagDocument(
                text="[1.00s-3.00s] 傅里叶变换可以把时域信号转换到频域。",
                metadata={
                    "session_id": "lec_query",
                    "type": "segment",
                    "source_id": "seg_001",
                    "ts": 1.0,
                },
            ),
            RagDocument(
                text="知识点：采样定理。说明：描述信号采样恢复条件。",
                metadata={
                    "session_id": "lec_query",
                    "type": "knowledge_node",
                    "source_id": "node_sampling",
                },
            ),
        ]

        result = self.service.query("傅里叶变换讲了什么？", documents)

        self.assertIn("傅里叶变换", result.answer)
        self.assertEqual(result.source_refs[0].id, "seg_001")
        self.assertEqual(result.source_refs[0].ts, 1.0)
        self.assertEqual(result.warnings, [])

    def test_query_returns_warning_when_no_source_matches(self) -> None:
        result = self.service.query(
            "矩阵分解讲了什么？",
            [
                RagDocument(
                    text="知识点：采样定理。",
                    metadata={
                        "session_id": "lec_query",
                        "type": "knowledge_node",
                        "source_id": "node_sampling",
                    },
                )
            ],
        )

        self.assertEqual(result.source_refs, [])
        self.assertIn("没有在课堂资料中找到", result.answer)
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
