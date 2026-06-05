// 前端共享类型定义。
//
// 这里的字段尽量与 docs/API_SCHEMA.md 和后端 Pydantic model 保持一致。
// 注意：后端 API 使用 snake_case，前端也保留 snake_case，减少联调时的
// 序列化/反序列化转换成本。

// POST /sessions/start 和 /sessions/{id}/end 返回的课堂元信息。
export type LectureSession = {
  session_id: string;
  title: string;
  course?: string | null;
  teacher?: string | null;
  start_time: string;
  end_time?: string | null;
  status: "recording" | "ended";
  language: string;
  created_by: string;
  device_id?: string | null;
};

// WebSocket 连接状态只描述前端连接生命周期，不等同于课堂 session.status。
export type WebSocketStatus = "disconnected" | "connecting" | "connected" | "error";

// ASR 字幕片段，对应 event_type = "transcript.segment"。
export type TranscriptSegment = {
  segment_id: string;
  session_id?: string;
  start_ts: number;
  end_ts: number;
  text: string;
  speaker?: string | null;
  confidence?: number | null;
  is_final?: boolean;
  source?: string | null;
  created_at?: string;
};

// 图片、OCR 或 VLM 视觉事件，对应 event_type = "image.capture"。
export type ImageCapture = {
  image_id: string;
  session_id?: string;
  capture_ts: number;
  upload_time?: string;
  image_path: string;
  source?: string | null;
  image_type?: string | null;
  status: string;
  ocr_text?: string | null;
  caption?: string | null;
};

// ContextManager 生成的统一时间线条目。
// 三类实时事件都会归一成 TimelineItem，方便前端只维护一条课堂流。
export type TimelineItem = {
  item_id: string;
  session_id: string;
  type: "transcript" | "visual" | "knowledge";
  ts: number;
  title: string;
  data: Record<string, unknown>;
};

// 知识图谱节点。字段来自 GraphPatch operation 中的 node。
export type KnowledgeNode = {
  node_id: string;
  label: string;
  type: string;
  summary?: string | null;
  level?: number;
  importance?: number | null;
};

// 知识图谱关系。字段来自 GraphPatch operation 中的 edge。
export type KnowledgeEdge = {
  edge_id: string;
  source: string;
  target: string;
  relation: string;
};

// 前端渲染用的图谱缓存。
// 后端按版本推送 patch，前端归并后得到这一份 view model。
export type KnowledgeGraphView = {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  version: number;
};

// 单条图谱增量操作。
// 前端 reducer 应按 operations 顺序执行，保证节点先于边创建。
export type GraphPatchOperation = {
  op: "add_node" | "update_node" | "add_edge";
  node?: KnowledgeNode | null;
  edge?: KnowledgeEdge | null;
  data?: Record<string, unknown>;
};

// KnowledgeGraphManager 对一次 knowledge.extraction 产生的增量补丁。
export type GraphPatch = {
  session_id: string;
  from_version: number;
  to_version: number;
  operations: GraphPatchOperation[];
};

// ContextManager 对一次实时事件产生的上下文更新摘要。
// event.received 消息中的 context_update 字段就是这个结构。
export type ContextUpdate = {
  session_id: string;
  event_type: string;
  timeline_item: TimelineItem;
  transcript_count: number;
  visual_count: number;
  knowledge_extraction_count: number;
};

// 后端 WebSocket 统一消息信封。
// data 会随 type 不同而变化，后续接 reducer 时再按 type 做窄化解析。
export type WebSocketMessage = {
  type: "ws.connected" | "session.started" | "event.received" | "session.ended";
  session_id: string;
  data: Record<string, unknown>;
  created_at: string;
};

// 当前课堂页面的整体状态。
// 这是 App 的本地 state 形状，也是未来 src/stores/ 可以直接迁移的基础。
export type ClassroomDashboardState = {
  session: LectureSession | null;
  websocketStatus: WebSocketStatus;
  eventCount: number;
  transcript: TranscriptSegment[];
  timeline: TimelineItem[];
  visuals: ImageCapture[];
  graph: KnowledgeGraphView;
};
