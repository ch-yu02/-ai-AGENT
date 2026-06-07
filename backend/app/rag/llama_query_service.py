"""可选 LlamaIndex 单节课查询服务。

这个模块实现 Phase 6 的第一步：把当前 ``RagDocument`` 临时转换成
``llama_index.core.Document``，构建单节课内存索引，然后执行查询并把来源节点
映射回 EDU-Mate 的 ``RagSourceRef``。

设计约束：
- ``llama-index`` 不是当前项目的硬依赖。未安装时，本服务会回退到词法检索。
- 不在这里保存索引。持久化到 ``data/sessions/{session_id}/llama_index/`` 是
  下一阶段，可以在本类稳定后继续扩展。
- 不让 Agent/Frontend 直接接触 LlamaIndex 类型，避免框架替换影响 API 契约。
"""

from typing import Any, Callable

from .documents import RagDocument
from .query_service import QueryResult, QueryService, RagSourceRef


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
    ) -> None:
        self.fallback = fallback or QueryService()
        self._document_factory = document_factory
        self._index_factory = index_factory

    def query(
        self,
        prompt: str,
        documents: list[RagDocument],
        limit: int = 5,
    ) -> QueryResult:
        """使用 LlamaIndex 查询课堂文档。

        流程：
        1. 把内部 ``RagDocument`` 转成 LlamaIndex Document。
        2. 用 ``VectorStoreIndex.from_documents`` 构建本次查询的临时内存索引。
        3. 调用 query engine。
        4. 从 source_nodes 中恢复 EDU-Mate 来源引用。

        任一环节失败都会回退到词法检索，并把失败原因放入 warning。这样开发者
        可以在未安装依赖时继续跑完整测试，也不会让用户的问题请求直接失败。
        """
        if not documents:
            return self.fallback.query(prompt, documents, limit=limit)

        try:
            document_factory, index_factory = self._resolve_llamaindex_types()
            llama_documents = [
                self._to_llama_document(document_factory, document)
                for document in documents
            ]
            index = index_factory.from_documents(llama_documents)
            query_engine = index.as_query_engine(similarity_top_k=limit)
            response = query_engine.query(prompt)
            refs = self._source_refs_from_response(response, limit=limit)

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

    def _resolve_llamaindex_types(self) -> tuple[Callable[..., Any], Any]:
        """解析 LlamaIndex 类型。

        这里故意使用动态 import，避免在没有安装 llama-index 的环境中导入模块就
        报错。只有真正选择 ``RAG_QUERY_BACKEND=llamaindex`` 并执行查询时才需要
        依赖存在。
        """
        if self._document_factory is not None and self._index_factory is not None:
            return self._document_factory, self._index_factory

        try:
            from llama_index.core import Document, VectorStoreIndex
        except ImportError as exc:
            raise RuntimeError(
                "llama-index is not installed; run backend dependency install first"
            ) from exc

        return Document, VectorStoreIndex

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
                    text=self._node_text(node),
                )
            )

        return refs

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


__all__ = ["LlamaIndexQueryService"]
