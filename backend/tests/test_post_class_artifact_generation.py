import tempfile
import unittest
from pathlib import Path

from backend.app.api import sessions as sessions_api
from backend.app.models import (
    ClassroomContext,
    KnowledgeNode,
    KnowledgeTree,
    LectureSession,
    TranscriptSegment,
)
from backend.app.storage import LocalStorage


class PostClassArtifactGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(Path(self.temp_dir.name) / "sessions")
        self.original_storage = sessions_api.local_storage
        sessions_api.local_storage = self.storage
        self.session_id = "lec_post_class_001"

    def tearDown(self) -> None:
        sessions_api.local_storage = self.original_storage
        self.temp_dir.cleanup()

    def test_end_route_helper_generates_only_auto_post_class_artifact_files(self) -> None:
        """结束课堂只自动保存总结和待办，自测题留给用户主动生成。

        这个测试直接覆盖 sessions API 的 helper，是为了防止以后有人把
        QuizMasterSkill 又放回结束课堂链路，导致每节课结束时都提前写出
        quiz.json。
        """
        context = ClassroomContext(
            session_id=self.session_id,
            transcript=[
                TranscriptSegment(
                    segment_id="seg_001",
                    session_id=self.session_id,
                    start_ts=1.0,
                    end_ts=3.0,
                    text="作业是完成第三题。傅里叶变换可以转换到频域。",
                )
            ],
        )
        graph = KnowledgeTree(
            session_id=self.session_id,
            nodes=[KnowledgeNode(node_id="node_fourier", label="傅里叶变换")],
        )
        self.storage.save_session(
            session=LectureSession(
                session_id=self.session_id,
                title="课后产物测试",
                course="通信原理",
                teacher=None,
                start_time="2026-06-04T09:00:00+08:00",
                end_time="2026-06-04T10:30:00+08:00",
                status="ended",
                language="zh-CN",
                created_by="student",
                device_id=None,
            ),
            context=context,
            knowledge_graph=graph,
        )

        files = sessions_api._generate_and_save_post_class_artifacts(
            self.session_id,
            context,
            graph,
        )

        self.assertIn("summary", files)
        self.assertIn("todos", files)
        self.assertNotIn("quiz", files)
        self.assertIn("agent_artifacts", files)
        self.assertTrue((self.storage.session_dir(self.session_id) / "summary.md").exists())
        self.assertTrue((self.storage.session_dir(self.session_id) / "todos.json").exists())
        self.assertFalse((self.storage.session_dir(self.session_id) / "quiz.json").exists())


if __name__ == "__main__":
    unittest.main()
