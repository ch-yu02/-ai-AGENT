import tempfile
import unittest
from pathlib import Path

from backend.app.core import ContextManager, KnowledgeGraphManager, SessionManager
from backend.app.models import RealtimeEvent, StartSessionRequest
from backend.app.storage import LocalStorage


class StorageIntegrationTest(unittest.TestCase):
    """服务层完整链路测试：开始课堂 -> 接收事件 -> 结束课堂 -> 保存文件。

    这里不使用 FastAPI TestClient。当前 Starlette 测试客户端在本环境中
    依赖组合不稳定，容易阻塞；而本测试直接覆盖后端主链路中的核心模块，
    更适合作为 Storage 的可靠回归测试。
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(Path(self.temp_dir.name) / "sessions")
        self.sessions = SessionManager()
        self.contexts = ContextManager()
        self.graphs = KnowledgeGraphManager()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_full_service_pipeline_writes_session_files(self) -> None:
        session = self.sessions.create_session(
            StartSessionRequest(title="通信原理第8讲", course="通信原理")
        )
        self.contexts.start_session(session.session_id)
        self.graphs.start_session(session.session_id)

        transcript_event = RealtimeEvent(
            session_id=session.session_id,
            event_type="transcript.segment",
            payload={
                "segment_id": "seg_001",
                "start_ts": 1.0,
                "end_ts": 3.5,
                "text": "傅里叶变换可以把时域信号转换到频域。",
            },
        )
        self.sessions.require_recording(session.session_id)
        self.contexts.handle_event(transcript_event)
        self.graphs.handle_event(transcript_event)

        knowledge_event = RealtimeEvent(
            session_id=session.session_id,
            event_type="knowledge.extraction",
            payload={
                "extraction_id": "ext_001",
                "timestamp_range": [1.0, 3.5],
                "source_segment_ids": ["seg_001"],
                "entities": [
                    {"entity_id": "node_fourier", "name": "傅里叶变换"},
                    {"entity_id": "node_freq", "name": "频域"},
                ],
                "relations": [
                    {
                        "source": "傅里叶变换",
                        "target": "频域",
                        "relation": "maps_to",
                    }
                ],
            },
        )
        self.sessions.require_recording(session.session_id)
        self.contexts.handle_event(knowledge_event)
        self.graphs.handle_event(knowledge_event)

        ended_session = self.sessions.end_session(session.session_id)
        result = self.storage.save_session(
            session=ended_session,
            context=self.contexts.get_context(session.session_id),
            knowledge_graph=self.graphs.get_graph(session.session_id),
        )

        session_dir = result.session_dir
        self.assertTrue((session_dir / "metadata.json").exists())
        self.assertTrue((session_dir / "transcript.md").exists())
        self.assertTrue((session_dir / "timeline.json").exists())
        self.assertTrue((session_dir / "knowledge_graph.json").exists())

        transcript = (session_dir / "transcript.md").read_text(encoding="utf-8")
        graph = (session_dir / "knowledge_graph.json").read_text(encoding="utf-8")
        self.assertIn("傅里叶变换可以把时域信号转换到频域。", transcript)
        self.assertIn("maps_to", graph)


if __name__ == "__main__":
    unittest.main()
