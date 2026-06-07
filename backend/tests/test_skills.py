import unittest

from backend.app.models import (
    ClassroomContext,
    KnowledgeNode,
    KnowledgeTree,
    TranscriptSegment,
)
from backend.app.skills import QuizMasterSkill, SummarizerSkill, TodoDetectiveSkill


class SkillsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_id = "lec_skills_001"
        self.segment = TranscriptSegment(
            segment_id="seg_001",
            session_id=self.session_id,
            start_ts=1.0,
            end_ts=3.0,
            text="作业是完成第三题，并预习采样定理。",
        )
        self.context = ClassroomContext(
            session_id=self.session_id,
            transcript=[self.segment],
        )
        self.graph = KnowledgeTree(
            session_id=self.session_id,
            nodes=[
                KnowledgeNode(
                    node_id="node_sampling",
                    label="采样定理",
                    summary="描述连续信号采样恢复条件。",
                )
            ],
        )

    def test_summarizer_returns_summary_artifact_and_sources(self) -> None:
        result = SummarizerSkill().run(self.session_id, self.context, self.graph)

        self.assertIsNotNone(result.artifact)
        self.assertEqual(result.artifact.type, "summary")
        self.assertIn("采样定理", result.answer)
        self.assertEqual(result.source_refs[0].id, "seg_001")

    def test_todo_detective_returns_structured_candidates(self) -> None:
        result = TodoDetectiveSkill().run(self.session_id, self.context, self.graph)

        self.assertIsNotNone(result.artifact)
        self.assertEqual(result.artifact.type, "todos")
        todo = result.artifact.content[0]
        self.assertEqual(todo["type"], "candidate")
        self.assertEqual(todo["source_refs"][0]["id"], "seg_001")
        self.assertTrue(result.warnings)

    def test_quiz_master_prefers_knowledge_nodes(self) -> None:
        result = QuizMasterSkill().run(self.session_id, self.context, self.graph)

        self.assertIsNotNone(result.artifact)
        self.assertEqual(result.artifact.type, "quiz")
        question = result.artifact.content[0]
        self.assertIn("采样定理", question["question"])
        self.assertEqual(question["source_refs"][0]["id"], "node_sampling")


if __name__ == "__main__":
    unittest.main()
