import tempfile
import unittest
from pathlib import Path

from backend.app.agent import AgentChatRequest, AgentSessionNotFoundError, ClassroomAgent
from backend.app.core import ContextManager, KnowledgeGraphManager
from backend.app.models import (
    ClassroomContext,
    KnowledgeNode,
    KnowledgeTree,
    LectureSession,
    RealtimeEvent,
)
from backend.app.storage import LocalStorage


class ClassroomAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(Path(self.temp_dir.name) / "sessions")
        self.context_manager = ContextManager()
        self.graph_manager = KnowledgeGraphManager()
        self.agent = ClassroomAgent(
            context_manager=self.context_manager,
            knowledge_graph_manager=self.graph_manager,
            storage=self.storage,
        )
        self.session_id = "lec_agent_001"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_answers_qa_from_in_memory_transcript(self) -> None:
        self._start_memory_session()
        self.context_manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="transcript.segment",
                payload={
                    "segment_id": "seg_fourier",
                    "start_ts": 1.0,
                    "end_ts": 3.5,
                    "text": "傅里叶变换可以把时域信号转换到频域。",
                },
            )
        )

        response = self.agent.chat(
            AgentChatRequest(session_id=self.session_id, prompt="傅里叶变换讲了什么？")
        )

        self.assertEqual(response.intent, "qa")
        self.assertIn("时域信号转换到频域", response.answer)
        self.assertEqual(response.source_refs[0].id, "seg_fourier")
        self.assertIn("课堂仍在录制中", response.warnings[-1])

    def test_generates_summary_from_history_when_memory_is_missing(self) -> None:
        self.storage.save_session(
            session=self._ended_session(),
            context=ClassroomContext(session_id=self.session_id),
            knowledge_graph=KnowledgeTree(
                session_id=self.session_id,
                nodes=[
                    KnowledgeNode(
                        node_id="node_fourier",
                        label="傅里叶变换",
                        summary="将信号从时域转换到频域。",
                    )
                ],
            ),
        )

        response = self.agent.chat(
            AgentChatRequest(session_id=self.session_id, prompt="总结这节课")
        )

        self.assertEqual(response.intent, "summary")
        self.assertIn("傅里叶变换", response.answer)
        self.assertEqual(response.warnings, [])
        summary_path = self.storage.session_dir(self.session_id) / "summary.md"
        self.assertTrue(summary_path.exists())
        self.assertIn("傅里叶变换", summary_path.read_text(encoding="utf-8"))
        detail = self.storage.read_session(self.session_id)
        self.assertEqual(detail.post_class_artifacts.agent_messages[0]["role"], "user")
        self.assertEqual(
            detail.post_class_artifacts.agent_messages[1]["role"],
            "assistant",
        )

    def test_extracts_todo_candidates(self) -> None:
        self._start_memory_session()
        self.context_manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="transcript.segment",
                payload={
                    "segment_id": "seg_homework",
                    "start_ts": 5.0,
                    "end_ts": 8.0,
                    "text": "作业是完成课后第三题，并预习采样定理。",
                },
            )
        )

        response = self.agent.chat(
            AgentChatRequest(session_id=self.session_id, prompt="有什么作业")
        )

        self.assertEqual(response.intent, "todos")
        self.assertIn("课后第三题", response.answer)
        self.assertEqual(response.artifacts[0].type, "todos")

    def test_generates_quiz_from_knowledge_graph(self) -> None:
        self._start_memory_session()
        self.graph_manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="knowledge.extraction",
                payload={
                    "extraction_id": "ext_001",
                    "entities": [
                        {
                            "entity_id": "node_sampling",
                            "name": "采样定理",
                            "description": "描述连续信号采样恢复条件。",
                        }
                    ],
                },
            )
        )
        # 先把课堂保存成历史目录，模拟用户结束课程后再点击 AgentPanel 的
        # “生成自测”。只有目录已存在时，Agent 才会把本次 quiz artifact 写成本地
        # quiz.json；正在录制且未落盘的课堂仍只返回回答，不提前创建历史目录。
        self.storage.save_session(
            session=self._ended_session(),
            context=self.context_manager.get_context(self.session_id),
            knowledge_graph=self.graph_manager.get_graph(self.session_id),
        )

        response = self.agent.chat(
            AgentChatRequest(session_id=self.session_id, prompt="出几道题")
        )

        self.assertEqual(response.intent, "quiz")
        self.assertIn("采样定理", response.answer)
        self.assertEqual(response.artifacts[0].type, "quiz")
        quiz_path = self.storage.session_dir(self.session_id) / "quiz.json"
        self.assertTrue(quiz_path.exists())
        self.assertIn("采样定理", quiz_path.read_text(encoding="utf-8"))

    def test_missing_session_raises_domain_error(self) -> None:
        with self.assertRaises(AgentSessionNotFoundError):
            self.agent.chat(
                AgentChatRequest(session_id="lec_missing", prompt="总结这节课")
            )

    def _start_memory_session(self) -> None:
        self.context_manager.start_session(self.session_id)
        self.graph_manager.start_session(self.session_id)

    def _ended_session(self) -> LectureSession:
        return LectureSession(
            session_id=self.session_id,
            title="Agent 测试课堂",
            course="通信原理",
            teacher="王老师",
            start_time="2026-06-04T09:00:00+08:00",
            end_time="2026-06-04T10:30:00+08:00",
            status="ended",
            language="zh-CN",
            created_by="student",
            device_id=None,
        )


if __name__ == "__main__":
    unittest.main()
