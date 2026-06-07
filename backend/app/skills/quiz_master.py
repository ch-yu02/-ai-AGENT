"""规则版自测题生成技能。

第一版自测题不追求难度和题型丰富度，而是保证任何有课堂资料的 session 都能
生成可演示、可追溯的短答题。它优先使用知识图谱节点，因为节点已经代表课堂
中的概念；如果图谱还没有内容，就降级使用字幕片段。
"""

from backend.app.models import ClassroomContext, KnowledgeTree

from .schemas import SkillArtifact, SkillResult, SkillSourceRef


class QuizMasterSkill:
    """生成课堂自测题。"""

    def run(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """根据知识节点或字幕生成短答题。"""
        nodes = knowledge_graph.nodes[:5]
        questions: list[dict[str, str]] = []
        source_refs: list[SkillSourceRef] = []

        for index, node in enumerate(nodes, start=1):
            answer = node.summary or f"课堂知识点：{node.label}"
            questions.append(
                {
                    "question": f"{index}. 请解释“{node.label}”的含义或作用。",
                    "type": "short_answer",
                    "options": [],
                    "answer": answer,
                    "explanation": "题目由课堂知识图谱节点生成。",
                    "source_refs": [
                        {
                            "type": "knowledge_node",
                            "id": node.node_id,
                            "ts": None,
                            "text": node.summary or node.label,
                        }
                    ],
                }
            )
            source_refs.append(
                SkillSourceRef(
                    type="knowledge_node",
                    id=node.node_id,
                    text=node.summary or node.label,
                )
            )

        if not questions:
            # 没有知识节点时也不让自测题功能直接空掉。字幕降级题虽然简单，
            # 但能帮助验证前后端结构化产物流转是否正常。
            for index, segment in enumerate(context.transcript[:3], start=1):
                questions.append(
                    {
                        "question": f"{index}. 这段课堂内容主要讲了什么？",
                        "type": "short_answer",
                        "options": [],
                        "answer": segment.text,
                        "explanation": "题目由课堂字幕片段生成。",
                        "source_refs": [
                            {
                                "type": "segment",
                                "id": segment.segment_id,
                                "ts": segment.start_ts,
                                "text": segment.text,
                            }
                        ],
                    }
                )
                source_refs.append(
                    SkillSourceRef(
                        type="segment",
                        id=segment.segment_id,
                        ts=segment.start_ts,
                        text=segment.text,
                    )
                )

        warnings: list[str] = []
        if not questions:
            warnings.append("还没有知识点或字幕，无法生成自测题。")

        answer = (
            "已根据课堂资料生成自测题：\n"
            + "\n".join(f"- {item['question']}" for item in questions)
            if questions
            else "没有找到足够的课堂资料生成自测题。"
        )

        return SkillResult(
            answer=answer,
            artifact=SkillArtifact(type="quiz", title="自测题", content=questions),
            source_refs=source_refs,
            warnings=warnings,
        )


__all__ = ["QuizMasterSkill"]
