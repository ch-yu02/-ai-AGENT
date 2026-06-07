import tempfile
import unittest
from pathlib import Path

from backend.app.agent import GlobalSearchRequest, GlobalSearchService
from backend.app.models import (
    ClassroomContext,
    KnowledgeNode,
    KnowledgeTree,
    LectureSession,
    TimelineItem,
    TranscriptSegment,
)
from backend.app.storage import LocalStorage


class GlobalSearchServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(Path(self.temp_dir.name) / "sessions")
        self.service = GlobalSearchService(self.storage)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_search_returns_hits_across_saved_sessions(self) -> None:
        self._save_session(
            session_id="lec_global_001",
            title="通信原理第8讲",
            course="通信原理",
            text="傅里叶变换可以把时域信号转换到频域。",
            node_label="傅里叶变换",
        )
        self._save_session(
            session_id="lec_global_002",
            title="信号处理第3讲",
            course="信号处理",
            text="采样定理描述连续信号采样恢复条件。",
            node_label="采样定理",
        )

        response = self.service.search(GlobalSearchRequest(query="哪节课讲过采样定理"))

        self.assertIn("历史课堂", response.answer)
        self.assertEqual(response.hits[0].session_id, "lec_global_002")
        self.assertIn("采样定理", response.hits[0].source_ref.text)

    def test_search_filters_by_course(self) -> None:
        self._save_session(
            session_id="lec_global_comm",
            title="通信原理第8讲",
            course="通信原理",
            text="采样定理在通信系统中很重要。",
            node_label="采样定理",
        )
        self._save_session(
            session_id="lec_global_math",
            title="数学第2讲",
            course="高等数学",
            text="采样定理这里只作为例子。",
            node_label="采样定理",
        )

        response = self.service.search(
            GlobalSearchRequest(query="采样定理", course="高等数学")
        )

        self.assertTrue(response.hits)
        self.assertTrue(all(hit.course == "高等数学" for hit in response.hits))

    def test_search_returns_warning_when_no_history_exists(self) -> None:
        response = self.service.search(GlobalSearchRequest(query="采样定理"))

        self.assertEqual(response.hits, [])
        self.assertTrue(response.warnings)

    def test_search_skips_broken_history_directory(self) -> None:
        broken_dir = self.storage.session_dir("lec_broken")
        broken_dir.mkdir(parents=True)
        (broken_dir / "metadata.json").write_text("{}", encoding="utf-8")
        self._save_session(
            session_id="lec_global_ok",
            title="通信原理第8讲",
            course="通信原理",
            text="傅里叶变换可以转换到频域。",
            node_label="傅里叶变换",
        )

        response = self.service.search(GlobalSearchRequest(query="傅里叶变换"))

        self.assertTrue(response.hits)
        self.assertEqual(response.hits[0].session_id, "lec_global_ok")

    def _save_session(
        self,
        *,
        session_id: str,
        title: str,
        course: str,
        text: str,
        node_label: str,
    ) -> None:
        segment = TranscriptSegment(
            segment_id=f"{session_id}_seg_001",
            session_id=session_id,
            start_ts=1.0,
            end_ts=3.0,
            text=text,
        )
        context = ClassroomContext(
            session_id=session_id,
            transcript=[segment],
            timeline=[
                TimelineItem(
                    item_id=segment.segment_id,
                    session_id=session_id,
                    type="transcript",
                    ts=1.0,
                    title=node_label,
                    data=segment.model_dump(),
                )
            ],
        )
        graph = KnowledgeTree(
            session_id=session_id,
            nodes=[
                KnowledgeNode(
                    node_id=f"{session_id}_node_001",
                    label=node_label,
                    summary=text,
                )
            ],
        )
        self.storage.save_session(
            session=LectureSession(
                session_id=session_id,
                title=title,
                course=course,
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


if __name__ == "__main__":
    unittest.main()
