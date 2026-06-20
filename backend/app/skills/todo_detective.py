"""待办提取技能。

待办提取的目标是从课堂字幕中找出“作业、预习、考试、提交”等提醒。未配置
LLM 时使用关键词规则；配置 LLM 后优先让模型输出结构化 todos。无论哪条路径，
输出都保持 ``todos.json`` 友好的字段形态。
"""

from typing import Any

from backend.app import prompts
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


class TodoDetectiveSkill:
    """从课堂字幕中提取疑似待办。"""

    _todo_keywords = ("作业", "待办", "预习", "复习", "考试", "提交", "完成", "下节课")
    _generated_todo_types = {
        "generated_review",
        "generated",
        "review",
        "practice",
        "self_check",
        "study_plan",
    }

    def __init__(self, llm_client: JsonLLMClient | None = None) -> None:
        # 生产环境按 LLM_API_KEY 自动启用；测试可注入 fake client。没有配置时
        # 保持纯本地规则版，避免课堂结束保存依赖网络。
        self.llm_client = llm_client if llm_client is not None else build_default_llm_client()

    def run(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """返回待办候选列表。

        有 LLM 时先尝试结构化提取，失败后回退关键词规则。回退 warning 会告诉
        用户结果是规则版候选，仍需人工确认。
        """
        if self.llm_client is not None:
            try:
                return self._run_llm(session_id, context, knowledge_graph)
            except (CloudLLMError, KeyError, TypeError, ValueError) as exc:
                fallback = self._run_rule_based(session_id, context, knowledge_graph)
                fallback.warnings.append(f"LLM 待办提取失败，已回退规则版：{exc}")
                return fallback

        return self._run_rule_based(session_id, context, knowledge_graph)

    def _run_rule_based(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """关键词规则版待办提取。

        ``knowledge_graph`` 暂时未参与规则版待办提取，但保留在入参里，是为了让
        所有技能拥有一致调用形态。后续 LLM 版本可以同时参考字幕和知识图谱，
        判断待办与哪个知识点相关。
        """
        matched = [
            segment
            for segment in context.transcript
            if any(keyword in segment.text for keyword in self._todo_keywords)
        ]

        items = [
            {
                "title": segment.text,
                "type": "candidate",
                "due_time": None,
                "source_refs": [
                    {
                        "type": "segment",
                        "id": segment.segment_id,
                        "ts": segment.start_ts,
                        "text": segment.text,
                    }
                ],
                # 固定置信度表示“关键词命中但未经过模型确认”。后续可以由
                # TodoDetectiveSkill 的 LLM 版本给出更细粒度置信度。
                "confidence": 0.6,
            }
            for segment in matched
        ]

        source_refs = [
            SkillSourceRef(
                type="segment",
                id=segment.segment_id,
                ts=segment.start_ts,
                text=segment.text,
            )
            for segment in matched[:6]
        ]

        if items:
            answer = "我找到这些疑似待办或考试相关提醒：\n" + "\n".join(
                f"- {item['title']}" for item in items
            )
            warnings = ["规则版待办提取会保留候选项，请人工确认。"]
        else:
            answer = "没有在课堂资料中找到明确的作业或待办提醒。"
            warnings = ["未匹配到作业、待办、预习、考试等关键词。"]

        return SkillResult(
            answer=answer,
            artifact=SkillArtifact(type="todos", title="待办候选", content=items),
            source_refs=source_refs,
            warnings=warnings,
        )

    def _run_llm(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """使用云端模型生成结构化待办列表。"""
        assert self.llm_client is not None
        brief = classroom_brief(context, knowledge_graph)
        payload = self.llm_client.complete_json(
            system_prompt=prompts.todo_system_prompt(),
            user_prompt=prompts.todo_user_prompt(brief),
            temperature=0.1,
        )
        items = [self._normalize_todo(item) for item in require_list(payload, "todos")]
        refs = source_refs_from_payload(
            [ref for item in items for ref in item.get("source_refs", [])],
            context,
            knowledge_graph,
        )

        if items and all(self._is_generated_todo(item) for item in items):
            answer = (
                "没有找到老师明确布置的待办；我基于课堂内容生成了这些课后学习待办：\n"
                + "\n".join(f"- {item['title']}" for item in items)
            )
            warnings = ["这些是模型根据课堂内容生成的学习建议，不代表老师明确布置。"]
        elif items:
            answer = "我找到这些待办或考试相关提醒：\n" + "\n".join(
                f"- {item['title']}" for item in items
            )
            warnings: list[str] = []
        else:
            answer = "没有在课堂资料中找到明确的作业或待办提醒，且模型没有生成学习待办。"
            warnings = ["LLM 未按要求生成 3 到 5 个课后学习待办。"]

        return SkillResult(
            answer=answer,
            artifact=SkillArtifact(type="todos", title="待办候选", content=items),
            source_refs=refs,
            warnings=warnings,
        )

    def _normalize_todo(self, item: dict[str, Any]) -> dict[str, Any]:
        """把 LLM 返回的待办项收敛到 todos.json 的稳定字段。"""
        title = str(item.get("title", "")).strip()
        if not title:
            raise CloudLLMError("LLM todo item missing title")

        confidence = item.get("confidence", 0.7)
        if not isinstance(confidence, (int, float)):
            confidence = 0.7

        source_refs = item.get("source_refs", [])
        return {
            "title": title,
            "type": str(item.get("type", "candidate")) or "candidate",
            "due_time": item.get("due_time"),
            "source_refs": source_refs if isinstance(source_refs, list) else [],
            "confidence": max(0.0, min(1.0, float(confidence))),
        }

    def _is_generated_todo(self, item: dict[str, Any]) -> bool:
        """Return whether a todo is an LLM-generated study suggestion."""
        item_type = str(item.get("type", "")).strip().lower()
        return item_type in self._generated_todo_types


__all__ = ["TodoDetectiveSkill"]
