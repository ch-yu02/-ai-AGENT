"""知识图谱模型 —— 定义课堂知识图谱的节点、边、树结构和增量更新。

EDU-Mate 的核心功能之一：在课堂进行过程中，端侧 SLM 实时从
语音和画面中提取知识点，构建一个不断生长的**知识图谱**，以
树/图结构组织课堂内容，帮助学生在课后快速回顾和导航。

数据流：
  SLM 提取 → KnowledgeEntity + KnowledgeRelation (events.py)
          → KnowledgeNode + KnowledgeEdge (知识图谱层)
          → KnowledgeTree (完整快照，用于前端渲染/持久化)
          → GraphPatch (增量更新，实时推送给前端)
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import SourceRef, utc_now_iso
from .events import KnowledgeEntity, KnowledgeRelation


# ── 知识图谱基础节点与边 ────────────────────────────────────────

class KnowledgeNode(BaseModel):
    """知识图谱中的一个节点，代表一个独立的知识概念。

    与 events.KnowledgeEntity 的区别：KnowledgeEntity 是 SLM
    一次提取的原始结果，KnowledgeNode 是经过合并、去重后进入
    知识图谱的正式节点，带有层级（level）和溯源引用（source_refs）。

    Attributes:
        node_id:     节点唯一标识
        label:       节点显示标签
        type:        节点类型（concept / formula / person 等）
        summary:     节点摘要/定义
        level:       在知识树中的层级深度（0 为根节点）
        importance:  重要度评分（0~1）
        source_refs: 溯源引用列表，指向原始课堂素材
    """

    node_id: str
    """节点唯一标识（UUID）。"""
    label: str
    """节点显示标签（如 '牛顿第二定律'）。"""
    type: str = "concept"
    """节点类型，与 KnowledgeEntity.type 含义一致。"""
    summary: str | None = None
    """节点摘要或详细描述。"""
    level: int | None = None
    """在知识树中的层级深度（0 = 根节点）。"""
    importance: float | None = None
    """节点重要度评分（0~1），用于前端视觉权重。"""
    source_refs: list[SourceRef] = Field(default_factory=list)
    """溯源引用，指向产生该节点的原始事件。"""


class KnowledgeEdge(BaseModel):
    """知识图谱中两个节点之间的有向关系。

    与 events.KnowledgeRelation 的区别：KnowledgeRelation 是
    SLM 一次提取的原始关系，KnowledgeEdge 是经过验证和合并后
    进入知识图谱的正式关系，带有溯源引用。

    Attributes:
        edge_id:    边唯一标识
        source:     起点节点 ID
        target:     终点节点 ID
        relation:   关系类型标签
        source_refs: 溯源引用列表
    """

    edge_id: str
    """边唯一标识（UUID）。"""
    source: str
    """起点节点 ID（对应 KnowledgeNode.node_id）。"""
    target: str
    """终点节点 ID。"""
    relation: str
    """关系类型（如 'belongs_to' / 'derives_from' / 'example_of'）。"""
    source_refs: list[SourceRef] = Field(default_factory=list)
    """溯源引用，指向产生该关系的原始事件。"""


# ── 知识图谱完整的图结构 ────────────────────────────────────────

class KnowledgeTree(BaseModel):
    """知识图谱的完整快照，用于前端渲染和持久化存储。

    一份 KnowledgeTree 对应一个课堂会话的知识图，包含节点列表、
    边列表和根节点索引。随着课堂进行，KnowledgeTree.version 不断
    递增，前端可以通过 GraphPatch 增量同步。

    Attributes:
        session_id: 所属会话 ID
        version:    当前版本号（每次变更递增）
        root_nodes: 根节点 ID 列表（顶层概念，用于树状展示）
        nodes:      所有知识节点
        edges:      所有知识边
        updated_at: 最后更新时间
    """

    session_id: str
    """所属课堂会话 ID。"""
    version: int = 0
    """知识图谱版本号，每次修改递增。"""
    root_nodes: list[str] = Field(default_factory=list)
    """根节点 ID 列表（层级为 0 的顶层节点）。"""
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    """所有知识节点。"""
    edges: list[KnowledgeEdge] = Field(default_factory=list)
    """所有知识边。"""
    updated_at: str = Field(default_factory=utc_now_iso)
    """此快照的最后更新时间。"""


# ── 增量更新机制 ────────────────────────────────────────────────

GraphOperationType = Literal["add_node", "update_node", "add_edge", "remove_node", "remove_edge"]
"""知识图谱变更操作类型。

- ``"add_node"``    —— 新增节点
- ``"update_node"`` —— 更新已有节点
- ``"add_edge"``    —— 新增边
- ``"remove_node"`` —— 删除节点（同时删除相关边）
- ``"remove_edge"`` —— 删除边
"""


class GraphPatchOperation(BaseModel):
    """一条增量图操作，推送给前端按顺序应用。

    每条操作记录一个原子变更，前端按照 operations 数组的顺序
    依次应用到本地的知识图谱快照上。

    Attributes:
        op:   操作类型
        node: 操作涉及的节点（add_node / update_node 时必须）
        edge: 操作涉及的边（add_edge / remove_edge 时必须）
        data: 附加数据（如 update_node 时的增量修改字段）
    """

    op: GraphOperationType
    """变更操作类型。"""
    node: KnowledgeNode | None = None
    """操作的节点对象（add_node / update_node 时必填）。"""
    edge: KnowledgeEdge | None = None
    """操作的边对象（add_edge / remove_edge 时必填）。"""
    data: dict[str, Any] = Field(default_factory=dict)
    """附加数据（update_node 时用于传送部分更新的字段）。"""


class GraphPatch(BaseModel):
    """两个版本之间的增量更新包。

    当知识图谱发生变化时，后端生成一个 GraphPatch 描述从
    from_version 到 to_version 的变更序列，推送给前端。
    而不是每次都传输完整的 KnowledgeTree。

    Attributes:
        session_id:  所属会话 ID
        from_version: 起始版本号
        to_version:   目标版本号
        operations:   变更操作列表（前端按序执行）
    """

    session_id: str
    """所属课堂会话 ID。"""
    from_version: int
    """起始版本号（前端当前的版本）。"""
    to_version: int
    """目标版本号（变更后的版本）。"""
    operations: list[GraphPatchOperation] = Field(default_factory=list)
    """按序应用的变更操作列表。"""


__all__ = [
    "GraphPatch",
    "GraphPatchOperation",
    "KnowledgeEdge",
    "KnowledgeEntity",
    "KnowledgeNode",
    "KnowledgeRelation",
    "KnowledgeTree",
]
