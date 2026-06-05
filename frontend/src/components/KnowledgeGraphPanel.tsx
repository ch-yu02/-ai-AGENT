import { EmptyState } from "./EmptyState";
import type { KnowledgeGraphView } from "../types/classroom";

// 知识图谱面板。
//
// 后端 KnowledgeGraphManager 通过 graph_patch.operations 推送增量变更。
// 当前 MVP 先用“节点列表 + 关系列表”稳定展示，避免一开始引入图谱渲染库。
// 后续接 React Flow / Cytoscape 时，可以保留 KnowledgeGraphView 作为适配层。
type KnowledgeGraphPanelProps = {
  graph: KnowledgeGraphView;
};

export function KnowledgeGraphPanel({ graph }: KnowledgeGraphPanelProps) {
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
          {/* 节点区：展示概念名称和摘要。 */}
          <div className="node-list">
            {graph.nodes.map((node) => (
              <article className="node-item" key={node.node_id}>
                <h3>{node.label}</h3>
                <p>{node.summary || node.type}</p>
              </article>
            ))}
          </div>
          {/* 关系区：展示 source --relation--> target。 */}
          <div className="edge-list">
            {graph.edges.map((edge) => (
              <div className="edge-item" key={edge.edge_id}>
                {edge.source} <span>{edge.relation}</span> {edge.target}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
