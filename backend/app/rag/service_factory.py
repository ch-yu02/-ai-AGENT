"""RAG 查询服务工厂。

Agent/Skill 层不应该关心底层到底是词法检索、LlamaIndex、向量库还是未来的
持久化索引。这里用一个很小的工厂函数根据环境变量选择实现：

- 默认：``QueryService``，无外部依赖，适合开发、测试和离线 demo。
- ``RAG_QUERY_BACKEND=llamaindex``：启用可选 LlamaIndex 查询服务。

如果 LlamaIndex 未安装，查询时会自动回退词法检索，不会让 Agent API 直接
崩掉。真正部署时可以通过日志或 response warnings 发现 fallback。
"""

import os
from typing import Protocol

from .documents import RagDocument
from .query_service import QueryResult, QueryService


class RagQueryService(Protocol):
    """QaSkill 需要的最小查询服务协议。"""

    def query(
        self,
        prompt: str,
        documents: list[RagDocument],
        limit: int = 5,
    ) -> QueryResult:
        """基于课堂文档回答问题。"""


def build_query_service() -> RagQueryService:
    """按环境变量创建查询服务。

    ``RAG_QUERY_BACKEND`` 的取值：
    - ``lexical`` 或空：使用当前稳定的本地词法检索。
    - ``llamaindex``：使用可选 LlamaIndex 临时索引服务。
    """
    backend = os.getenv("RAG_QUERY_BACKEND", "lexical").strip().lower()
    if backend == "llamaindex":
        from .llama_query_service import LlamaIndexQueryService

        return LlamaIndexQueryService(fallback=QueryService())

    return QueryService()


__all__ = ["RagQueryService", "build_query_service"]
