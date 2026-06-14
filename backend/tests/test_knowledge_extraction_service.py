import unittest

from backend.app.core import ContextManager, KnowledgeGraphManager
from backend.app.extraction import KnowledgeExtractionService, RuleKnowledgeExtractor
from backend.app.models import RealtimeEvent


class KnowledgeExtractionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_id = "lec_service_extract_001"
        self.context_manager = ContextManager()
        self.graph_manager = KnowledgeGraphManager()
        self.context = self.context_manager.start_session(self.session_id)
        self.graph_manager.start_session(self.session_id)
        self.service = KnowledgeExtractionService(RuleKnowledgeExtractor())

    def test_extract_and_apply_routes_internal_events_to_context_and_graph(self) -> None:
        self.context_manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="transcript.segment",
                payload={
                    "segment_id": "seg_001",
                    "start_ts": 1.0,
                    "end_ts": 4.0,
                    "text": "傅里叶变换可以把时域信号转换到频域。",
                },
            )
        )

        result = self.service.extract_and_apply(
            context=self.context,
            context_manager=self.context_manager,
            knowledge_graph_manager=self.graph_manager,
        )

        graph = self.graph_manager.get_graph(self.session_id)

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.extractions), 1)
        self.assertEqual(len(self.context.knowledge_extractions), 1)
        self.assertEqual(self.context.timeline[-1].type, "knowledge")
        self.assertGreaterEqual(len(graph.nodes), 2)
        self.assertGreaterEqual(len(graph.edges), 1)

    def test_realtime_trigger_waits_for_transcript_batch(self) -> None:
        for index in range(2):
            self.context_manager.handle_event(
                RealtimeEvent(
                    session_id=self.session_id,
                    event_type="transcript.segment",
                    payload={
                        "segment_id": f"seg_00{index + 1}",
                        "start_ts": float(index),
                        "end_ts": float(index + 1),
                        "text": "采样定理是通信系统的重要概念。",
                    },
                )
            )

        event = RealtimeEvent(
            session_id=self.session_id,
            event_type="transcript.segment",
            payload={"segment_id": "seg_002"},
        )
        self.assertFalse(self.service.should_extract_realtime(self.context, event))

        self.context_manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="transcript.segment",
                payload={
                    "segment_id": "seg_003",
                    "start_ts": 2.0,
                    "end_ts": 3.0,
                    "text": "傅里叶变换可以把时域信号转换到频域。",
                },
            )
        )
        event = RealtimeEvent(
            session_id=self.session_id,
            event_type="transcript.segment",
            payload={"segment_id": "seg_003"},
        )
        self.assertTrue(self.service.should_extract_realtime(self.context, event))

    def test_realtime_trigger_accepts_processed_visual_with_text(self) -> None:
        self.context_manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="image.capture",
                payload={
                    "image_id": "img_empty",
                    "capture_ts": 1.0,
                    "image_path": "local://empty.jpg",
                    "status": "processed",
                },
            )
        )
        event = RealtimeEvent(
            session_id=self.session_id,
            event_type="image.capture",
            payload={"image_id": "img_empty"},
        )
        self.assertFalse(self.service.should_extract_realtime(self.context, event))

        self.context_manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="image.capture",
                payload={
                    "image_id": "img_formula",
                    "capture_ts": 2.0,
                    "image_path": "local://formula.jpg",
                    "status": "processed",
                    "ocr_text": "X(f)=∫x(t)e^{-j2πft}dt",
                },
            )
        )
        event = RealtimeEvent(
            session_id=self.session_id,
            event_type="image.capture",
            payload={"image_id": "img_formula"},
        )
        self.assertTrue(self.service.should_extract_realtime(self.context, event))


if __name__ == "__main__":
    unittest.main()
