"""课堂数据 RAG 工具包。

当前包提供无外部依赖的文档转换和词法检索能力。它刻意保持接近 Phase 3
计划中的 LlamaIndex 形态，但暂时不引入重依赖。后续真正接入 LlamaIndex 时，
优先替换 ``documents`` / ``index_manager`` / ``query_service`` 的内部实现，
尽量不影响 Agent API 和前端调用方式。
"""

from .documents import RagDocument, RagDocumentType, build_session_documents
from .global_index_service import GlobalIndexHit, GlobalLlamaIndexService
from .index_manager import IndexManager, index_manager
from .llama_query_service import LlamaIndexQueryService
from .query_service import QueryResult, QueryService, RagSourceRef
from .service_factory import RagQueryService, build_query_service


__all__ = [
    "IndexManager",
    "GlobalIndexHit",
    "GlobalLlamaIndexService",
    "LlamaIndexQueryService",
    "QueryResult",
    "QueryService",
    "RagDocument",
    "RagDocumentType",
    "RagQueryService",
    "RagSourceRef",
    "build_session_documents",
    "build_query_service",
    "index_manager",
]
