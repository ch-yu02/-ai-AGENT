"""自测题生成技能。

未配置 LLM 时，本技能使用规则版短答题生成，保证离线可演示、可追溯。配置
LLM 后会优先生成更自然的题目、答案和解析；模型失败时仍回退规则版。
"""

from typing import Any

from backend.app.llm import CloudLLMError
from backend.app.models import ClassroomContext, KnowledgeTree

from .llm_support import (
    JsonLLMClient,
    build_default_llm_client,
    classroom_brief,
    require_list,
    source_refs_from_payload,
)
from .schemas import SkillArtifact, SkillResult, SkillSourceRef


class QuizMasterSkill:
    """生成课堂自测题。"""

    def __init__(self, llm_client: JsonLLMClient | None = None) -> None:
        # quiz 仍然必须由用户主动触发；这里的 LLM client 只决定触发后用云端
        # 还是规则版生成，不改变“结束课堂不自动生成 quiz.json”的业务规则。
        self.llm_client = llm_client if llm_client is not None else build_default_llm_client()

    def run(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """根据知识节点或字幕生成自测题。"""
        if self.llm_client is not None:
            try:
                return self._run_llm(session_id, context, knowledge_graph)
            except (CloudLLMError, KeyError, TypeError, ValueError) as exc:
                fallback = self._run_rule_based(session_id, context, knowledge_graph)
                fallback.warnings.append(f"LLM 自测题生成失败，已回退规则版：{exc}")
                return fallback

        return self._run_rule_based(session_id, context, knowledge_graph)

    def _run_rule_based(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """规则版短答题生成。"""
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

    def _run_llm(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """使用云端模型生成结构化自测题。"""
        assert self.llm_client is not None
        payload = self.llm_client.complete_json(
            system_prompt=(
                "你是课堂自测题生成助手。只能基于课堂资料出题，不要引入课外内容。"
                "请输出 JSON object，字段为 quiz。quiz 是数组，每项包含 question、"
                "type、options、answer、explanation、source_refs。source_refs 元素"
                "包含 type(segment 或 knowledge_node) 和 id。"
            ),
            user_prompt=(
                "请生成 3 到 5 道中文自测题，优先覆盖关键概念。输出必须是 JSON，"
                "不要 Markdown code fence。\n\n"
                + classroom_brief(context, knowledge_graph)
            ),
            temperature=0.2,
        )
        questions = [self._normalize_question(item) for item in require_list(payload, "quiz")]
        refs = source_refs_from_payload(
            [ref for item in questions for ref in item.get("source_refs", [])],
            context,
            knowledge_graph,
        )

        warnings: list[str] = []
        if not questions:
            warnings.append("LLM 没有返回自测题。")

        answer = (
            "已根据课堂资料生成自测题：\n"
            + "\n".join(f"- {item['question']}" for item in questions)
            if questions
            else "没有找到足够的课堂资料生成自测题。"
        )
        return SkillResult(
            answer=answer,
            artifact=SkillArtifact(type="quiz", title="自测题", content=questions),
            source_refs=refs,
            warnings=warnings,
        )

    def _normalize_question(self, item: dict[str, Any]) -> dict[str, Any]:
        """把 LLM 返回题目收敛为 quiz.json 的稳定字段。"""
        question = str(item.get("question", "")).strip()
        if not question:
            raise CloudLLMError("LLM quiz item missing question")

        options = item.get("options", [])
        source_refs = item.get("source_refs", [])
        return {
            "question": question,
            "type": str(item.get("type", "short_answer")) or "short_answer",
            "options": options if isinstance(options, list) else [],
            "answer": str(item.get("answer", "")).strip(),
            "explanation": str(item.get("explanation", "")).strip(),
            "source_refs": source_refs if isinstance(source_refs, list) else [],
        }


__all__ = ["QuizMasterSkill"]
