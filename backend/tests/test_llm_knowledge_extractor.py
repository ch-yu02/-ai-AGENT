import unittest

from backend.app.extraction import LLMKnowledgeExtractor
from backend.app.llm import CloudLLMError
from backend.app.models import ClassroomContext, ImageCapture, TranscriptSegment


class FakeJsonLLMClient:
    """Fake model client used to keep extraction tests offline and deterministic."""

    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls: list[dict[str, object]] = []

    def complete_json(self, system_prompt, user_prompt, *, temperature=0.1):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": temperature,
            }
        )
        if self.error is not None:
            raise self.error
        return self.payload


class LLMKnowledgeExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_id = "lec_llm_extract_001"

    def test_extract_validates_model_payload_and_overrides_source_fields(self) -> None:
        client = FakeJsonLLMClient(
            payload={
                "extraction_id": "model_ext",
                "session_id": "wrong_session",
                "source_segment_ids": ["seg_001", "invented_seg"],
                "source_visual_ids": ["invented_img"],
                "entities": [
                    {
                        "entity_id": "node_fourier_transform",
                        "name": "傅里叶变换",
                        "type": "concept",
                        "description": "将信号转换到频域分析",
                    },
                    {"name": "频域", "type": "concept"},
                ],
                "relations": [
                    {
                        "source": "傅里叶变换",
                        "target": "频域",
                        "relation": "maps_to",
                    }
                ],
                "importance": 0.9,
            }
        )
        extractor = LLMKnowledgeExtractor(client)

        result = extractor.extract(self._context())

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.extractions), 1)
        extraction = result.extractions[0]
        self.assertEqual(extraction.session_id, self.session_id)
        self.assertEqual(extraction.source_segment_ids, ["seg_001"])
        self.assertEqual(extraction.source_visual_ids, ["img_001"])
        self.assertEqual(extraction.timestamp_range, (1.0, 5.0))
        self.assertEqual(extraction.entities[0].name, "傅里叶变换")
        self.assertEqual(extraction.relations[0].relation, "maps_to")
        self.assertIn("seg_001", client.calls[0]["user_prompt"])
        self.assertIn("img_001", client.calls[0]["user_prompt"])

    def test_model_failure_returns_error_without_fallback_extraction(self) -> None:
        extractor = LLMKnowledgeExtractor(
            FakeJsonLLMClient(error=CloudLLMError("timeout"))
        )

        result = extractor.extract(self._context())

        self.assertEqual(result.extractions, [])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].provider, "llm")
        self.assertEqual(result.errors[0].error_type, "CloudLLMError")
        self.assertFalse(result.errors[0].generated_graph)

    def test_invalid_schema_returns_error_without_graph_payload(self) -> None:
        extractor = LLMKnowledgeExtractor(
            FakeJsonLLMClient(payload={"entities": [{"description": "missing name"}]})
        )

        result = extractor.extract(self._context())

        self.assertEqual(result.extractions, [])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("validation", result.errors[0].message.lower())

    def _context(self) -> ClassroomContext:
        return ClassroomContext(
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


if __name__ == "__main__":
    unittest.main()
