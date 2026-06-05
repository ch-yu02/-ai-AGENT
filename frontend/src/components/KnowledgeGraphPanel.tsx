import { useMemo, useState } from "react";

import { EmptyState } from "./EmptyState";
import type { KnowledgeEdge, KnowledgeGraphView, KnowledgeNode } from "../types/classroom";

// 知识图谱面板。
//
// 后端 KnowledgeGraphManager 通过 graph_patch.operations 推送增量变更。
// MVP 先提供两种显示：
// 1. 列表视图：稳定、信息密度高，适合联调时确认节点和边是否正确进入前端。
// 2. 图形视图：用轻量 SVG 画出节点和连线，不引入额外图库，避免增加依赖风险。
//
// 后续如果接 React Flow / Cytoscape，可以继续使用 KnowledgeGraphView 作为
// 数据适配层，把这里的 SVG 视图替换为专业图谱组件。
type KnowledgeGraphPanelProps = {
  graph: KnowledgeGraphView;
};

type GraphViewMode = "list" | "graph";

export function KnowledgeGraphPanel({ graph }: KnowledgeGraphPanelProps) {
  // 用户可以在“列表”和“图形”之间切换。
  // 默认列表，因为它对 mock sender 联调最可靠：任何节点/边都能直接读出来。
  const [viewMode, setViewMode] = useState<GraphViewMode>("list");

  // nodeById 用于把后端边里的 source/target 节点 ID 转成可读 label。
  // 后端 KnowledgeEdge.source/target 保存的是 node_id，不是实体中文名。
  const nodeById = useMemo(() => {
    return new Map(graph.nodes.map((node) => [node.node_id, node]));
  }, [graph.nodes]);

  return (
    <section className="panel graph-panel" aria-labelledby="graph-title">
      <div className="panel-header">
        <div>
          <h2 id="graph-title">知识图谱</h2>
          <span>v{graph.version}</span>
        </div>
        <strong>{graph.nodes.length}</strong>
      </div>

      {graph.nodes.length === 0 ? (
        <EmptyState label="等待知识点" />
      ) : (
        <div className="graph-content">
          <div className="segmented-control" role="tablist" aria-label="知识图谱视图">
            <button
              className={viewMode === "list" ? "active" : ""}
              type="button"
              role="tab"
              aria-selected={viewMode === "list"}
              onClick={() => setViewMode("list")}
            >
              列表
            </button>
            <button
              className={viewMode === "graph" ? "active" : ""}
              type="button"
              role="tab"
              aria-selected={viewMode === "graph"}
              onClick={() => setViewMode("graph")}
            >
              图形
            </button>
          </div>

          {viewMode === "list" ? (
            <KnowledgeGraphList graph={graph} nodeById={nodeById} />
          ) : (
            <KnowledgeGraphCanvas graph={graph} nodeById={nodeById} />
          )}
        </div>
      )}
    </section>
  );
}

type KnowledgeGraphListProps = {
  graph: KnowledgeGraphView;
  nodeById: Map<string, KnowledgeNode>;
};

function KnowledgeGraphList({ graph, nodeById }: KnowledgeGraphListProps) {
  return (
    <div className="graph-list-view">
      {/* 节点区：展示概念名称、类型、重要度和摘要。 */}
      <div className="node-list">
        {graph.nodes.map((node) => (
          <article className="node-item" key={node.node_id}>
            <div className="node-title-row">
              <h3>{node.label}</h3>
              <span>{node.type || "concept"}</span>
            </div>
            <p>{node.summary || "暂无摘要"}</p>
            {typeof node.importance === "number" ? (
              <meter min="0" max="1" value={node.importance}>
                {node.importance}
              </meter>
            ) : null}
          </article>
        ))}
      </div>

      {/* 关系区：展示 source --relation--> target。 */}
      <div className="edge-list" aria-label="知识关系">
        {graph.edges.length === 0 ? (
          <div className="edge-empty">等待关系</div>
        ) : (
          graph.edges.map((edge) => (
            <div className="edge-item" key={edge.edge_id}>
              {nodeLabel(edge.source, nodeById)} <span>{edge.relation}</span>{" "}
              {nodeLabel(edge.target, nodeById)}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

type KnowledgeGraphCanvasProps = {
  graph: KnowledgeGraphView;
  nodeById: Map<string, KnowledgeNode>;
};

function KnowledgeGraphCanvas({ graph, nodeById }: KnowledgeGraphCanvasProps) {
  // 轻量 SVG 布局。
  //
  // 对 MVP 来说，我们不需要复杂的力导向布局；只需要 mock sender 一推知识点，
  // 页面就能看见“点”和“关系”。这里把节点均匀放在椭圆上：
  // - 节点少时仍能保持居中。
  // - 节点多时不会互相完全重叠。
  // - 计算是纯函数，不需要 canvas 生命周期或第三方依赖。
  const layout = useMemo(() => createGraphLayout(graph.nodes), [graph.nodes]);

  return (
    <div className="graph-canvas" aria-label="知识图谱图形视图">
      <svg viewBox="0 0 640 360" role="img" aria-labelledby="graph-svg-title">
        <title id="graph-svg-title">课堂知识图谱</title>
        <defs>
          <marker
            id="arrow-head"
            markerHeight="8"
            markerWidth="8"
            orient="auto"
            refX="8"
            refY="4"
          >
            <path d="M0,0 L8,4 L0,8 Z" fill="#7a8aa0" />
          </marker>
        </defs>

        {graph.edges.map((edge) => {
          const source = layout.get(edge.source);
          const target = layout.get(edge.target);

          if (!source || !target) {
            return null;
          }

          return (
            <g className="graph-edge" key={edge.edge_id}>
              <line
                markerEnd="url(#arrow-head)"
                x1={source.x}
                x2={target.x}
                y1={source.y}
                y2={target.y}
              />
              <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 6}>
                {edge.relation}
              </text>
            </g>
          );
        })}

        {graph.nodes.map((node) => {
          const point = layout.get(node.node_id);

          if (!point) {
            return null;
          }

          return (
            <g className="graph-node" key={node.node_id}>
              <circle cx={point.x} cy={point.y} r={nodeRadius(node)} />
              <text x={point.x} y={point.y + 4}>
                {truncateLabel(node.label)}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="graph-caption">
        {graph.nodes.length} 个节点，{graph.edges.length} 条关系
        {graph.edges.length > 0 ? `，最新关系：${latestEdgeText(graph.edges, nodeById)}` : ""}
      </div>
    </div>
  );
}

function createGraphLayout(nodes: KnowledgeNode[]): Map<string, { x: number; y: number }> {
  const layout = new Map<string, { x: number; y: number }>();
  const centerX = 320;
  const centerY = 180;
  const radiusX = nodes.length <= 2 ? 130 : 230;
  const radiusY = nodes.length <= 2 ? 70 : 125;

  nodes.forEach((node, index) => {
    const angle = nodes.length === 1 ? 0 : (Math.PI * 2 * index) / nodes.length - Math.PI / 2;
    layout.set(node.node_id, {
      x: centerX + Math.cos(angle) * radiusX,
      y: centerY + Math.sin(angle) * radiusY,
    });
  });

  return layout;
}

function nodeRadius(node: KnowledgeNode): number {
  // importance 是 0-1 的重要度。用半径做轻量视觉权重，保持范围克制，
  // 避免一个高重要度节点压住整张图。
  const importance = typeof node.importance === "number" ? node.importance : 0.5;
  return 30 + Math.round(importance * 8);
}

function nodeLabel(nodeId: string, nodeById: Map<string, KnowledgeNode>): string {
  return nodeById.get(nodeId)?.label || nodeId;
}

function latestEdgeText(edges: KnowledgeEdge[], nodeById: Map<string, KnowledgeNode>): string {
  const latestEdge = edges[edges.length - 1];
  return `${nodeLabel(latestEdge.source, nodeById)} ${latestEdge.relation} ${nodeLabel(
    latestEdge.target,
    nodeById,
  )}`;
}

function truncateLabel(label: string): string {
  return label.length > 8 ? `${label.slice(0, 8)}...` : label;
}
