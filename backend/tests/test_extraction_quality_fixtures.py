import json
import unittest
from pathlib import Path

from backend.app.extraction import LLMKnowledgeExtractor
from backend.app.models import ClassroomContext, ImageCapture, TranscriptSegment


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "extraction_quality_cases.json"


class FixtureEchoLLMClient:
    """Fake model that returns each fixture's expected graph shape.

    The goal is not to grade a real LLM in unit tests. Instead, this verifies
    that fixture inputs can flow through ``LLMKnowledgeExtractor`` and produce a
    valid ``KnowledgeExtraction``. Real provider evaluation can reuse the same
    fixture file in a manual or CI job with network access.
    """

    def __init__(self, case: dict) -> None:
        self.case = case

    def complete_json(self, system_prompt, user_prompt, *, temperature=0.1):  # type: ignore[no-untyped-def]
        entities = [
            {"name": name, "type": "concept"}
            for name in self.case["expected_entities"]
        ]
        relation = self.case["expected_relations"][0]
        return {
            "entities": entities,
            "relations": [
                {
                    "source": entities[0]["name"],
                    "target": entities[-1]["name"],
                    "relation": relation,
                }
            ],
        }


class ExtractionQualityFixtureTest(unittest.TestCase):
    def test_fixture_cases_are_valid_extraction_inputs(self) -> None:
        cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        for case in cases:
            with self.subTest(case=case["name"]):
                context = self._context_from_case(case)
                extractor = LLMKnowledgeExtractor(FixtureEchoLLMClient(case))
                result = extractor.extract(context)

                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.extractions), 1)
                names = {entity.name for entity in result.extractions[0].entities}
                relations = {
                    relation.relation for relation in result.extractions[0].relations
                }
                self.assertTrue(set(case["expected_entities"]).issubset(names))
                self.assertTrue(set(case["expected_relations"]).issubset(relations))

    def _context_from_case(self, case: dict) -> ClassroomContext:
        session_id = case["session_id"]
        return ClassroomContext(
            session_id=session_id,
            transcript=[
                TranscriptSegment(
                    session_id=session_id,
                    segment_id=item["segment_id"],
                    start_ts=item["start_ts"],
                    end_ts=item["end_ts"],
                    text=item["text"],
                )
                for item in case["transcript"]
            ],
            visuals=[
                ImageCapture(
                    session_id=session_id,
                    image_id=item["image_id"],
                    capture_ts=item["capture_ts"],
                    image_path=f"local://sessions/{session_id}/images/{item['image_id']}.jpg",
                    ocr_text=item.get("ocr_text"),
                    caption=item.get("caption"),
                )
                for item in case["visuals"]
            ],
        )


if __name__ == "__main__":
    unittest.main()
