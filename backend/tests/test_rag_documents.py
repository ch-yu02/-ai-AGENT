import unittest

from backend.app.models import (
    ClassroomContext,
    ImageCapture,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeTree,
    SourceRef,
    TranscriptSegment,
)
from backend.app.rag import build_session_documents


class RagDocumentsTest(unittest.TestCase):
    def test_builds_documents_from_classroom_context_and_graph(self) -> None:
        session_id = "lec_rag_docs"
        context = ClassroomContext(
            session_id=session_id,
            transcript=[
                TranscriptSegment(
                    segment_id="seg_001",
                    session_id=session_id,
                    start_ts=1.0,
                    end_ts=3.5,
                    text="傅里叶变换可以把时域信号转换到频域。",
                )
            ],
            visuals=[
                ImageCapture(
                    image_id="img_001",
                    session_id=session_id,
                    capture_ts=8.0,
                    image_path="local://slide.jpg",
                    ocr_text="X(f)=∫x(t)e^{-j2πft}dt",
                    caption="课件展示傅里叶变换公式。",
                )
            ],
        )
        node_a = KnowledgeNode(
            node_id="node_fourier",
            label="傅里叶变换",
            summary="将信号从时域转换到频域。",
            source_refs=[SourceRef(type="segment", id="seg_001", ts=1.0)],
        )
        node_b = KnowledgeNode(node_id="node_freq", label="频域")
        edge = KnowledgeEdge(
            edge_id="edge_fourier_freq",
            source=node_a.node_id,
            target=node_b.node_id,
            relation="maps_to",
            source_refs=[SourceRef(type="segment", id="seg_001", ts=1.0)],
        )
        graph = KnowledgeTree(
            session_id=session_id,
            nodes=[node_a, node_b],
            edges=[edge],
        )

        documents = build_session_documents(context, graph)

        self.assertEqual(
            [document.metadata["type"] for document in documents],
            [
                "segment",
                "visual",
                "knowledge_node",
                "knowledge_node",
                "knowledge_edge",
            ],
        )
        self.assertIn("时域信号转换到频域", documents[0].text)
        self.assertIn("OCR:", documents[1].text)
        self.assertEqual(documents[2].metadata["source_id"], "node_fourier")
        self.assertEqual(documents[4].metadata["relation"], "maps_to")

    def test_builds_document_from_structured_notes_markdown(self) -> None:
        session_id = "lec_rag_notes"
        context = ClassroomContext(
            session_id=session_id,
            transcript=[
                TranscriptSegment(
                    segment_id="seg_001",
                    session_id=session_id,
                    start_ts=2.0,
                    end_ts=3.0,
                    text="课堂讲傅里叶变换。",
                )
            ],
        )

        documents = build_session_documents(
            context,
            KnowledgeTree(session_id=session_id),
            structured_notes_markdown="# 结构化笔记\n\n- 傅里叶变换是本节课重点。",
        )

        self.assertEqual(documents[1].metadata["type"], "structured_note")
        self.assertEqual(documents[1].metadata["source_id"], "structured_notes")
        self.assertIn("傅里叶变换是本节课重点", documents[1].text)


if __name__ == "__main__":
    unittest.main()
