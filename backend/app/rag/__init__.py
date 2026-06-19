"""课堂数据 RAG 工具包。

当前包提供文档转换、默认词法检索，以及可选 LlamaIndex 向量检索能力。
默认路径不引入重依赖；显式配置 ``RAG_QUERY_BACKEND=llamaindex`` 或
``GLOBAL_SEARCH_BACKEND=llamaindex`` 后，服务会尝试加载可选依赖并在失败时
回退到词法检索，尽量不影响 Agent API 和前端调用方式。
"""

from .documents import RagDocument, RagDocumentType, build_session_documents
from .global_index_service import GlobalIndexHit, GlobalLlamaIndexService
from .index_manager import IndexManager, index_manager
from .llama_query_service import LlamaIndexQueryService
from .query_service import MAX_SOURCE_REF_COUNT, QueryResult, QueryService, RagSourceRef
from .service_factory import RagQueryService, build_query_service


__all__ = [
    "IndexManager",
    "GlobalIndexHit",
    "GlobalLlamaIndexService",
    "LlamaIndexQueryService",
    "MAX_SOURCE_REF_COUNT",
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
