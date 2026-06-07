import unittest
from typing import Any

from backend.app.llm import CloudLLMError
from backend.app.models import (
    ClassroomContext,
    KnowledgeNode,
    KnowledgeTree,
    TranscriptSegment,
)
from backend.app.skills import QuizMasterSkill, SummarizerSkill, TodoDetectiveSkill


class FakeLLMClient:
    """skills 测试用 fake client，避免单元测试访问真实云端模型。"""

    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None):
        self.payload = payload or {}
        self.error = error

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return self.payload


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

    def test_summarizer_uses_llm_payload_when_client_is_available(self) -> None:
        result = SummarizerSkill(
            llm_client=FakeLLMClient(
                {
                    "summary_markdown": "## 课堂总结\n- 采样定理是重点。",
                    "source_refs": [{"type": "segment", "id": "seg_001"}],
                }
            )
        ).run(self.session_id, self.context, self.graph)

        self.assertEqual(result.artifact.type, "summary")
        self.assertIn("采样定理是重点", result.answer)
        self.assertEqual(result.source_refs[0].id, "seg_001")

    def test_todo_detective_uses_llm_payload_when_client_is_available(self) -> None:
        result = TodoDetectiveSkill(
            llm_client=FakeLLMClient(
                {
                    "todos": [
                        {
                            "title": "预习采样定理",
                            "type": "preview",
                            "due_time": None,
                            "confidence": 0.9,
                            "source_refs": [{"type": "segment", "id": "seg_001"}],
                        }
                    ]
                }
            )
        ).run(self.session_id, self.context, self.graph)

        todo = result.artifact.content[0]
        self.assertEqual(todo["title"], "预习采样定理")
        self.assertEqual(todo["confidence"], 0.9)
        self.assertEqual(result.source_refs[0].id, "seg_001")

    def test_quiz_master_uses_llm_payload_when_client_is_available(self) -> None:
        result = QuizMasterSkill(
            llm_client=FakeLLMClient(
                {
                    "quiz": [
                        {
                            "question": "采样定理解决什么问题？",
                            "type": "short_answer",
                            "options": [],
                            "answer": "连续信号采样恢复条件。",
                            "explanation": "来自知识节点。",
                            "source_refs": [
                                {"type": "knowledge_node", "id": "node_sampling"}
                            ],
                        }
                    ]
                }
            )
        ).run(self.session_id, self.context, self.graph)

        question = result.artifact.content[0]
        self.assertEqual(question["answer"], "连续信号采样恢复条件。")
        self.assertEqual(result.source_refs[0].id, "node_sampling")

    def test_skill_falls_back_to_rules_when_llm_fails(self) -> None:
        result = SummarizerSkill(
            llm_client=FakeLLMClient(error=CloudLLMError("timeout"))
        ).run(self.session_id, self.context, self.graph)

        self.assertIn("采样定理", result.answer)
        self.assertTrue(any("已回退规则版" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
