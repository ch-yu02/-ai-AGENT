import unittest

from backend.app.agent.knowledge_tree_notes import MarkdownKnowledgeTreeAgent
from backend.app.agent.schemas import NotesKnowledgeTreeUpdateRequest
from backend.app.models import KnowledgeNode, KnowledgeTree


class FakeJsonLLMClient:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls: list[dict[str, object]] = []

    def complete_json(self, system_prompt, user_prompt, *, temperature=0.1):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": temperature,
            }
        )
        if self.error:
            raise self.error
        return self.payload


class MarkdownKnowledgeTreeAgentTest(unittest.TestCase):
    def test_extracts_grounded_tree_and_normalizes_source_fields(self) -> None:
        client = FakeJsonLLMClient(
            {
                "extraction_id": "model_ext",
                "session_id": "wrong",
                "source_segment_ids": ["seg_001", "invented"],
                "entities": [
                    {"name": "傅里叶变换", "type": "concept", "description": "频域分析"},
                    {"name": "频域", "type": "concept"},
                    {"name": "课堂没有的概念", "type": "concept"},
                ],
                "relations": [
                    {
                        "source": "频域",
                        "target": "傅里叶变换",
                        "relation": "part_of",
                    }
                ],
                "importance": 1.2,
            }
        )
        agent = MarkdownKnowledgeTreeAgent(client)
        request = NotesKnowledgeTreeUpdateRequest(
            session_id="lec_notes",
            snapshot_id="snap_001",
            sequence=1,
            markdown="# 课堂笔记\n\n- 傅里叶变换用于频域分析。",
            source_segments=[
                {
                    "segment_id": "seg_001",
                    "start_ts": 2.0,
                    "end_ts": 6.0,
                    "text": "傅里叶变换用于频域分析。",
                }
            ],
        )

        result = agent.extract(
            request,
            KnowledgeTree(
                session_id="lec_notes",
                nodes=[KnowledgeNode(node_id="node_old", label="旧知识点")],
            ),
        )

        self.assertFalse(result.failed)
        self.assertIsNotNone(result.extraction)
        extraction = result.extraction
        assert extraction is not None
        self.assertEqual(extraction.session_id, "lec_notes")
        self.assertEqual(extraction.source_segment_ids, ["seg_001"])
        self.assertEqual(extraction.timestamp_range, (2.0, 6.0))
        self.assertEqual(extraction.importance, 1.0)
        self.assertEqual([entity.name for entity in extraction.entities], ["傅里叶变换", "频域"])
        self.assertEqual(extraction.relations[0].source, "傅里叶变换")
        self.assertEqual(extraction.relations[0].target, "频域")
        self.assertEqual(extraction.relations[0].relation, "contains")
        self.assertIn("Dropped ungrounded entity", "\n".join(result.warnings))
        self.assertIn("旧知识点", client.calls[0]["user_prompt"])

    def test_duplicate_markdown_hash_skips_without_model_call(self) -> None:
        agent = MarkdownKnowledgeTreeAgent(FakeJsonLLMClient({"entities": []}))
        request = NotesKnowledgeTreeUpdateRequest(
            session_id="lec_notes",
            snapshot_id="snap_001",
            markdown="# 空笔记",
            markdown_hash="hash_001",
        )

        agent.remember_processed("lec_notes", "hash_001")
        result = agent.extract(request, KnowledgeTree(session_id="lec_notes"))

        self.assertIsNone(result.extraction)
        self.assertFalse(result.failed)
        self.assertEqual(result.markdown_hash, "hash_001")
        self.assertIn("already processed", result.warnings[0])

    def test_missing_or_overbroad_source_ids_fall_back_to_recent_subtitles(self) -> None:
        source_segments = [
            {
                "segment_id": f"seg_{index:03d}",
                "start_ts": float(index),
                "end_ts": float(index) + 0.5,
                "text": f"第 {index} 段课堂字幕提到傅里叶变换。",
            }
            for index in range(1, 8)
        ]
        request = NotesKnowledgeTreeUpdateRequest(
            session_id="lec_notes",
            snapshot_id="snap_recent",
            sequence=3,
            markdown="# 课堂笔记\n\n- 傅里叶变换。",
            source_segments=source_segments,
        )
        graph = KnowledgeTree(session_id="lec_notes")

        fallback_agent = MarkdownKnowledgeTreeAgent(
            FakeJsonLLMClient(
                {
                    "entities": [{"name": "傅里叶变换", "type": "concept"}],
                    "relations": [],
                }
            )
        )
        fallback_result = fallback_agent.extract(request, graph)
        self.assertIsNotNone(fallback_result.extraction)
        assert fallback_result.extraction is not None
        self.assertEqual(
            fallback_result.extraction.source_segment_ids,
            ["seg_003", "seg_004", "seg_005", "seg_006", "seg_007"],
        )
        self.assertEqual(fallback_result.extraction.timestamp_range, (3.0, 7.5))

        overbroad_agent = MarkdownKnowledgeTreeAgent(
            FakeJsonLLMClient(
                {
                    "source_segment_ids": [item["segment_id"] for item in source_segments],
                    "entities": [{"name": "傅里叶变换", "type": "concept"}],
                    "relations": [],
                }
            )
        )
        overbroad_result = overbroad_agent.extract(request, graph)
        self.assertIsNotNone(overbroad_result.extraction)
        assert overbroad_result.extraction is not None
        self.assertEqual(
            overbroad_result.extraction.source_segment_ids,
            ["seg_003", "seg_004", "seg_005", "seg_006", "seg_007"],
        )

    def test_recent_source_segments_limit_citations_and_prompt_window(self) -> None:
        source_segments = [
            {
                "segment_id": f"seg_{index:03d}",
                "start_ts": float(index),
                "end_ts": float(index) + 0.5,
                "text": f"第 {index} 段课堂字幕提到傅里叶变换。",
            }
            for index in range(1, 8)
        ]
        client = FakeJsonLLMClient(
            {
                "source_segment_ids": ["seg_001", "seg_006"],
                "entities": [{"name": "傅里叶变换", "type": "concept"}],
                "relations": [],
            }
        )
        agent = MarkdownKnowledgeTreeAgent(client)
        request = NotesKnowledgeTreeUpdateRequest(
            session_id="lec_notes",
            snapshot_id="snap_recent_window",
            sequence=4,
            markdown="# 课堂笔记\n\n- 傅里叶变换。",
            source_segments=source_segments,
            recent_source_segments=source_segments[5:7],
        )

        result = agent.extract(request, KnowledgeTree(session_id="lec_notes"))

        self.assertIsNotNone(result.extraction)
        assert result.extraction is not None
        self.assertEqual(result.extraction.source_segment_ids, ["seg_006"])
        self.assertEqual(result.extraction.timestamp_range, (6.0, 6.5))
        prompt = client.calls[0]["user_prompt"]
        self.assertIn("recent_source_subtitle_count: 2", prompt)
        self.assertIn("seg_006", prompt)
        self.assertNotIn("id=seg_001", prompt)


if __name__ == "__main__":
    unittest.main()
