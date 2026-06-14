import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
from backend.app.rag import GlobalIndexHit


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

    def test_search_filters_by_date_range(self) -> None:
        self._save_session(
            session_id="lec_global_old",
            title="旧课",
            course="通信原理",
            text="采样定理旧课内容。",
            node_label="采样定理",
            start_time="2026-06-01T09:00:00+08:00",
        )
        self._save_session(
            session_id="lec_global_new",
            title="新课",
            course="通信原理",
            text="采样定理新课内容。",
            node_label="采样定理",
            start_time="2026-06-05T09:00:00+08:00",
        )

        response = self.service.search(
            GlobalSearchRequest(
                query="采样定理",
                date_from="2026-06-05",
                date_to="2026-06-05",
            )
        )

        self.assertTrue(response.hits)
        self.assertTrue(all(hit.session_id == "lec_global_new" for hit in response.hits))

    def test_search_writes_global_index_snapshot(self) -> None:
        self._save_session(
            session_id="lec_global_index",
            title="通信原理第8讲",
            course="通信原理",
            text="傅里叶变换可以转换到频域。",
            node_label="傅里叶变换",
        )

        self.service.search(GlobalSearchRequest(query="傅里叶变换"))

        index_path = (
            self.storage.global_index_dir() / "documents.json"
        )
        self.assertTrue(index_path.exists())

    def test_rebuild_global_index_writes_snapshot(self) -> None:
        self._save_session(
            session_id="lec_rebuild_index",
            title="通信原理第11讲",
            course="通信原理",
            text="信道容量描述信道传输信息的上限。",
            node_label="信道容量",
        )

        result = self.service.rebuild_global_index()

        self.assertEqual(result["document_count"], 2)
        self.assertTrue(Path(str(result["documents_path"])).exists())
        self.assertEqual(result["llamaindex"]["status"], "skipped")

    def test_search_uses_optional_global_llama_index_backend(self) -> None:
        self._save_session(
            session_id="lec_vector_index",
            title="通信原理第9讲",
            course="通信原理",
            text="信道编码用于提高通信可靠性。",
            node_label="信道编码",
        )
        fake_service = _FakeGlobalIndexService(
            hits=[
                GlobalIndexHit(
                    score=900,
                    session_id="lec_vector_index",
                    title="通信原理第9讲",
                    course="通信原理",
                    source_type="segment",
                    source_id="lec_vector_index_seg_001",
                    ts=1.0,
                    text="[1.00s-3.00s] 信道编码用于提高通信可靠性。",
                )
            ]
        )
        service = GlobalSearchService(
            storage=self.storage,
            global_index_service=fake_service,
        )

        with patch.dict("os.environ", {"GLOBAL_SEARCH_BACKEND": "llamaindex"}):
            response = service.search(GlobalSearchRequest(query="可靠性"))

        self.assertIn("全局向量索引", response.answer)
        self.assertEqual(response.hits[0].score, 900)
        self.assertTrue(fake_service.was_called)

    def test_search_falls_back_when_global_llama_index_fails(self) -> None:
        self._save_session(
            session_id="lec_vector_fallback",
            title="通信原理第10讲",
            course="通信原理",
            text="卷积码也是一种信道编码。",
            node_label="卷积码",
        )
        service = GlobalSearchService(
            storage=self.storage,
            global_index_service=_FailingGlobalIndexService(),
        )

        with patch.dict("os.environ", {"GLOBAL_SEARCH_BACKEND": "llamaindex"}):
            response = service.search(GlobalSearchRequest(query="卷积码"))

        self.assertTrue(response.hits)
        self.assertEqual(response.hits[0].session_id, "lec_vector_fallback")
        self.assertTrue(any("已回退词法搜索" in warning for warning in response.warnings))

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
        start_time: str = "2026-06-04T09:00:00+08:00",
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
                start_time=start_time,
                end_time="2026-06-04T10:30:00+08:00",
                status="ended",
                language="zh-CN",
                created_by="student",
                device_id=None,
            ),
            context=context,
            knowledge_graph=graph,
        )


class _FakeGlobalIndexService:
    def __init__(self, hits: list[GlobalIndexHit]) -> None:
        self.hits = hits
        self.was_called = False

    def search(self, **_: object) -> list[GlobalIndexHit]:
        self.was_called = True
        return self.hits


class _FailingGlobalIndexService:
    def search(self, **_: object) -> list[GlobalIndexHit]:
        raise RuntimeError("fake global index failure")


if __name__ == "__main__":
    unittest.main()
