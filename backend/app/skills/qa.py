"""课堂问答技能。

QA 技能是 Agent 接入 RAG 层的唯一入口。默认模式严格依据课堂资料回答；当
用户显式选择 grounded 模式时，技能会先检索课堂来源，再让模型基于这些来源和
自身通用知识补充解释，并在 warning 中标明“包含模型补充”。
"""

from backend.app.llm import CloudLLMError
from backend.app.models import ClassroomContext, KnowledgeTree
from backend.app.rag import (
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
    ) -> SkillResult:
        """检索课堂资料并返回带来源的回答。"""
        documents = build_session_documents(context, knowledge_graph)
        result = self.query_service.query(prompt, documents)
        if answer_mode == "grounded":
            return self._grounded_result(prompt, result)

        return SkillResult(
            answer=result.answer,
            artifact=None,
            source_refs=[
                SkillSourceRef(
                    type=ref.type,
                    id=ref.id,
                    ts=ref.ts,
                    text=ref.text,
                )
                for ref in result.source_refs
            ],
            warnings=result.warnings,
        )

    def _grounded_result(self, prompt: str, result: QueryResult) -> SkillResult:
        """在课堂检索结果基础上加入模型通用知识补充。

        这里故意要求先有课堂检索结果，再让模型补充。即便模型知道很多课外知识，
        回答也必须以课堂来源为锚点；如果当前课堂没有任何来源，grounded 模式也
        不会退化成开放域问答。
        """
        source_refs = [
            SkillSourceRef(
                type=ref.type,
                id=ref.id,
                ts=ref.ts,
                text=ref.text,
            )
            for ref in result.source_refs
        ]
        warnings = list(result.warnings)

        if not result.source_refs:
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
                system_prompt=(
                    "你是课堂答疑助手。必须优先依据课堂来源回答；可以使用你的通用"
                    "知识补充解释，但必须明确区分课堂内容和补充解释。不要编造课堂"
                    "中没有出现过的来源。请输出 JSON object，字段 answer。"
                ),
                user_prompt=(
                    f"学生问题：{prompt}\n\n"
                    f"课堂检索回答：{result.answer}\n\n"
                    "课堂来源：\n"
                    + "\n".join(
                        f"- {ref.type}:{ref.id}; ts={ref.ts}; text={ref.text}"
                        for ref in result.source_refs
                    )
                    + "\n\n请用中文回答，格式上明确包含“根据课堂内容”和“补充解释”。"
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


__all__ = ["QaSkill"]
