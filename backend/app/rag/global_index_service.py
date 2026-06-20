"""可选的跨课堂 LlamaIndex 全局索引服务。

本模块补齐“真实全局向量索引”的主链路，但仍然遵守项目的轻依赖原则：

- 默认搜索路径不会导入或要求安装 ``llama-index``。
- 只有显式把 ``GLOBAL_SEARCH_BACKEND=llamaindex`` 时，跨课堂搜索才会尝试
  使用这里的服务。
- 索引构建、加载或查询任一步失败时，调用方会回退到已有词法搜索。

全局索引目录复用 storage 层提供的 ``data/indexes/global``，其中：

```text
data/indexes/global/documents.json      # 可审计的文档快照
data/indexes/global/manifest.json       # 判断索引是否需要重建的指纹
data/indexes/global/llama_index/        # LlamaIndex 实际持久化目录
```
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .documents import RagDocument
from .llama_metadata import compact_llama_metadata
from .llama_settings import configure_llamaindex_settings


@dataclass(frozen=True)
class GlobalIndexHit:
    """全局向量索引返回的一条命中。

    该模型只在 RAG 层内部使用。Agent API 层会再转换为
    ``GlobalSearchHit``，从而避免前端依赖 LlamaIndex 的任何字段。
    """

    score: int
    session_id: str
    title: str
    course: str | None
    source_type: str
    source_id: str
    ts: float | None
    text: str


class GlobalLlamaIndexService:
    """跨课堂 LlamaIndex 索引的构建、加载和查询入口。"""

    def __init__(
        self,
        *,
        index_root: Path,
        document_factory: Callable[..., Any] | None = None,
        index_factory: Any | None = None,
        storage_context_factory: Any | None = None,
        load_index_func: Callable[..., Any] | None = None,
    ) -> None:
        self.index_root = index_root
        self.index_dir = index_root / "llama_index"
        self.manifest_path = index_root / "manifest.json"
        self._document_factory = document_factory
        self._index_factory = index_factory
        self._storage_context_factory = storage_context_factory
        self._load_index_func = load_index_func

    def search(
        self,
        *,
        query: str,
        records: list[dict],
        documents: list[RagDocument],
        limit: int,
    ) -> list[GlobalIndexHit]:
        """查询全局索引。

        ``records`` 是写入 ``documents.json`` 的可审计快照，``documents`` 是
        构建 LlamaIndex 需要的内部文档对象。两者都由 ``GlobalSearchService``
        基于当前历史课堂实时生成，因此历史删除后下一次搜索会自然触发索引重建。
        """
        if not documents:
            return []

        self.index_root.mkdir(parents=True, exist_ok=True)
        manifest = self._manifest(records)
        index = self._load_or_rebuild_index(documents, manifest)
        source_nodes = self._retrieve_source_nodes(index, query, limit=limit)
        if source_nodes is not None:
            return self._hits_from_source_nodes(source_nodes, limit=limit)

        query_engine = index.as_query_engine(similarity_top_k=limit)
        response = query_engine.query(query)
        return self._hits_from_response(response, limit=limit)

    def rebuild(
        self,
        *,
        records: list[dict],
        documents: list[RagDocument],
    ) -> dict[str, Any]:
        """Force rebuilding the persisted global LlamaIndex.

        Search already rebuilds lazily when the manifest changes, but a manual
        command is useful before demos or after changing embedding/provider
        settings. This method intentionally requires the caller to provide both
        the auditable JSON records and the RAG documents so storage/search code
        remains the only place that knows how to read saved sessions.
        """
        self.index_root.mkdir(parents=True, exist_ok=True)
        manifest = self._manifest(records)
        if self.index_dir.exists():
            shutil.rmtree(self.index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        index = self._build_index(documents)
        storage_context = getattr(index, "storage_context", None)
        persist = getattr(storage_context, "persist", None)
        if not callable(persist):
            raise RuntimeError("LlamaIndex index does not expose storage_context.persist")
        persist(persist_dir=str(self.index_dir))
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest

    def _load_or_rebuild_index(
        self,
        documents: list[RagDocument],
        manifest: dict[str, Any],
    ) -> Any:
        """根据 manifest 判断复用旧索引还是重建。

        manifest 使用当前文档快照的 hash。只要历史课堂数量、正文或来源元数据有
        变化，hash 就会变化，从而重建索引。这样删除历史课堂后不会继续命中过期
        session。
        """
        if self._is_manifest_current(manifest) and self._persisted_index_exists():
            return self._load_index()

        if self.index_dir.exists():
            shutil.rmtree(self.index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        index = self._build_index(documents)
        storage_context = getattr(index, "storage_context", None)
        persist = getattr(storage_context, "persist", None)
        if not callable(persist):
            raise RuntimeError("LlamaIndex index does not expose storage_context.persist")

        persist(persist_dir=str(self.index_dir))
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return index

    def _build_index(self, documents: list[RagDocument]) -> Any:
        """把内部 RAG 文档转换为 LlamaIndex Document 并构建向量索引。"""
        document_factory, index_factory, _, _ = self._resolve_llamaindex_types()
        llama_documents = [
            document_factory(
                text=document.text,
                metadata=compact_llama_metadata(document.metadata),
            )
            for document in documents
        ]
        return index_factory.from_documents(llama_documents)

    def _load_index(self) -> Any:
        """从 ``data/indexes/global/llama_index`` 加载已持久化索引。"""
        _, _, storage_context_factory, load_index_func = self._resolve_llamaindex_types()
        storage_context = storage_context_factory.from_defaults(
            persist_dir=str(self.index_dir)
        )
        return load_index_func(storage_context)

    def _resolve_llamaindex_types(
        self,
    ) -> tuple[Callable[..., Any], Any, Any, Callable[..., Any]]:
        """动态解析 LlamaIndex 类型，避免默认导入阶段要求可选依赖。"""
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
                "llama-index is not installed; keep GLOBAL_SEARCH_BACKEND=lexical "
                "or install optional LlamaIndex dependencies"
            ) from exc

        configure_llamaindex_settings(Settings)
        return Document, VectorStoreIndex, StorageContext, load_index_from_storage

    def _hits_from_response(self, response: Any, *, limit: int) -> list[GlobalIndexHit]:
        """从 LlamaIndex response.source_nodes 恢复全局搜索命中。

        LlamaIndex 的 source node 在不同版本中包装方式不同，可能是
        ``source_node.node.metadata``，也可能直接是 ``source_node.metadata``。
        这里做宽容读取，并把缺失字段回退到稳定默认值。
        """
        source_nodes = getattr(response, "source_nodes", []) or []
        return self._hits_from_source_nodes(source_nodes, limit=limit)

    def _retrieve_source_nodes(
        self,
        index: Any,
        query: str,
        *,
        limit: int,
    ) -> list[Any] | None:
        """Prefer vector retrieval over LlamaIndex's default query-engine LLM."""
        as_retriever = getattr(index, "as_retriever", None)
        if not callable(as_retriever):
            return None

        retriever = as_retriever(similarity_top_k=limit)
        retrieve = getattr(retriever, "retrieve", None)
        if not callable(retrieve):
            return None

        return list(retrieve(query) or [])

    def _hits_from_source_nodes(
        self,
        source_nodes: list[Any],
        *,
        limit: int,
    ) -> list[GlobalIndexHit]:
        """从 LlamaIndex source nodes 恢复全局搜索命中。"""
        hits: list[GlobalIndexHit] = []

        for source_node in source_nodes[:limit]:
            node = getattr(source_node, "node", source_node)
            metadata = getattr(node, "metadata", {}) or {}
            if not isinstance(metadata, dict):
                continue

            session_id = str(metadata.get("session_id", ""))
            if not session_id:
                continue

            ts = metadata.get("ts")
            raw_score = getattr(source_node, "score", None)
            hits.append(
                GlobalIndexHit(
                    score=self._normalize_score(raw_score),
                    session_id=session_id,
                    title=str(metadata.get("title", "未命名课堂")),
                    course=(
                        str(metadata["course"])
                        if metadata.get("course") is not None
                        else None
                    ),
                    source_type=str(metadata.get("type", "timeline")),
                    source_id=str(metadata.get("source_id", "unknown")),
                    ts=ts if isinstance(ts, int | float) else None,
                    text=self._node_text(node),
                )
            )

        return hits

    def _manifest(self, records: list[dict]) -> dict[str, Any]:
        """生成当前全局文档快照的稳定指纹。"""
        encoded = json.dumps(records, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return {
            "version": 1,
            "document_count": len(records),
            "fingerprint": hashlib.sha256(encoded).hexdigest(),
        }

    def _is_manifest_current(self, expected: dict[str, Any]) -> bool:
        """判断磁盘 manifest 是否与当前文档快照一致。"""
        if not self.manifest_path.exists():
            return False
        try:
            current = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return current == expected

    def _persisted_index_exists(self) -> bool:
        """判断全局 LlamaIndex 目录是否已有可尝试加载的文件。"""
        return self.index_dir.exists() and self.index_dir.is_dir() and any(
            self.index_dir.iterdir()
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

    def _normalize_score(self, raw_score: object) -> int:
        """把 LlamaIndex 的相似度分数转成前端已有的整数 score 字段。"""
        if isinstance(raw_score, int | float):
            return max(1, int(float(raw_score) * 1000))
        return 1


__all__ = ["GlobalIndexHit", "GlobalLlamaIndexService", "compact_llama_metadata"]
