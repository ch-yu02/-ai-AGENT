import unittest

from backend.app.api import events as events_api
from backend.app.core import (
    context_manager,
    knowledge_graph_manager,
    session_manager,
    websocket_manager,
)
from backend.app.models import RealtimeEvent, StartSessionRequest


class FakeWebSocket:
    """Small WebSocket stand-in that captures broadcast payloads.

    The realtime extraction behavior is mostly about WebSocket ordering and
    payload shape, so this fake keeps the test at manager/API level without
    needing a FastAPI TestClient.
    """

    def __init__(self) -> None:
        self.accepted = False
        self.sent_payloads: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        self.sent_payloads.append(data)


class RealtimeKnowledgeExtractionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        session_manager.clear()
        context_manager.clear()
        knowledge_graph_manager.clear()
        websocket_manager.clear()

        session = session_manager.create_session(
            StartSessionRequest(title="实时抽取测试")
        )
        self.session_id = session.session_id
        context_manager.start_session(self.session_id)
        knowledge_graph_manager.start_session(self.session_id)
        self.socket = FakeWebSocket()

    async def asyncSetUp(self) -> None:
        await websocket_manager.connect(self.session_id, self.socket)

    def tearDown(self) -> None:
        session_manager.clear()
        context_manager.clear()
        knowledge_graph_manager.clear()
        websocket_manager.clear()

    async def test_third_transcript_segment_broadcasts_internal_extraction(self) -> None:
        """The third final segment should trigger a separate graph update."""
        texts = [
            "采样定理是通信系统的重要概念。",
            "卷积方法可以分析线性系统。",
            "傅里叶变换可以把时域信号转换到频域。",
        ]
        for index, text in enumerate(texts, start=1):
            await events_api.receive_event(
                RealtimeEvent(
                    session_id=self.session_id,
                    event_type="transcript.segment",
                    payload={
                        "segment_id": f"seg_{index:03d}",
                        "start_ts": float(index),
                        "end_ts": float(index + 1),
                        "text": text,
                    },
                )
            )

        event_types = [
            payload["data"]["event_type"]
            for payload in self.socket.sent_payloads
            if payload["type"] == "event.received"
        ]
        # The triggering transcript remains visible first; the internally
        # generated knowledge event follows as its own event.received message.
        self.assertEqual(
            event_types,
            [
                "transcript.segment",
                "transcript.segment",
                "transcript.segment",
                "knowledge.extraction",
            ],
        )

        third_payload = self.socket.sent_payloads[2]["data"]
        # The triggering transcript carries only the extraction summary.
        self.assertIn("knowledge_extraction", third_payload)
        self.assertEqual(third_payload["knowledge_extraction"]["extraction_count"], 1)

        extraction_payload = self.socket.sent_payloads[3]["data"]
        # The following internal event carries the actual graph patch.
        self.assertIsNotNone(extraction_payload["graph_patch"])
        self.assertEqual(
            extraction_payload["context_update"]["knowledge_extraction_count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
