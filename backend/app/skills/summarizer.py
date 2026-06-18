"""课堂总结技能。

默认情况下，本技能使用可测试、可追溯、无 API key 依赖的规则版总结。配置
``LLM_API_KEY`` 后，会优先尝试云端模型生成更自然的总结；模型不可用、超时或
返回结构不合规时自动回退规则版，避免影响课堂结束保存。
"""

from backend.app import prompts
from backend.app.llm import CloudLLMError
from backend.app.models import ClassroomContext, KnowledgeTree

from .llm_support import (
    JsonLLMClient,
    build_default_llm_client,
    classroom_brief,
    source_refs_from_payload,
)
from .schemas import SkillArtifact, SkillResult, SkillSourceRef


class SummarizerSkill:
    """生成课堂重点总结。"""

    def __init__(self, llm_client: JsonLLMClient | None = None) -> None:
        # 允许测试传 fake client；生产环境未显式传入时，按环境变量决定是否启用
        # 云端模型。没有 LLM_API_KEY 时这里是 None，技能完全保持离线规则版。
        self.llm_client = llm_client if llm_client is not None else build_default_llm_client()

    def run(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """根据课堂上下文和知识图谱生成总结。

        调用顺序：
        1. 若已配置 LLM，先让模型基于课堂 brief 输出 JSON 总结。
        2. 校验失败或调用失败时回退规则版，并把失败原因放进 warning。
        3. 未配置 LLM 时直接使用规则版，保持本地 demo 不需要 API key。
        """
        if self.llm_client is not None:
            try:
                return self._run_llm(session_id, context, knowledge_graph)
            except (CloudLLMError, KeyError, TypeError, ValueError) as exc:
                fallback = self._run_rule_based(session_id, context, knowledge_graph)
                fallback.warnings.append(f"LLM 总结失败，已回退规则版：{exc}")
                return fallback

        return self._run_rule_based(session_id, context, knowledge_graph)

    def _run_rule_based(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """规则版总结实现。

        策略说明：
        - 优先列出知识图谱中的前几个知识节点，帮助用户看到概念清单。
        - 再补充前几条字幕原文，避免规则版总结过度“发挥”。
        - 来源引用主要使用字幕片段；知识节点目前缺少稳定时间戳，后续可以通过
          node.source_refs 继续映射回字幕或视觉来源。
        """
        transcript = context.transcript[:8]
        nodes = knowledge_graph.nodes[:8]
        source_refs = [
            SkillSourceRef(
                type="segment",
                id=segment.segment_id,
                ts=segment.start_ts,
                text=segment.text,
            )
            for segment in transcript[:4]
        ]

        points: list[str] = []
        if nodes:
            points.append("知识点：" + "、".join(node.label for node in nodes))
        points.extend(segment.text for segment in transcript[:5] if segment.text)

        warnings: list[str] = []
        if not points:
            warnings.append("还没有可用于总结的课堂内容。")

        answer = (
            "这节课目前可归纳为：\n"
            + "\n".join(f"- {point}" for point in points)
            if points
            else "没有找到足够的课堂内容生成总结。"
        )

        return SkillResult(
            answer=answer,
            artifact=SkillArtifact(
                type="summary",
                title="课堂总结",
                content=answer,
            ),
            source_refs=source_refs,
            warnings=warnings,
        )

    def _run_llm(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """使用云端模型生成结构化总结。"""
        assert self.llm_client is not None
        brief = classroom_brief(context, knowledge_graph)
        payload = self.llm_client.complete_json(
            system_prompt=prompts.summary_system_prompt(),
            user_prompt=prompts.summary_user_prompt(brief),
            temperature=0.2,
        )
        summary = str(payload["summary_markdown"]).strip()
        if not summary:
            raise CloudLLMError("LLM summary is empty")

        source_refs = source_refs_from_payload(
            payload.get("source_refs", []),
            context,
            knowledge_graph,
        )
        return SkillResult(
            answer=summary,
            artifact=SkillArtifact(
                type="summary",
                title="课堂总结",
                content=summary,
            ),
            source_refs=source_refs,
            warnings=[],
        )


__all__ = ["SummarizerSkill"]
