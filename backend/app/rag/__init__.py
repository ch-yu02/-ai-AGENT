"""RAG utilities for classroom data.

The package currently provides dependency-free document conversion and lexical
retrieval. It deliberately mirrors the Phase 3 LlamaIndex shape without adding
heavy dependencies yet.
"""

from .documents import RagDocument, RagDocumentType, build_session_documents
from .index_manager import IndexManager, index_manager
from .query_service import QueryResult, QueryService, RagSourceRef


__all__ = [
    "IndexManager",
    "QueryResult",
    "QueryService",
    "RagDocument",
    "RagDocumentType",
    "RagSourceRef",
    "build_session_documents",
    "index_manager",
]
