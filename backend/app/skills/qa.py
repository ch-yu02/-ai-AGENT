"""课堂问答技能。

QA 技能是 Agent 接入 RAG 层的唯一入口。当前 RAG 层还是本地关键词检索；
后续换成 LlamaIndex 时，优先替换 ``QueryService``，而不是改 Agent 或前端。
"""

from backend.app.models import ClassroomContext, KnowledgeTree
from backend.app.rag import RagQueryService, build_query_service, build_session_documents

from .schemas import SkillResult, SkillSourceRef


class QaSkill:
    """基于课堂资料回答用户问题。"""

    def __init__(self, query_service: RagQueryService | None = None) -> None:
        # 默认通过工厂读取 RAG_QUERY_BACKEND：
        # - 未配置时使用稳定的词法检索；
        # - 配置为 llamaindex 时使用可选 LlamaIndex 服务。
        # 测试仍可以注入 fake/query_service，避免依赖环境变量。
        self.query_service = query_service or build_query_service()

    def run(
        self,
        session_id: str,
        prompt: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """检索课堂资料并返回带来源的回答。"""
        documents = build_session_documents(context, knowledge_graph)
        result = self.query_service.query(prompt, documents)

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


__all__ = ["QaSkill"]
