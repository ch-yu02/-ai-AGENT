"""轻量级课堂文档索引管理器。

这里还不是向量索引，只是在 ``build_session_documents()`` 外包了一层内存缓存。
这样后端其他模块可以先依赖 ``IndexManager`` 这个抽象，等后续接入
LlamaIndex 时，再把内部实现替换成真正的索引构建、加载和持久化。

后续替换点：
- 课堂结束时构建一次索引。
- 持久化/加载 ``data/sessions/{session_id}/llama_index/``。
- 正在录制时按批次增量更新或失效缓存。
"""

from backend.app.models import ClassroomContext, KnowledgeTree

from .documents import RagDocument, build_session_documents


class IndexManager:
    """按 session_id 构建并缓存可检索文档。"""

    def __init__(self) -> None:
        self._documents_by_session: dict[str, list[RagDocument]] = {}

    def build_session_index(
        self,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> list[RagDocument]:
        """为一节课堂构建文档索引，并写入内存缓存。"""
        documents = build_session_documents(context, knowledge_graph)
        self._documents_by_session[context.session_id] = documents
        return documents

    def get_documents(self, session_id: str) -> list[RagDocument]:
        """读取某节课的缓存文档；没有缓存时返回空列表。"""
        return list(self._documents_by_session.get(session_id, []))

    def clear(self) -> None:
        """清空所有内存文档索引，主要用于测试和本地重置。"""
        self._documents_by_session.clear()


index_manager = IndexManager()
"""默认进程内文档索引缓存。"""


__all__ = ["IndexManager", "index_manager"]
