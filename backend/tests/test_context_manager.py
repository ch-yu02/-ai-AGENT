import unittest

from backend.app.core import ContextEventError, ContextManager, ContextNotFoundError
from backend.app.models import RealtimeEvent


class ContextManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ContextManager()
        self.session_id = "lec_test_001"
        self.manager.start_session(self.session_id)

    def test_handle_transcript_segment_updates_transcript_and_timeline(self) -> None:
        update = self.manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="transcript.segment",
                payload={
                    "start_ts": 12.0,
                    "end_ts": 15.0,
                    "text": "这是考试重点。",
                    "importance": 0.9,
                },
            )
        )

        context = self.manager.get_context(self.session_id)
        self.assertEqual(update.transcript_count, 1)
        self.assertEqual(context.transcript[0].text, "这是考试重点。")
        self.assertEqual(context.timeline[0].type, "transcript")
        self.assertEqual(context.important_segments, [context.transcript[0].segment_id])

    def test_handle_image_capture_updates_visuals(self) -> None:
        self.manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="image.capture",
                payload={
                    "capture_ts": 20.0,
                    "image_path": "local://slide.jpg",
                    "ocr_text": "傅里叶变换",
                    "image_type": "ppt",
                },
            )
        )

        context = self.manager.get_context(self.session_id)
        self.assertEqual(len(context.visuals), 1)
        self.assertEqual(context.visuals[0].ocr_text, "傅里叶变换")
        self.assertEqual(context.timeline[0].title, "傅里叶变换")

    def test_handle_knowledge_extraction_updates_extractions(self) -> None:
        self.manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="knowledge.extraction",
                payload={
                    "timestamp_range": [30.0, 35.0],
                    "source_segment_ids": ["seg_001"],
                    "entities": [{"name": "傅里叶变换", "type": "concept"}],
                    "relations": [
                        {
                            "source": "傅里叶变换",
                            "target": "频域",
                            "relation": "maps_to",
                        }
                    ],
                    "importance": 0.95,
                },
            )
        )

        context = self.manager.get_context(self.session_id)
        compressed = self.manager.get_compressed_context(self.session_id)

        self.assertEqual(len(context.knowledge_extractions), 1)
        self.assertEqual(context.timeline[0].type, "knowledge")
        self.assertIn("傅里叶变换", compressed["knowledge_entities"])
        self.assertIn("seg_001", compressed["important_segments"])

    def test_timeline_is_sorted_by_timestamp(self) -> None:
        self.manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="transcript.segment",
                payload={"start_ts": 50.0, "end_ts": 51.0, "text": "后发生"},
            )
        )
        self.manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="image.capture",
                payload={"capture_ts": 10.0, "image_path": "local://early.jpg"},
            )
        )

        context = self.manager.get_context(self.session_id)
        self.assertEqual([item.ts for item in context.timeline], [10.0, 50.0])

    def test_unknown_context_and_event_type_raise_domain_errors(self) -> None:
        with self.assertRaises(ContextNotFoundError):
            self.manager.get_context("missing")

        with self.assertRaises(ContextEventError):
            self.manager.handle_event(
                RealtimeEvent(
                    session_id=self.session_id,
                    event_type="unsupported.event",
                    payload={},
                )
            )


if __name__ == "__main__":
    unittest.main()
