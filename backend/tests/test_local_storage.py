import json
import tempfile
import unittest
from pathlib import Path

from backend.app.models import (
    ClassroomContext,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeTree,
    LectureSession,
    TimelineItem,
    TranscriptSegment,
)
from backend.app.storage import LocalStorage


class LocalStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name) / "sessions"
        self.storage = LocalStorage(self.base_dir)
        self.session_id = "lec_storage_001"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _session(self) -> LectureSession:
        return LectureSession(
            session_id=self.session_id,
            title="通信原理第8讲",
            course="通信原理",
            teacher="王老师",
            start_time="2026-06-04T09:00:00+08:00",
            end_time="2026-06-04T10:30:00+08:00",
            status="ended",
            language="zh-CN",
            created_by="student",
            device_id="dk2500_001",
        )

    def _context(self) -> ClassroomContext:
        segment = TranscriptSegment(
            segment_id="seg_001",
            session_id=self.session_id,
            start_ts=1.0,
            end_ts=3.5,
            text="傅里叶变换可以把时域信号转换到频域。",
            speaker="teacher",
        )
        timeline_item = TimelineItem(
            item_id="seg_001",
            session_id=self.session_id,
            type="transcript",
            ts=1.0,
            title="傅里叶变换",
            data=segment.model_dump(),
        )
        return ClassroomContext(
            session_id=self.session_id,
            transcript=[segment],
            timeline=[timeline_item],
        )

    def _knowledge_graph(self) -> KnowledgeTree:
        node_a = KnowledgeNode(node_id="node_fourier", label="傅里叶变换")
        node_b = KnowledgeNode(node_id="node_freq", label="频域")
        edge = KnowledgeEdge(
            edge_id="edge_fourier_maps_freq",
            source=node_a.node_id,
            target=node_b.node_id,
            relation="maps_to",
        )
        return KnowledgeTree(
            session_id=self.session_id,
            version=1,
            root_nodes=[node_a.node_id],
            nodes=[node_a, node_b],
            edges=[edge],
        )

    def test_save_session_writes_all_mvp_artifacts(self) -> None:
        result = self.storage.save_session(
            session=self._session(),
            context=self._context(),
            knowledge_graph=self._knowledge_graph(),
        )

        self.assertTrue(result.session_dir.exists())
        self.assertEqual(
            set(result.files),
            {"metadata", "transcript", "timeline", "knowledge_graph"},
        )
        for path in result.files.values():
            self.assertTrue(path.exists(), f"missing file: {path}")

    def test_saved_metadata_timeline_and_graph_are_valid_json(self) -> None:
        result = self.storage.save_session(
            session=self._session(),
            context=self._context(),
            knowledge_graph=self._knowledge_graph(),
        )

        metadata = json.loads(result.files["metadata"].read_text(encoding="utf-8"))
        timeline = json.loads(result.files["timeline"].read_text(encoding="utf-8"))
        graph = json.loads(result.files["knowledge_graph"].read_text(encoding="utf-8"))

        self.assertEqual(metadata["session_id"], self.session_id)
        self.assertEqual(metadata["status"], "ended")
        self.assertEqual(timeline[0]["item_id"], "seg_001")
        self.assertEqual(graph["nodes"][0]["label"], "傅里叶变换")
        self.assertEqual(graph["edges"][0]["relation"], "maps_to")

    def test_transcript_markdown_is_human_readable(self) -> None:
        result = self.storage.save_session(
            session=self._session(),
            context=self._context(),
            knowledge_graph=self._knowledge_graph(),
        )

        transcript = result.files["transcript"].read_text(encoding="utf-8")
        self.assertIn("# Transcript - lec_storage_001", transcript)
        self.assertIn("[1.00s - 3.50s]", transcript)
        self.assertIn("傅里叶变换可以把时域信号转换到频域。", transcript)

    def test_read_metadata_supports_future_history_lookup(self) -> None:
        self.storage.save_session(
            session=self._session(),
            context=self._context(),
            knowledge_graph=self._knowledge_graph(),
        )

        metadata = self.storage.read_metadata(self.session_id)

        self.assertTrue(self.storage.session_exists(self.session_id))
        self.assertEqual(metadata["title"], "通信原理第8讲")


if __name__ == "__main__":
    unittest.main()
