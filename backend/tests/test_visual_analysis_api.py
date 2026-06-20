import tempfile
import unittest
from pathlib import Path

from backend.app.agent.schemas import VisualAnalysisRequest
from backend.app.agent.visual_analysis import ClassroomVisualAnalysisAgent
from backend.app.api import agent as agent_api
from backend.app.core import (
    context_manager,
    knowledge_graph_manager,
    session_manager,
    websocket_manager,
)
from backend.app.models import RealtimeEvent, StartSessionRequest
from backend.app.storage.local_storage import LocalStorage


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent_payloads: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        self.sent_payloads.append(data)


class FakeMultimodalClient:
    def complete_json_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        image_bytes: bytes,
        media_type: str,
        temperature: float = 0.1,
    ) -> dict[str, object]:
        self.image_bytes = image_bytes
        self.media_type = media_type
        return {
            "caption": "照片中有一页关于 TCP/IP 分层模型的投影。",
            "visual_text": ["应用层", "传输层", "网络层"],
            "key_points": [
                "TCP/IP 模型把网络通信划分为多个协作层次。",
            ],
            "entities": [
                {"name": "TCP/IP 模型", "type": "concept"},
                {"name": "应用层", "type": "concept"},
                {"name": "传输层", "type": "concept"},
            ],
            "relations": [
                {
                    "source": "TCP/IP 模型",
                    "target": "应用层",
                    "relation": "contains",
                }
            ],
            "importance": 0.85,
        }


class VisualAnalysisApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        session_manager.clear()
        context_manager.clear()
        knowledge_graph_manager.clear()
        websocket_manager.clear()

        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(Path(self.tempdir.name) / "sessions")
        self.fake_client = FakeMultimodalClient()
        self.original_storage = agent_api.local_storage
        self.original_agent = agent_api.visual_analysis_agent
        self.original_to_thread = agent_api.asyncio.to_thread
        agent_api.local_storage = self.storage
        agent_api.visual_analysis_agent = ClassroomVisualAnalysisAgent(self.fake_client)
        agent_api.asyncio.to_thread = _direct_to_thread

        session = session_manager.create_session(
            StartSessionRequest(title="视觉分析 API 测试")
        )
        self.session_id = session.session_id
        self.image_id = "img_visual_api_001"
        context_manager.start_session(self.session_id)
        knowledge_graph_manager.start_session(self.session_id)

        image_path = self.storage.save_session_image(
            self.session_id,
            self.image_id,
            b"\xff\xd8fake-jpeg\xff\xd9",
            "image/jpeg",
        )
        self.image_uri = (
            f"local://sessions/{self.session_id}/images/{image_path.name}"
        )
        context_manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="image.capture",
                payload={
                    "image_id": self.image_id,
                    "session_id": self.session_id,
                    "capture_ts": 12.5,
                    "image_path": self.image_uri,
                    "source": "browser_camera",
                    "image_type": "camera_snapshot",
                    "status": "processing",
                },
            )
        )
        self.socket = FakeWebSocket()

    async def asyncSetUp(self) -> None:
        await websocket_manager.connect(self.session_id, self.socket)

    def tearDown(self) -> None:
        agent_api.local_storage = self.original_storage
        agent_api.visual_analysis_agent = self.original_agent
        agent_api.asyncio.to_thread = self.original_to_thread
        session_manager.clear()
        context_manager.clear()
        knowledge_graph_manager.clear()
        websocket_manager.clear()
        self.tempdir.cleanup()

    async def test_visual_analyze_updates_visual_graph_and_broadcasts(self) -> None:
        response = await agent_api.analyze_visual(
            VisualAnalysisRequest(
                session_id=self.session_id,
                image_id=self.image_id,
            )
        )

        self.assertEqual(response.status, "applied")
        self.assertEqual(response.visual_text, ["应用层", "传输层", "网络层"])
        self.assertGreater(response.graph_patch_operations, 0)
        self.assertEqual(self.fake_client.media_type, "image/jpeg")

        context = context_manager.get_context(self.session_id)
        self.assertEqual(len(context.visuals), 1)
        self.assertEqual(context.visuals[0].status, "processed")
        self.assertIn("TCP/IP", context.visuals[0].caption or "")
        self.assertEqual(len(context.knowledge_extractions), 1)
        self.assertEqual(
            context.knowledge_extractions[0].source_visual_ids,
            [self.image_id],
        )

        graph = knowledge_graph_manager.get_graph(self.session_id)
        self.assertIn("TCP/IP 模型", {node.label for node in graph.nodes})
        self.assertTrue(
            any(ref.type == "visual" for node in graph.nodes for ref in node.source_refs)
        )

        event_messages = [
            payload
            for payload in self.socket.sent_payloads
            if payload["type"] == "event.received"
        ]
        self.assertEqual(
            [message["data"]["event_type"] for message in event_messages],
            ["image.capture", "knowledge.extraction"],
        )
        self.assertIsNone(event_messages[0]["data"]["graph_patch"])
        self.assertIsNotNone(event_messages[1]["data"]["graph_patch"])


async def _direct_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
    return func(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
