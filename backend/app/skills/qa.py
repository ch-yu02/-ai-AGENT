"""课堂问答技能。

QA 技能是 Agent 接入 RAG 层的唯一入口。默认模式严格依据课堂资料回答；当
用户显式选择 grounded 模式时，技能会先检索课堂来源，再让模型基于这些来源和
自身通用知识补充解释，并在 warning 中标明“包含模型补充”。
"""

import re

from backend.app import prompts
from backend.app.llm import CloudLLMError
from backend.app.models import ClassroomContext, KnowledgeTree
from backend.app.rag import (
    MAX_SOURCE_REF_COUNT,
    QueryResult,
    RagQueryService,
    build_query_service,
    build_session_documents,
)

from .llm_support import JsonLLMClient, build_default_llm_client, require_string
from .schemas import SkillResult, SkillSourceRef


class QaSkill:
    """基于课堂资料回答用户问题。"""

    def __init__(
        self,
        query_service: RagQueryService | None = None,
        llm_client: JsonLLMClient | None = None,
    ) -> None:
        # 默认通过工厂读取 RAG_QUERY_BACKEND：
        # - 未配置时使用稳定的词法检索；
        # - 配置为 llamaindex 时使用可选 LlamaIndex 服务。
        # 测试仍可以注入 fake/query_service，避免依赖环境变量。
        self.query_service = query_service or build_query_service()
        # grounded QA 需要模型补充。未配置 LLM 时保持 None，调用时会清晰 warning
        # 并退回 strict 结果。
        self.llm_client = llm_client if llm_client is not None else build_default_llm_client()

    def run(
        self,
        session_id: str,
        prompt: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
        *,
        answer_mode: str = "strict",
        structured_notes_markdown: str | None = None,
    ) -> SkillResult:
        """检索课堂资料并返回带来源的回答。"""
        documents = build_session_documents(
            context,
            knowledge_graph,
            structured_notes_markdown=structured_notes_markdown,
        )
        result = self.query_service.query(prompt, documents, limit=MAX_SOURCE_REF_COUNT)
        source_refs = _skill_source_refs(result)
        if answer_mode == "grounded":
            return self._grounded_result(prompt, result, source_refs)

        return self._strict_result(prompt, result, source_refs)

    def _strict_result(
        self,
        prompt: str,
        result: QueryResult,
        source_refs: list[SkillSourceRef],
    ) -> SkillResult:
        """Use LLM wording when available while staying strictly source-bound."""
        warnings = list(result.warnings)

        if not source_refs or self.llm_client is None:
            return SkillResult(
                answer=result.answer,
                artifact=None,
                source_refs=source_refs,
                warnings=warnings,
            )

        try:
            payload = self.llm_client.complete_json(
                system_prompt=prompts.strict_qa_system_prompt(),
                user_prompt=prompts.strict_qa_user_prompt(
                    student_prompt=prompt,
                    retrieved_answer=result.answer,
                    source_refs=[
                        {
                            "type": ref.type,
                            "id": ref.id,
                            "ts": ref.ts,
                            "text": ref.text,
                        }
                        for ref in source_refs
                    ],
                ),
                temperature=0.1,
            )
            answer = require_string(payload, "answer")
        except (CloudLLMError, KeyError, TypeError, ValueError) as exc:
            warnings.append(f"严格问答模型生成失败，已退回检索摘要：{exc}")
            return SkillResult(
                answer=result.answer,
                artifact=None,
                source_refs=source_refs,
                warnings=warnings,
            )

        if not _is_strict_answer_grounded(answer, source_refs):
            warnings.append("严格问答模型回答未通过来源校验，已退回检索摘要。")
            return SkillResult(
                answer=result.answer,
                artifact=None,
                source_refs=source_refs,
                warnings=warnings,
            )

        return SkillResult(
            answer=answer,
            artifact=None,
            source_refs=source_refs,
            warnings=warnings,
        )

    def _grounded_result(
        self,
        prompt: str,
        result: QueryResult,
        source_refs: list[SkillSourceRef],
    ) -> SkillResult:
        """在课堂检索结果基础上加入模型通用知识补充。

        这里故意要求先有课堂检索结果，再让模型补充。即便模型知道很多课外知识，
        回答也必须以课堂来源为锚点；如果当前课堂没有任何来源，grounded 模式也
        不会退化成开放域问答。
        """
        warnings = list(result.warnings)

        if not source_refs:
            warnings.append("grounded 模式没有找到课堂依据，未使用模型课外知识补充。")
            return SkillResult(
                answer=result.answer,
                source_refs=source_refs,
                warnings=warnings,
            )

        if self.llm_client is None:
            warnings.append("未配置 LLM，grounded 模式已退回严格课堂依据回答。")
            return SkillResult(
                answer=result.answer,
                source_refs=source_refs,
                warnings=warnings,
            )

        try:
            payload = self.llm_client.complete_json(
                system_prompt=prompts.grounded_qa_system_prompt(),
                user_prompt=prompts.grounded_qa_user_prompt(
                    student_prompt=prompt,
                    retrieved_answer=result.answer,
                    source_refs=[
                        {
                            "type": ref.type,
                            "id": ref.id,
                            "ts": ref.ts,
                            "text": ref.text,
                        }
                        for ref in source_refs
                    ],
                ),
                temperature=0.2,
            )
            answer = require_string(payload, "answer")
        except (CloudLLMError, KeyError, TypeError, ValueError) as exc:
            warnings.append(f"grounded 模型补充失败，已退回严格课堂依据回答：{exc}")
            return SkillResult(
                answer=result.answer,
                source_refs=source_refs,
                warnings=warnings,
            )

        warnings.append("回答包含模型通用知识补充；课堂依据见来源引用。")
        return SkillResult(
            answer=answer,
            source_refs=source_refs,
            warnings=warnings,
        )


def _skill_source_refs(result: QueryResult) -> list[SkillSourceRef]:
    return [
        SkillSourceRef(
            type=ref.type,
            id=ref.id,
            ts=ref.ts,
            text=ref.text,
        )
        for ref in result.source_refs[:MAX_SOURCE_REF_COUNT]
    ]


def _is_strict_answer_grounded(
    answer: str,
    source_refs: list[SkillSourceRef],
) -> bool:
    """Return true when a strict QA answer is plausibly supported by sources."""
    answer_text = answer.strip()
    if not answer_text:
        return False
    if "补充解释" in answer_text:
        return False

    source_text = "\n".join(ref.text for ref in source_refs)
    source_key = _qa_comparable_text(source_text)
    if not source_key:
        return False

    answer_key = _qa_comparable_text(answer_text)
    if answer_key and answer_key in source_key:
        return True

    source_terms = set(_qa_terms(source_text))
    answer_terms = [
        term
        for term in _qa_terms(answer_text)
        if term not in _QA_GENERIC_TERMS
    ]
    if not answer_terms:
        return False

    matched_terms = [
        term
        for term in answer_terms
        if term in source_terms or term in source_key
    ]
    required = 1 if len(answer_terms) <= 3 else 2
    return len(matched_terms) >= required


def _qa_comparable_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.lower(), flags=re.UNICODE)


def _qa_terms(value: str) -> list[str]:
    """Create lightweight terms for Chinese/English grounding checks."""
    raw_terms = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", value)
    terms: list[str] = []
    for term in raw_terms:
        lowered = term.lower()
        terms.append(lowered)
        if re.fullmatch(r"[\u4e00-\u9fff]{5,}", term):
            terms.extend(term[index : index + 4] for index in range(len(term) - 3))
    return terms


_QA_GENERIC_TERMS = {
    "根据",
    "课堂",
    "资料",
    "内容",
    "相关",
    "回答",
    "可以",
    "说明",
    "提到",
    "找到",
}


__all__ = ["QaSkill"]
