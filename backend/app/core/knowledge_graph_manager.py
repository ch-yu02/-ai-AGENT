"""知识图谱管理器。

KnowledgeGraphManager 负责把 ContextManager 中保存的
``KnowledgeExtraction`` 转成课堂知识图谱：

  KnowledgeExtraction.entities  -> KnowledgeNode
  KnowledgeExtraction.relations -> KnowledgeEdge
  KnowledgeTree                 -> 完整图谱快照
  GraphPatch                    -> 推送给前端的增量更新

职责边界
--------
- 不负责 ASR/OCR 原始事件解析：这由 ContextManager 完成。
- 不负责 WebSocket 发送：API 路由拿到 GraphPatch 后交给
  ConnectionManager 广播。
- 不负责持久化：课堂结束时 Storage 模块读取 KnowledgeTree 写入
  ``knowledge_graph.json``。

MVP 合并策略
------------
当前节点去重采用“实体名规范化”：
  - 去掉首尾空白
  - 转小写

这能解决“傅里叶变换”被重复提取的问题。后续如需支持别名合并
（如 FFT / 快速傅里叶变换），可以把 ``_normalize_label`` 替换成
别名表或 embedding 相似度匹配。
"""

import re
from collections import deque
from difflib import SequenceMatcher

from backend.app.knowledge_quality import (
    is_low_value_entity_name,
    strip_generic_entity_affixes,
)
from backend.app.models import (
    GraphPatch,
    GraphPatchOperation,
    KnowledgeEdge,
    KnowledgeEntity,
    KnowledgeExtraction,
    KnowledgeNode,
    KnowledgeRelation,
    KnowledgeTree,
    RealtimeEvent,
    SourceRef,
    utc_now_iso,
)


class KnowledgeGraphNotFoundError(Exception):
    """Raised when a graph operation references an unknown session."""


class KnowledgeGraphEventError(Exception):
    """Raised when a realtime event is not a valid graph update event."""


class KnowledgeGraphManager:
    """Maintains one live knowledge graph per classroom session."""

    MAX_NODE_SOURCE_REFS = 3
    MAX_EDGE_SOURCE_REFS = 2

    def __init__(self) -> None:
        self._graphs: dict[str, KnowledgeTree] = {}
        # _node_index maps normalized entity labels to node_id. It lets the
        # manager merge repeated mentions into the same KnowledgeNode.
        self._node_index: dict[str, dict[str, str]] = {}

    # ── 生命周期 ─────────────────────────────────────────────

    def start_session(self, session_id: str) -> KnowledgeTree:
        """Create or reset the knowledge graph for a new classroom session."""
        graph = KnowledgeTree(session_id=session_id)
        self._graphs[session_id] = graph
        self._node_index[session_id] = {}
        return graph

    def get_graph(self, session_id: str) -> KnowledgeTree:
        """Return the current graph snapshot for a session."""
        graph = self._graphs.get(session_id)
        if graph is None:
            raise KnowledgeGraphNotFoundError(f"Knowledge graph not found: {session_id}")
        return graph

    def clear(self) -> None:
        """Clear all in-memory graphs for tests and local demo restarts."""
        self._graphs.clear()
        self._node_index.clear()

    # ── 事件入口 ─────────────────────────────────────────────

    def handle_event(self, event: RealtimeEvent) -> GraphPatch | None:
        """Apply a realtime event to the knowledge graph when applicable.

        只有 ``knowledge.extraction`` 会修改图谱。字幕和图片事件只进入
        ContextManager，因此这里返回 None，API 路由可以据此跳过图谱推送。
        """
        if event.event_type != "knowledge.extraction":
            return None

        try:
            extraction = KnowledgeExtraction.model_validate(
                {
                    "extraction_id": event.payload.get("extraction_id", ""),
                    "session_id": event.payload.get("session_id", event.session_id),
                    **event.payload,
                }
            )
        except Exception as exc:
            raise KnowledgeGraphEventError(
                f"Invalid knowledge.extraction payload: {exc}"
            ) from exc

        return self.apply_extraction(extraction)

    def apply_extraction(self, extraction: KnowledgeExtraction) -> GraphPatch:
        """Merge one structured extraction result into the graph.

        返回值是本次变更的 GraphPatch。前端可将 patch 应用到本地图谱；
        Storage 模块则读取完整 KnowledgeTree 保存。
        """
        graph = self.get_graph(extraction.session_id)
        from_version = graph.version
        operations: list[GraphPatchOperation] = []
        refs = self._source_refs(extraction)

        for entity in extraction.entities:
            operation = self._upsert_node(graph, entity, extraction.importance, refs)
            if operation is not None:
                operations.append(operation)

        for relation in extraction.relations:
            operations.extend(self._upsert_edge(graph, relation, refs))

        if operations:
            graph.version += 1
            graph.updated_at = utc_now_iso()
            self._recompute_roots(graph)

        return GraphPatch(
            session_id=extraction.session_id,
            from_version=from_version,
            to_version=graph.version,
            operations=operations,
        )

    # ── 节点处理 ─────────────────────────────────────────────

    def _upsert_node(
        self,
        graph: KnowledgeTree,
        entity: KnowledgeEntity,
        importance: float | None,
        refs: list[SourceRef],
    ) -> GraphPatchOperation | None:
        """Insert a new node or enrich an existing node.

        如果实体名第一次出现，创建 ``add_node`` 操作；如果已存在，则合并
        摘要、重要度和来源引用，必要时返回 ``update_node``。
        """
        if self._is_low_value_label(entity.name):
            return None

        key = self._normalize_label(entity.name)
        index = self._node_index.setdefault(graph.session_id, {})
        node_id = index.get(key) or self._find_similar_node_id(graph, key)

        if node_id is None:
            node = KnowledgeNode(
                node_id=entity.entity_id or self._node_id(entity.name),
                label=entity.name,
                type=entity.type,
                summary=entity.description,
                level=0,
                importance=importance,
                source_refs=self._limited_refs(refs, self.MAX_NODE_SOURCE_REFS),
            )
            graph.nodes.append(node)
            index[key] = node.node_id
            return GraphPatchOperation(op="add_node", node=node)

        node = self._find_node(graph, node_id)
        if node is None:
            return None

        changed = False
        if node.type == "concept" and entity.type and entity.type != node.type:
            node.type = entity.type
            changed = True
        if entity.description and entity.description != node.summary:
            node.summary = entity.description
            changed = True
        if importance is not None:
            old_importance = node.importance or 0.0
            node.importance = max(old_importance, importance)
            changed = changed or node.importance != old_importance
        changed = (
            self._merge_refs(node.source_refs, refs, max_refs=self.MAX_NODE_SOURCE_REFS)
            or changed
        )

        if not changed:
            return None
        return GraphPatchOperation(op="update_node", node=node)

    def _ensure_node_for_relation(
        self,
        graph: KnowledgeTree,
        label: str,
        refs: list[SourceRef],
    ) -> tuple[KnowledgeNode, GraphPatchOperation | None]:
        """Ensure relation endpoints exist even when SLM omitted entities.

        返回节点和可选 add_node 操作。这样当前端收到只包含关系的抽取
        结果时，也会先创建缺失节点，再创建边。
        """
        if self._is_low_value_label(label):
            raise ValueError(f"Low-value relation endpoint should be filtered first: {label}")

        key = self._normalize_label(label)
        index = self._node_index.setdefault(graph.session_id, {})
        node_id = index.get(key) or self._find_similar_node_id(graph, key)
        if node_id is not None:
            node = self._find_node(graph, node_id)
            if node is not None:
                self._merge_refs(
                    node.source_refs,
                    refs,
                    max_refs=self.MAX_NODE_SOURCE_REFS,
                )
                return node, None

        node = KnowledgeNode(
            node_id=self._node_id(label),
            label=label,
            level=0,
            source_refs=self._limited_refs(refs, self.MAX_NODE_SOURCE_REFS),
        )
        graph.nodes.append(node)
        index[key] = node.node_id
        return node, GraphPatchOperation(op="add_node", node=node)

    # ── 边处理 ───────────────────────────────────────────────

    def _upsert_edge(
        self,
        graph: KnowledgeTree,
        relation: KnowledgeRelation,
        refs: list[SourceRef],
    ) -> list[GraphPatchOperation]:
        """Insert or enrich an edge between two existing/placeholder nodes."""
        operations: list[GraphPatchOperation] = []
        source_label, target_label, relation_label = self._normalize_relation(
            relation.source,
            relation.target,
            relation.relation,
        )
        if (
            self._is_low_value_label(source_label)
            or self._is_low_value_label(target_label)
            or source_label == target_label
        ):
            return operations

        source_node, source_operation = self._ensure_node_for_relation(
            graph, source_label, refs
        )
        target_node, target_operation = self._ensure_node_for_relation(
            graph, target_label, refs
        )
        if source_operation is not None:
            operations.append(source_operation)
        if target_operation is not None:
            operations.append(target_operation)

        edge_id = self._edge_id(source_node.node_id, target_node.node_id, relation_label)

        for edge in graph.edges:
            if edge.edge_id == edge_id:
                self._merge_refs(
                    edge.source_refs,
                    refs,
                    max_refs=self.MAX_EDGE_SOURCE_REFS,
                )
                return operations

        edge = KnowledgeEdge(
            edge_id=edge_id,
            source=source_node.node_id,
            target=target_node.node_id,
            relation=relation_label,
            source_refs=self._limited_refs(refs, self.MAX_EDGE_SOURCE_REFS),
        )
        graph.edges.append(edge)
        operations.append(GraphPatchOperation(op="add_edge", edge=edge))
        return operations

    # ── 工具方法 ─────────────────────────────────────────────

    def _source_refs(self, extraction: KnowledgeExtraction) -> list[SourceRef]:
        """Build compact traceability references from extraction source fields.

        ``event`` refs are intentionally omitted here. They point to extraction
        bookkeeping rather than classroom material and can grow very large when
        note snapshots repeatedly cover cumulative transcript ranges.
        """
        refs: list[SourceRef] = []
        for segment_id in extraction.source_segment_ids:
            ts = extraction.timestamp_range[0] if extraction.timestamp_range else None
            refs.append(SourceRef(type="segment", id=segment_id, ts=ts))
        for visual_id in extraction.source_visual_ids:
            ts = extraction.timestamp_range[0] if extraction.timestamp_range else None
            refs.append(SourceRef(type="visual", id=visual_id, ts=ts))
        return refs

    def _merge_refs(
        self,
        target: list[SourceRef],
        refs: list[SourceRef],
        *,
        max_refs: int,
    ) -> bool:
        """Merge refs while keeping the latest compact classroom-material window."""
        original = [(ref.type, ref.id, ref.ts) for ref in target]
        material_ref_count = sum(1 for ref in refs if ref.type != "event")
        if material_ref_count >= max_refs:
            merged = self._limited_refs(refs, max_refs)
        else:
            merged = self._limited_refs([*target, *refs], max_refs)
        merged_key = [(ref.type, ref.id, ref.ts) for ref in merged]
        if merged_key == original:
            return False
        target[:] = merged
        return True

    def _limited_refs(self, refs: list[SourceRef], max_refs: int) -> list[SourceRef]:
        """Return recent unique classroom-material refs capped for compact storage."""
        unique: list[SourceRef] = []
        seen: set[tuple[str, str, float | None]] = set()
        for ref in refs:
            if ref.type == "event":
                continue
            key = (ref.type, ref.id, ref.ts)
            if key in seen:
                continue
            unique.append(ref)
            seen.add(key)
        return unique[-max_refs:]

    def _recompute_roots(self, graph: KnowledgeTree) -> None:
        """Recalculate root nodes and breadth-first tree levels."""
        targets = {edge.target for edge in graph.edges}
        graph.root_nodes = [node.node_id for node in graph.nodes if node.node_id not in targets]
        if not graph.root_nodes and graph.nodes:
            graph.root_nodes = [graph.nodes[0].node_id]

        children: dict[str, list[str]] = {}
        for edge in graph.edges:
            children.setdefault(edge.source, []).append(edge.target)

        levels: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in graph.root_nodes)
        while queue:
            node_id, level = queue.popleft()
            if node_id in levels and levels[node_id] <= level:
                continue
            levels[node_id] = level
            for child_id in children.get(node_id, []):
                queue.append((child_id, level + 1))

        for node in graph.nodes:
            node.level = levels.get(node.node_id, 0)

    def _find_node(self, graph: KnowledgeTree, node_id: str) -> KnowledgeNode | None:
        """Find one node by ID in the current graph snapshot."""
        for node in graph.nodes:
            if node.node_id == node_id:
                return node
        return None

    def _normalize_label(self, label: str) -> str:
        """Normalize labels for MVP deduplication."""
        normalized = re.sub(r"[\s\-_（）()《》“”'\"，,。:：]+", "", label.strip().lower())
        return self._strip_generic_suffix(normalized)

    def _find_similar_node_id(self, graph: KnowledgeTree, key: str) -> str | None:
        """Find an existing node with an obviously equivalent label."""
        best_node_id: str | None = None
        best_score = 0.0
        for node in graph.nodes:
            node_key = self._normalize_label(node.label)
            if key == node_key:
                return node.node_id
            if not key or not node_key:
                continue
            score = SequenceMatcher(None, key, node_key, autojunk=False).ratio()
            if score > best_score:
                best_score = score
                best_node_id = node.node_id
        if best_score >= 0.9:
            index = self._node_index.setdefault(graph.session_id, {})
            if best_node_id is not None:
                index[key] = best_node_id
            return best_node_id
        return None

    def _strip_generic_suffix(self, label: str) -> str:
        return strip_generic_entity_affixes(label)

    def _is_low_value_label(self, label: str) -> bool:
        return is_low_value_entity_name(label)

    def _normalize_relation(
        self,
        source: str,
        target: str,
        relation: str,
    ) -> tuple[str, str, str]:
        """Normalize relation label and hierarchy direction for stable edges."""
        label = re.sub(r"[\s\-]+", "_", relation.strip().lower()) or "related_to"
        label = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "", label) or "related_to"
        aliases = {
            "include": "contains",
            "includes": "contains",
            "contain": "contains",
            "has_part": "contains",
        }
        label = aliases.get(label, label)
        reverse_hierarchy = {
            "part_of": "contains",
            "belongs_to": "contains",
            "included_in": "contains",
            "subtopic_of": "contains",
            "example_of": "has_example",
            "属于": "contains",
            "隶属于": "contains",
        }
        reversed_label = reverse_hierarchy.get(label)
        if reversed_label is not None:
            return target, source, reversed_label
        return source, target, label

    def _node_id(self, label: str) -> str:
        """Create a stable node ID from a human-readable label."""
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", label.strip()).strip("_")
        return f"node_{slug or 'unknown'}"

    def _edge_id(self, source: str, target: str, relation: str) -> str:
        """Create a stable edge ID so duplicate relations merge naturally."""
        raw = f"{source}_{relation}_{target}"
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", raw).strip("_")
        return f"edge_{slug}"


knowledge_graph_manager = KnowledgeGraphManager()
"""KnowledgeGraphManager 的全局单例实例。"""
