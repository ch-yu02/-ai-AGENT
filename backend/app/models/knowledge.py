from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import SourceRef, utc_now_iso
from .events import KnowledgeEntity, KnowledgeRelation


class KnowledgeNode(BaseModel):
    """Node in the live classroom knowledge tree."""

    node_id: str
    label: str
    type: str = "concept"
    summary: str | None = None
    level: int | None = None
    importance: float | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)


class KnowledgeEdge(BaseModel):
    """Directed relationship between two knowledge nodes."""

    edge_id: str
    source: str
    target: str
    relation: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class KnowledgeTree(BaseModel):
    """Complete graph snapshot suitable for frontend rendering and storage."""

    session_id: str
    version: int = 0
    root_nodes: list[str] = Field(default_factory=list)
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)


GraphOperationType = Literal["add_node", "update_node", "add_edge", "remove_node", "remove_edge"]


class GraphPatchOperation(BaseModel):
    """One incremental graph operation pushed to the frontend."""

    op: GraphOperationType
    node: KnowledgeNode | None = None
    edge: KnowledgeEdge | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class GraphPatch(BaseModel):
    """Incremental graph update between two knowledge tree versions."""

    session_id: str
    from_version: int
    to_version: int
    operations: list[GraphPatchOperation] = Field(default_factory=list)


__all__ = [
    "GraphPatch",
    "GraphPatchOperation",
    "KnowledgeEdge",
    "KnowledgeEntity",
    "KnowledgeNode",
    "KnowledgeRelation",
    "KnowledgeTree",
]
