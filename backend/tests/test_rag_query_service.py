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

    def test_source_refs_use_compact_display_text(self) -> None:
        long_text = "傅里叶变换" + "，包含完整字幕" * 80
        result = self.service.query(
            "傅里叶变换",
            [
                RagDocument(
                    text=long_text,
                    metadata={
                        "session_id": "lec_query",
                        "type": "structured_note",
                        "source_id": "structured_notes",
                        "display_text": "结构化课堂笔记：傅里叶变换用于频域分析。",
                    },
                )
            ],
        )

        self.assertEqual(
            result.source_refs[0].text,
            "结构化课堂笔记：傅里叶变换用于频域分析。",
        )
        self.assertNotIn("完整字幕", result.answer)

    def test_query_limits_source_refs_for_display(self) -> None:
        documents = [
            RagDocument(
                text=f"傅里叶变换相关内容 {index}",
                metadata={
                    "session_id": "lec_query",
                    "type": "segment",
                    "source_id": f"seg_{index:03d}",
                },
            )
            for index in range(5)
        ]

        result = self.service.query("傅里叶变换", documents, limit=5)

        self.assertEqual(len(result.source_refs), 3)


if __name__ == "__main__":
    unittest.main()
