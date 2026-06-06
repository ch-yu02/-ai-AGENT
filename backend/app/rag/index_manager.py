"""Lightweight session document index manager.

This is not a vector index yet. It is a small cache around
``build_session_documents()`` so the rest of the backend can depend on an
``IndexManager`` abstraction before LlamaIndex is introduced.

Future replacement points:
- build documents once when a session ends,
- persist/load ``data/sessions/{session_id}/llama_index/``,
- invalidate or incrementally update documents while recording.
"""

from backend.app.models import ClassroomContext, KnowledgeTree

from .documents import RagDocument, build_session_documents


class IndexManager:
    """Build and cache retrievable documents by session_id."""

    def __init__(self) -> None:
        self._documents_by_session: dict[str, list[RagDocument]] = {}

    def build_session_index(
        self,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> list[RagDocument]:
        """Build and cache documents for one session."""
        documents = build_session_documents(context, knowledge_graph)
        self._documents_by_session[context.session_id] = documents
        return documents

    def get_documents(self, session_id: str) -> list[RagDocument]:
        """Return cached documents for a session, or an empty list."""
        return list(self._documents_by_session.get(session_id, []))

    def clear(self) -> None:
        """Clear all cached document indexes."""
        self._documents_by_session.clear()


index_manager = IndexManager()
"""Default in-process document index cache."""


__all__ = ["IndexManager", "index_manager"]
