import unittest

from backend.app.core import ContextManager, KnowledgeGraphManager
from backend.app.extraction import (
    LLMKnowledgeExtractor,
    KnowledgeExtractionService,
)
from backend.app.extraction.service import build_default_extractor
from backend.app.models import RealtimeEvent


class FakeJsonLLMClient:
    """Offline fake that returns a stable extraction-shaped JSON payload."""

    def complete_json(self, system_prompt, user_prompt, *, temperature=0.1):  # type: ignore[no-untyped-def]
        return {
            "entities": [
                {
                    "entity_id": "node_fourier_transform",
                    "name": "傅里叶变换",
                    "type": "concept",
                    "description": "将信号转换到频域分析",
                },
                {"entity_id": "node_frequency_domain", "name": "频域", "type": "concept"},
            ],
            "relations": [
                {
                    "source": "傅里叶变换",
                    "target": "频域",
                    "relation": "maps_to",
                }
            ],
            "importance": 0.9,
        }


class KnowledgeExtractionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_id = "lec_service_extract_001"
        self.context_manager = ContextManager()
        self.graph_manager = KnowledgeGraphManager()
        self.context = self.context_manager.start_session(self.session_id)
        self.graph_manager.start_session(self.session_id)
        self.service = KnowledgeExtractionService(
            LLMKnowledgeExtractor(FakeJsonLLMClient())
        )

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

    def test_default_extractor_uses_llm_backend(self) -> None:
        self.assertIsInstance(build_default_extractor(), LLMKnowledgeExtractor)


if __name__ == "__main__":
    unittest.main()
