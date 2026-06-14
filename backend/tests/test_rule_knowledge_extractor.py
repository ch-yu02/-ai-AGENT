import unittest

from backend.app.extraction import RuleKnowledgeExtractor
from backend.app.models import ClassroomContext, ImageCapture, TranscriptSegment


class RuleKnowledgeExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_id = "lec_extract_001"
        self.extractor = RuleKnowledgeExtractor()

    def test_extracts_entities_relations_and_source_refs(self) -> None:
        context = ClassroomContext(
            session_id=self.session_id,
            transcript=[
                TranscriptSegment(
                    segment_id="seg_001",
                    session_id=self.session_id,
                    start_ts=1.0,
                    end_ts=4.0,
                    text="傅里叶变换可以把时域信号转换到频域。",
                )
            ],
            visuals=[
                ImageCapture(
                    image_id="img_001",
                    session_id=self.session_id,
                    capture_ts=5.0,
                    image_path="local://slide.jpg",
                    ocr_text="X(f)=∫x(t)e^{-j2πft}dt",
                    caption="课件展示傅里叶变换公式。",
                )
            ],
        )

        result = self.extractor.extract(context)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.processed_source_ids, ["seg_001", "img_001"])
        self.assertEqual(len(result.extractions), 1)

        extraction = result.extractions[0]
        entity_names = {entity.name for entity in extraction.entities}
        relation_types = {relation.relation for relation in extraction.relations}

        self.assertIn("傅里叶变换", entity_names)
        self.assertIn("频域", entity_names)
        self.assertIn("X(f)=∫x(t)e^{-j2πft}dt", entity_names)
        self.assertIn("maps_to", relation_types)
        self.assertEqual(extraction.source_segment_ids, ["seg_001"])
        self.assertEqual(extraction.source_visual_ids, ["img_001"])
        self.assertEqual(extraction.timestamp_range, (1.0, 5.0))

    def test_skips_sources_already_used_by_existing_extractions(self) -> None:
        context = ClassroomContext(
            session_id=self.session_id,
            transcript=[
                TranscriptSegment(
                    segment_id="seg_001",
                    session_id=self.session_id,
                    start_ts=1.0,
                    end_ts=2.0,
                    text="采样定理是通信系统的重要概念。",
                )
            ],
        )
        first = self.extractor.extract(context)
        context.knowledge_extractions.extend(first.extractions)

        second = self.extractor.extract(context)

        self.assertEqual(second.errors, [])
        self.assertEqual(second.extractions, [])
        self.assertEqual(second.processed_source_ids, [])


if __name__ == "__main__":
    unittest.main()
