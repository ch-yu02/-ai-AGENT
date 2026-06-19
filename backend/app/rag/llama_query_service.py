"""可选 LlamaIndex 单节课查询服务。

这个模块实现 Phase 6：把当前 ``RagDocument`` 转换成
``llama_index.core.Document``，查询时优先加载已保存的单节课索引；索引不存在
时临时构建；结束课堂时可以主动构建并持久化到本地。

设计约束：
- ``llama-index`` 不是当前项目的硬依赖。未安装时，本服务会回退到词法检索。
- 持久化路径由 ``LocalStorage.session_index_dir()`` 提供，RAG 层不直接拼接
  ``data/sessions``。
- 不让 Agent/Frontend 直接接触 LlamaIndex 类型，避免框架替换影响 API 契约。
"""

from pathlib import Path
from typing import Any, Callable

from .documents import RagDocument
from .query_service import (
    MAX_SOURCE_REF_COUNT,
    QueryResult,
    QueryService,
    RagSourceRef,
    compact_source_ref_text,
)
from .llama_settings import configure_llamaindex_settings


class LlamaIndexQueryService:
    """基于 LlamaIndex 的单节课临时索引查询服务。

    生产路径默认从 ``llama_index.core`` 动态导入 ``Document`` 和
    ``VectorStoreIndex``。测试可以注入 fake ``document_factory`` 和
    ``index_factory``，从而不安装 llama-index、不访问真实模型。
    """

    def __init__(
        self,
        *,
        fallback: QueryService | None = None,
        document_factory: Callable[..., Any] | None = None,
        index_factory: Any | None = None,
        storage_context_factory: Any | None = None,
        load_index_func: Callable[..., Any] | None = None,
        index_dir_resolver: Callable[[str], Path] | None = None,
    ) -> None:
        self.fallback = fallback or QueryService()
        self._document_factory = document_factory
        self._index_factory = index_factory
        self._storage_context_factory = storage_context_factory
        self._load_index_func = load_index_func
        self._index_dir_resolver = index_dir_resolver

    def query(
        self,
        prompt: str,
        documents: list[RagDocument],
        limit: int = 5,
    ) -> QueryResult:
        """使用 LlamaIndex 查询课堂文档。

        流程：
        1. 如果能解析出 session_id 且本地持久化索引存在，优先加载索引。
        2. 如果没有索引，则把 ``RagDocument`` 转成 LlamaIndex Document 并构建
           本次查询的临时内存索引。
        3. 优先调用 retriever 做向量召回，只在旧版本/测试 fake 不支持时调用
           query engine。
        4. 从 source_nodes 中恢复 EDU-Mate 来源引用。

        任一环节失败都会回退到词法检索，并把失败原因放入 warning。这样开发者
        可以在未安装依赖时继续跑完整测试，也不会让用户的问题请求直接失败。
        """
        if not documents:
            return self.fallback.query(prompt, documents, limit=limit)

        try:
            index = self._load_or_build_index(documents)
            source_limit = min(max(1, limit), MAX_SOURCE_REF_COUNT)
            source_nodes = self._retrieve_source_nodes(
                index,
                prompt,
                source_limit=source_limit,
            )
            if source_nodes is not None:
                refs = self._source_refs_from_nodes(source_nodes, limit=source_limit)
                if not refs:
                    return QueryResult(
                        answer="LlamaIndex 向量检索没有返回可映射的课堂来源。",
                        source_refs=[],
                        warnings=["LlamaIndex 未返回可映射的来源引用。"],
                    )
                return QueryResult(
                    answer=self._answer_from_refs(refs),
                    source_refs=refs,
                    warnings=[],
                )

            query_engine = index.as_query_engine(similarity_top_k=source_limit)
            response = query_engine.query(prompt)
            refs = self._source_refs_from_response(response, limit=source_limit)

            if not refs:
                # LlamaIndex 给出文本但没有来源时，不直接丢弃回答，而是附加 warning。
                # 课堂 Agent 的原则是“尽量带来源”；缺来源需要让前端可见。
                return QueryResult(
                    answer=str(response),
                    source_refs=[],
                    warnings=["LlamaIndex 未返回可映射的来源引用。"],
                )

            return QueryResult(
                answer=str(response),
                source_refs=refs,
                warnings=[],
            )
        except Exception as exc:  # noqa: BLE001 - fallback 需要覆盖可选依赖的多类异常。
            fallback_result = self.fallback.query(prompt, documents, limit=limit)
            return QueryResult(
                answer=fallback_result.answer,
                source_refs=fallback_result.source_refs,
                warnings=[
                    *fallback_result.warnings,
                    f"LlamaIndex 查询不可用，已回退词法检索：{exc}",
                ],
            )

    def build_and_persist(
        self,
        documents: list[RagDocument],
        *,
        session_id: str | None = None,
    ) -> Path:
        """构建并持久化一节课的 LlamaIndex 索引。

        调用时机通常是课堂结束保存完 metadata/transcript/timeline/graph 之后。
        这里会：
        1. 确认可以解析出 session_id。
        2. 通过 ``index_dir_resolver`` 获取安全的 ``llama_index`` 目录。
        3. 构建索引。
        4. 调用 ``index.storage_context.persist(persist_dir=...)`` 落盘。

        如果 LlamaIndex 未安装、模型/embedding 配置不可用或持久化失败，会抛出
        异常。API 层会捕获这些异常并放进 warning，不影响课堂主文件保存。
        """
        resolved_session_id = session_id or self._session_id_from_documents(documents)
        if not resolved_session_id:
            raise ValueError("Cannot persist index without session_id")
        if self._index_dir_resolver is None:
            raise ValueError("No index_dir_resolver configured for persistence")

        index_dir = self._index_dir_resolver(resolved_session_id)
        index_dir.mkdir(parents=True, exist_ok=True)
        index = self._build_index(documents)
        storage_context = getattr(index, "storage_context", None)
        persist = getattr(storage_context, "persist", None)
        if not callable(persist):
            raise RuntimeError("LlamaIndex index does not expose storage_context.persist")

        persist(persist_dir=str(index_dir))
        return index_dir

    def _load_or_build_index(self, documents: list[RagDocument]) -> Any:
        """优先加载持久化索引，失败时构建临时索引。

        加载失败在这里不吞掉，因为 query() 外层会统一 fallback 到词法检索并
        带 warning。这样可以避免损坏索引悄悄产生不可信结果。
        """
        session_id = self._session_id_from_documents(documents)
        if session_id and self._index_dir_resolver is not None:
            index_dir = self._index_dir_resolver(session_id)
            if self._persisted_index_exists(index_dir):
                return self._load_persisted_index(index_dir)

        return self._build_index(documents)

    def _build_index(self, documents: list[RagDocument]) -> Any:
        """把 RagDocument 转成 LlamaIndex Document 并构建索引。"""
        document_factory, index_factory, _, _ = self._resolve_llamaindex_types()
        llama_documents = [
            self._to_llama_document(document_factory, document)
            for document in documents
        ]
        return index_factory.from_documents(llama_documents)

    def _load_persisted_index(self, index_dir: Path) -> Any:
        """从本地 llama_index 目录加载索引。"""
        _, _, storage_context_factory, load_index_func = self._resolve_llamaindex_types()
        storage_context = storage_context_factory.from_defaults(
            persist_dir=str(index_dir)
        )
        return load_index_func(storage_context)

    def _resolve_llamaindex_types(self) -> tuple[Callable[..., Any], Any, Any, Callable[..., Any]]:
        """解析 LlamaIndex 类型。

        这里故意使用动态 import，避免在没有安装 llama-index 的环境中导入模块就
        报错。只有真正选择 ``RAG_QUERY_BACKEND=llamaindex`` 并执行查询时才需要
        依赖存在。
        """
        if (
            self._document_factory is not None
            and self._index_factory is not None
            and self._storage_context_factory is not None
            and self._load_index_func is not None
        ):
            return (
                self._document_factory,
                self._index_factory,
                self._storage_context_factory,
                self._load_index_func,
            )

        try:
            from llama_index.core import (
                Document,
                Settings,
                StorageContext,
                VectorStoreIndex,
                load_index_from_storage,
            )
        except ImportError as exc:
            raise RuntimeError(
                "llama-index is not installed; run backend dependency install first"
            ) from exc

        configure_llamaindex_settings(Settings)
        return Document, VectorStoreIndex, StorageContext, load_index_from_storage

    def _to_llama_document(
        self,
        document_factory: Callable[..., Any],
        document: RagDocument,
    ) -> Any:
        """把内部 RagDocument 转成 LlamaIndex Document。"""
        return document_factory(
            text=document.text,
            metadata=document.metadata,
        )

    def _source_refs_from_response(
        self,
        response: Any,
        *,
        limit: int,
    ) -> list[RagSourceRef]:
        """从 LlamaIndex response.source_nodes 中提取来源引用。

        LlamaIndex 不同版本的 source node 包装层略有差异：有的直接暴露
        ``node.metadata``，有的通过 ``source_node.node.metadata``。这里做防御式
        读取，尽量兼容版本差异和测试 fake。
        """
        source_nodes = getattr(response, "source_nodes", []) or []
        return self._source_refs_from_nodes(source_nodes, limit=limit)

    def _retrieve_source_nodes(
        self,
        index: Any,
        prompt: str,
        *,
        source_limit: int,
    ) -> list[Any] | None:
        """Prefer LlamaIndex retriever output instead of its default LLM answer."""
        as_retriever = getattr(index, "as_retriever", None)
        if not callable(as_retriever):
            return None

        retriever = as_retriever(similarity_top_k=source_limit)
        retrieve = getattr(retriever, "retrieve", None)
        if not callable(retrieve):
            return None

        return list(retrieve(prompt) or [])

    def _source_refs_from_nodes(
        self,
        source_nodes: list[Any],
        *,
        limit: int,
    ) -> list[RagSourceRef]:
        """从 LlamaIndex source nodes 中提取 EDU-Mate 来源引用。"""
        refs: list[RagSourceRef] = []

        for source_node in source_nodes[:limit]:
            node = getattr(source_node, "node", source_node)
            metadata = getattr(node, "metadata", {}) or {}
            if not isinstance(metadata, dict):
                continue

            source_type = str(metadata.get("type", "timeline"))
            source_id = str(metadata.get("source_id", "unknown"))
            ts = metadata.get("ts")
            refs.append(
                RagSourceRef(
                    type=source_type,
                    id=source_id,
                    ts=ts if isinstance(ts, int | float) else None,
                    text=compact_source_ref_text(
                        self._node_text(node),
                        metadata=metadata,
                    ),
                )
            )

        return refs

    def _answer_from_refs(self, refs: list[RagSourceRef]) -> str:
        """Build a source-only answer from retrieved vector hits."""
        return "我在课堂向量索引中找到这些相关内容：\n" + "\n".join(
            f"- {ref.text}" for ref in refs[:MAX_SOURCE_REF_COUNT]
        )

    def _node_text(self, node: Any) -> str:
        """兼容不同 LlamaIndex 节点对象的正文读取方式。"""
        get_content = getattr(node, "get_content", None)
        if callable(get_content):
            content = get_content()
            if isinstance(content, str) and content:
                return content

        text = getattr(node, "text", None)
        if isinstance(text, str) and text:
            return text

        return ""

    def _session_id_from_documents(self, documents: list[RagDocument]) -> str | None:
        """从文档元数据中解析 session_id。

        正常情况下，一次查询只会传入同一节课的文档；如果列表为空或元数据缺失，
        返回 None，调用方会退回临时索引或抛出更清楚的错误。
        """
        for document in documents:
            session_id = document.metadata.get("session_id")
            if isinstance(session_id, str) and session_id:
                return session_id
        return None

    def _persisted_index_exists(self, index_dir: Path) -> bool:
        """判断本地索引目录是否已经有可尝试加载的文件。"""
        return index_dir.exists() and index_dir.is_dir() and any(index_dir.iterdir())


__all__ = ["LlamaIndexQueryService"]
