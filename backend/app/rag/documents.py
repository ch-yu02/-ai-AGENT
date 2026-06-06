"""Convert classroom artifacts into retrievable RAG documents.

Phase 3 的最终目标是接入 LlamaIndex。为了避免一上来引入重依赖和外部模型，
这里先定义一个轻量 ``RagDocument``，把 EDU-Mate 已有的课堂模型转换成
“文本 + metadata”的通用形态。

后续迁移到 LlamaIndex 时，``RagDocument`` 可以一一映射到
``llama_index.core.Document``：

    text     -> Document.text
    metadata -> Document.metadata

这样 Agent / QueryService 的上层契约可以先稳定下来，底层索引实现再替换。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.models import ClassroomContext, KnowledgeEdge, KnowledgeNode, KnowledgeTree


RagDocumentType = Literal[
    "segment",
    "visual",
    "knowledge_node",
    "knowledge_edge",
]
"""可检索文档类型，对应课堂资料中的四类主要来源。"""


class RagDocument(BaseModel):
    """A small, provider-neutral document for classroom retrieval."""

    text: str
    """参与检索和回答的正文。"""
    metadata: dict[str, Any] = Field(default_factory=dict)
    """来源信息。至少包含 session_id/type/source_id，可能包含 ts。"""


def build_session_documents(
    context: ClassroomContext,
    knowledge_graph: KnowledgeTree,
) -> list[RagDocument]:
    """Build all retrievable documents for one classroom session.

    输入保持为 Agent 已经统一好的 ``ClassroomContext`` 和 ``KnowledgeTree``。
    这意味着它同时支持内存课堂和历史课堂，不需要关心数据来自 manager 还是
    LocalStorage。
    """
    documents: list[RagDocument] = []
    documents.extend(_transcript_documents(context))
    documents.extend(_visual_documents(context))
    documents.extend(_knowledge_node_documents(knowledge_graph))
    documents.extend(_knowledge_edge_documents(knowledge_graph))
    return documents


def _transcript_documents(context: ClassroomContext) -> list[RagDocument]:
    documents: list[RagDocument] = []
    for segment in context.transcript:
        text = f"[{segment.start_ts:.2f}s-{segment.end_ts:.2f}s] {segment.text}"
        documents.append(
            _document(
                session_id=context.session_id,
                source_type="segment",
                source_id=segment.segment_id,
                text=text,
                ts=segment.start_ts,
                extra={
                    "end_ts": segment.end_ts,
                    "speaker": segment.speaker,
                },
            )
        )
    return documents


def _visual_documents(context: ClassroomContext) -> list[RagDocument]:
    documents: list[RagDocument] = []
    for visual in context.visuals:
        parts: list[str] = [f"[{visual.capture_ts:.2f}s]"]
        if visual.ocr_text:
            parts.append(f"OCR: {visual.ocr_text}")
        if visual.caption:
            parts.append(f"Caption: {visual.caption}")
        if len(parts) == 1:
            parts.append(visual.image_type or visual.image_path)

        documents.append(
            _document(
                session_id=context.session_id,
                source_type="visual",
                source_id=visual.image_id,
                text=" ".join(parts),
                ts=visual.capture_ts,
                extra={
                    "image_path": visual.image_path,
                    "image_type": visual.image_type,
                },
            )
        )
    return documents


def _knowledge_node_documents(knowledge_graph: KnowledgeTree) -> list[RagDocument]:
    documents: list[RagDocument] = []
    for node in knowledge_graph.nodes:
        summary = f"。说明：{node.summary}" if node.summary else ""
        documents.append(
            _document(
                session_id=knowledge_graph.session_id,
                source_type="knowledge_node",
                source_id=node.node_id,
                text=f"知识点：{node.label}{summary}。",
                ts=_first_source_ts(node),
                extra={
                    "label": node.label,
                    "node_type": node.type,
                    "importance": node.importance,
                },
            )
        )
    return documents


def _knowledge_edge_documents(knowledge_graph: KnowledgeTree) -> list[RagDocument]:
    nodes_by_id = {node.node_id: node for node in knowledge_graph.nodes}
    documents: list[RagDocument] = []

    for edge in knowledge_graph.edges:
        source_label = _node_label(nodes_by_id, edge.source)
        target_label = _node_label(nodes_by_id, edge.target)
        documents.append(
            _document(
                session_id=knowledge_graph.session_id,
                source_type="knowledge_edge",
                source_id=edge.edge_id,
                text=f"知识关系：{source_label} --{edge.relation}--> {target_label}。",
                ts=_first_source_ts(edge),
                extra={
                    "source": edge.source,
                    "target": edge.target,
                    "relation": edge.relation,
                },
            )
        )
    return documents


def _document(
    session_id: str,
    source_type: RagDocumentType,
    source_id: str,
    text: str,
    ts: float | None = None,
    extra: dict[str, Any] | None = None,
) -> RagDocument:
    metadata = {
        "session_id": session_id,
        "type": source_type,
        "source_id": source_id,
    }
    if ts is not None:
        metadata["ts"] = ts
    if extra:
        metadata.update({key: value for key, value in extra.items() if value is not None})
    return RagDocument(text=text, metadata=metadata)


def _first_source_ts(item: KnowledgeNode | KnowledgeEdge) -> float | None:
    for ref in item.source_refs:
        if ref.ts is not None:
            return ref.ts
    return None


def _node_label(nodes_by_id: dict[str, KnowledgeNode], node_id: str) -> str:
    node = nodes_by_id.get(node_id)
    return node.label if node is not None else node_id


__all__ = ["RagDocument", "RagDocumentType", "build_session_documents"]
