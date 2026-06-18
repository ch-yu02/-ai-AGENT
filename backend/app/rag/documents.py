"""把课堂产物转换成可检索的 RAG 文档。

Phase 3 的最终目标是接入 LlamaIndex。为了避免一上来引入重依赖和外部模型，
这里先定义一个轻量 ``RagDocument``，把 EDU-Mate 已有的课堂模型转换成
“文本 + 元数据”的通用形态。

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
    "structured_note",
    "visual",
    "knowledge_node",
    "knowledge_edge",
]
"""可检索文档类型，对应课堂资料中的四类主要来源。"""


class RagDocument(BaseModel):
    """面向课堂检索的轻量文档模型，不绑定具体 RAG/向量库供应方。

    当前项目暂不直接暴露 LlamaIndex 的 Document 类型，而是先用这个模型
    稳定内部契约。这样做的好处是：测试不需要安装 LlamaIndex；未来接入
    真正索引时，只要在边界处做一次模型转换。
    """

    text: str
    """参与检索和回答的正文。"""
    metadata: dict[str, Any] = Field(default_factory=dict)
    """来源信息。至少包含 session_id/type/source_id，可能包含 ts。"""


def build_session_documents(
    context: ClassroomContext,
    knowledge_graph: KnowledgeTree,
    structured_notes_markdown: str | None = None,
) -> list[RagDocument]:
    """构建一节课堂的全部可检索文档。

    输入保持为 Agent 已经统一好的 ``ClassroomContext`` 和 ``KnowledgeTree``。
    这意味着它同时支持内存课堂和历史课堂，不需要关心数据来自 manager 还是
    LocalStorage。

    转换顺序保持稳定：字幕 → 视觉内容 → 知识节点 → 知识关系。稳定顺序能让
    单元测试更可靠，也便于后续排查检索结果为什么排在某个位置。
    """
    documents: list[RagDocument] = []
    documents.extend(_transcript_documents(context))
    if structured_notes_markdown and structured_notes_markdown.strip():
        documents.append(_structured_notes_document(context, structured_notes_markdown))
    documents.extend(_visual_documents(context))
    documents.extend(_knowledge_node_documents(knowledge_graph))
    documents.extend(_knowledge_edge_documents(knowledge_graph))
    return documents


def _transcript_documents(context: ClassroomContext) -> list[RagDocument]:
    """把 ASR 字幕片段转换成检索文档。

    字幕是课堂 QA 最常用的来源，因此文档正文里保留起止时间，元数据里
    同时保留 ``segment_id``、开始时间、结束时间和 speaker。未来前端可以用
    这些字段跳转到历史回放中的具体片段。
    """
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


def _structured_notes_document(
    context: ClassroomContext,
    structured_notes_markdown: str,
) -> RagDocument:
    """把 Qwen 结构化课堂笔记转换成检索文档。

    这份文档比原始字幕更适合回答“这节课重点是什么、知识主线是什么”这类
    课后问题。原始字幕仍保留为独立 segment 文档，便于追溯细节。
    """
    first_ts = context.transcript[0].start_ts if context.transcript else None
    return _document(
        session_id=context.session_id,
        source_type="structured_note",
        source_id="structured_notes",
        text=f"结构化课堂笔记：\n{structured_notes_markdown}",
        ts=first_ts,
    )


def _visual_documents(context: ClassroomContext) -> list[RagDocument]:
    """把课堂视觉内容转换成检索文档。

    视觉事件可能包含 OCR、caption，也可能只有图片路径或类型。检索正文优先
    使用 OCR 和 caption；如果两者都没有，再退回 image_type / image_path，
    保证每个视觉事件至少能形成一个可追溯文档。
    """
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
    """把知识图谱节点转换成检索文档。

    节点文档用于回答“某个概念是什么”这类问题。元数据中保留 label、
    node_type、importance，后续可以作为排序、过滤或前端展示依据。
    """
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
    """把知识图谱边转换成检索文档。

    边文档用于回答“两个知识点之间有什么关系”。正文使用可读的节点标签；
    元数据仍保留 source/target 节点 ID，方便未来跳回图谱视图。
    """
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
    """统一创建 RagDocument，并过滤元数据中的空值。

    各类来源都会落到相同的元数据形态：
    - ``session_id``：所属课堂。
    - ``type``：来源类型。
    - ``source_id``：原始对象 ID。
    - ``ts``：可选课堂内时间。

    其他额外字段由调用方通过 ``extra`` 传入。
    """
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
    """从知识节点/边的 source_refs 中取第一个可用时间戳。"""
    for ref in item.source_refs:
        if ref.ts is not None:
            return ref.ts
    return None


def _node_label(nodes_by_id: dict[str, KnowledgeNode], node_id: str) -> str:
    """根据节点 ID 取显示标签；找不到节点时退回原始 ID。"""
    node = nodes_by_id.get(node_id)
    return node.label if node is not None else node_id


__all__ = ["RagDocument", "RagDocumentType", "build_session_documents"]
