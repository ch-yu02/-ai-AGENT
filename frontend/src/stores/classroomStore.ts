import type {
  ClassroomDashboardState,
  ContextUpdate,
  GraphPatch,
  GraphPatchOperation,
  ImageCapture,
  KnowledgeEdge,
  KnowledgeGraphView,
  KnowledgeNode,
  LectureSession,
  TimelineItem,
  TranscriptSegment,
  WebSocketMessage,
  WebSocketStatus,
} from "../types/classroom";

// 前端课堂 store。
//
// 这个文件集中维护“后端实时消息 -> 前端页面状态”的转换规则。
// App 负责发起 API、建立 WebSocket 和 dispatch action；store 负责纯数据归并。
// 这样后续新增字幕滚动、图谱渲染、历史课程等功能时，不需要把状态处理逻辑
// 堆在 App.tsx 里。

export const initialDashboardState: ClassroomDashboardState = {
  session: null,
  websocketStatus: "disconnected",
  eventCount: 0,
  transcript: [],
  timeline: [],
  visuals: [],
  graph: {
    nodes: [],
    edges: [],
    version: 0,
  },
};

export type ClassroomAction =
  | {
      type: "session.started";
      session: LectureSession;
    }
  | {
      type: "session.ended";
      session: LectureSession;
    }
  | {
      type: "websocket.statusChanged";
      status: WebSocketStatus;
    }
  | {
      type: "websocket.messageReceived";
      message: WebSocketMessage;
    };

export function classroomReducer(
  state: ClassroomDashboardState,
  action: ClassroomAction,
): ClassroomDashboardState {
  switch (action.type) {
    case "session.started":
      // 开始新课堂时清空上一节课的实时数据，但保留新的 session。
      // WebSocket 随后会进入 connecting/connected。
      return {
        ...initialDashboardState,
        session: action.session,
      };

    case "session.ended":
      // 结束课堂由 HTTP 响应或 WebSocket session.ended 广播触发。
      // 保留现有字幕/时间线/图谱，方便用户结束后继续查看本次课堂结果。
      return {
        ...state,
        session: action.session,
        websocketStatus: "disconnected",
      };

    case "websocket.statusChanged":
      return {
        ...state,
        websocketStatus: action.status,
      };

    case "websocket.messageReceived":
      return applyWebSocketMessage(state, action.message);
  }
}

function applyWebSocketMessage(
  state: ClassroomDashboardState,
  message: WebSocketMessage,
): ClassroomDashboardState {
  // ws.connected 是后端对订阅成功的确认。浏览器 onopen 也会把状态设为
  // connected，两处都设置是幂等的，能覆盖“onopen 已到但后端确认稍后到”的场景。
  if (message.type === "ws.connected") {
    return {
      ...state,
      websocketStatus: "connected",
    };
  }

  if (message.type === "session.ended") {
    return applySessionEndedMessage(state, message);
  }

  if (message.type === "event.received") {
    return applyEventReceivedMessage(state, message);
  }

  // session.started 通常发生在前端连接 WebSocket 之前，当前 MVP 不依赖它。
  return state;
}

function applySessionEndedMessage(
  state: ClassroomDashboardState,
  message: WebSocketMessage,
): ClassroomDashboardState {
  const session = readObject(message.data.session);

  if (!session || typeof session.session_id !== "string") {
    return {
      ...state,
      websocketStatus: "disconnected",
    };
  }

  // 后端的 session.ended 广播可能只带部分 session 字段。这里与当前 session
  // 合并，避免因为广播字段较少而丢掉 title/course 等前端正在展示的信息。
  return {
    ...state,
    session: state.session
      ? {
          ...state.session,
          ...session,
          status: "ended",
        }
      : state.session,
    websocketStatus: "disconnected",
  };
}

function applyEventReceivedMessage(
  state: ClassroomDashboardState,
  message: WebSocketMessage,
): ClassroomDashboardState {
  const data = message.data;
  const eventType = typeof data.event_type === "string" ? data.event_type : "";
  const payload = readObject(data.payload);
  const contextUpdate = parseContextUpdate(data.context_update);
  const graphPatch = parseGraphPatch(data.graph_patch);
  const eventCount = typeof data.event_count === "number" ? data.event_count : state.eventCount;

  let nextState: ClassroomDashboardState = {
    ...state,
    eventCount,
  };

  if (contextUpdate) {
    nextState = {
      ...nextState,
      timeline: upsertById(nextState.timeline, contextUpdate.timeline_item, "item_id"),
    };
  }

  // 优先使用 ContextManager 标准化后的 timeline_item.data；如果缺失，则回退到
  // 原始 payload。这样前端能兼容 mock sender 和后端默认补齐字段。
  const timelineData = readObject(contextUpdate?.timeline_item.data);
  const normalizedPayload =
    timelineData && Object.keys(timelineData).length > 0 ? timelineData : payload;

  if (eventType === "transcript.segment" && isTranscriptSegment(normalizedPayload)) {
    nextState = {
      ...nextState,
      transcript: upsertById(nextState.transcript, normalizedPayload, "segment_id"),
    };
  }

  if (eventType === "image.capture" && isImageCapture(normalizedPayload)) {
    nextState = {
      ...nextState,
      visuals: upsertById(nextState.visuals, normalizedPayload, "image_id"),
    };
  }

  if (graphPatch) {
    nextState = {
      ...nextState,
      graph: applyGraphPatch(nextState.graph, graphPatch),
    };
  }

  return nextState;
}

function applyGraphPatch(graph: KnowledgeGraphView, patch: GraphPatch): KnowledgeGraphView {
  // GraphPatch 是有序操作流。必须按后端给出的顺序应用，因为 relation 可能引用
  // 同一个 patch 中刚刚创建的占位节点。
  return patch.operations.reduce(
    (currentGraph, operation) => applyGraphOperation(currentGraph, operation),
    {
      ...graph,
      version: patch.to_version,
    },
  );
}

function applyGraphOperation(
  graph: KnowledgeGraphView,
  operation: GraphPatchOperation,
): KnowledgeGraphView {
  if ((operation.op === "add_node" || operation.op === "update_node") && operation.node) {
    return {
      ...graph,
      nodes: upsertById(graph.nodes, operation.node, "node_id"),
    };
  }

  if (operation.op === "add_edge" && operation.edge) {
    return {
      ...graph,
      edges: upsertById(graph.edges, operation.edge, "edge_id"),
    };
  }

  if (operation.op === "remove_node" && operation.node) {
    return {
      ...graph,
      nodes: graph.nodes.filter((node) => node.node_id !== operation.node?.node_id),
      edges: graph.edges.filter(
        (edge) =>
          edge.source !== operation.node?.node_id && edge.target !== operation.node?.node_id,
      ),
    };
  }

  if (operation.op === "remove_edge" && operation.edge) {
    return {
      ...graph,
      edges: graph.edges.filter((edge) => edge.edge_id !== operation.edge?.edge_id),
    };
  }

  return graph;
}

function upsertById<T extends Record<K, string>, K extends keyof T>(
  items: T[],
  nextItem: T,
  key: K,
): T[] {
  const index = items.findIndex((item) => item[key] === nextItem[key]);

  if (index === -1) {
    return [...items, nextItem];
  }

  return items.map((item, itemIndex) =>
    itemIndex === index
      ? {
          ...item,
          ...nextItem,
        }
      : item,
  );
}

function parseContextUpdate(value: unknown): ContextUpdate | null {
  const data = readObject(value);
  const timelineItem = parseTimelineItem(data?.timeline_item);

  if (!data || !timelineItem || typeof data.session_id !== "string") {
    return null;
  }

  return {
    session_id: data.session_id,
    event_type: typeof data.event_type === "string" ? data.event_type : "",
    timeline_item: timelineItem,
    transcript_count: readNumber(data.transcript_count),
    visual_count: readNumber(data.visual_count),
    knowledge_extraction_count: readNumber(data.knowledge_extraction_count),
  };
}

function parseTimelineItem(value: unknown): TimelineItem | null {
  const data = readObject(value);

  if (
    !data ||
    typeof data.item_id !== "string" ||
    typeof data.session_id !== "string" ||
    typeof data.type !== "string" ||
    typeof data.title !== "string"
  ) {
    return null;
  }

  const timelineType = data.type;

  if (!["transcript", "visual", "knowledge"].includes(timelineType)) {
    return null;
  }

  return {
    item_id: data.item_id,
    session_id: data.session_id,
    type: timelineType as TimelineItem["type"],
    ts: readNumber(data.ts),
    title: data.title,
    data: readObject(data.data) ?? {},
  };
}

function parseGraphPatch(value: unknown): GraphPatch | null {
  const data = readObject(value);

  if (!data || typeof data.session_id !== "string" || !Array.isArray(data.operations)) {
    return null;
  }

  return {
    session_id: data.session_id,
    from_version: readNumber(data.from_version),
    to_version: readNumber(data.to_version),
    operations: data.operations.flatMap((operation) => {
      const parsedOperation = parseGraphPatchOperation(operation);
      return parsedOperation ? [parsedOperation] : [];
    }),
  };
}

function parseGraphPatchOperation(value: unknown): GraphPatchOperation | null {
  const data = readObject(value);

  if (!data || typeof data.op !== "string") {
    return null;
  }

  const operationType = data.op;

  if (
    !["add_node", "update_node", "add_edge", "remove_node", "remove_edge"].includes(
      operationType,
    )
  ) {
    return null;
  }

  return {
    op: operationType as GraphPatchOperation["op"],
    node: parseKnowledgeNode(data.node),
    edge: parseKnowledgeEdge(data.edge),
    data: readObject(data.data) ?? {},
  };
}

function parseKnowledgeNode(value: unknown): KnowledgeNode | null {
  const data = readObject(value);

  if (!data || typeof data.node_id !== "string" || typeof data.label !== "string") {
    return null;
  }

  return {
    node_id: data.node_id,
    label: data.label,
    type: typeof data.type === "string" ? data.type : "concept",
    summary: typeof data.summary === "string" ? data.summary : null,
    level: typeof data.level === "number" ? data.level : undefined,
    importance: typeof data.importance === "number" ? data.importance : null,
  };
}

function parseKnowledgeEdge(value: unknown): KnowledgeEdge | null {
  const data = readObject(value);

  if (
    !data ||
    typeof data.edge_id !== "string" ||
    typeof data.source !== "string" ||
    typeof data.target !== "string" ||
    typeof data.relation !== "string"
  ) {
    return null;
  }

  return {
    edge_id: data.edge_id,
    source: data.source,
    target: data.target,
    relation: data.relation,
  };
}

function isTranscriptSegment(value: unknown): value is TranscriptSegment {
  const data = readObject(value);

  return (
    !!data &&
    typeof data.segment_id === "string" &&
    typeof data.text === "string" &&
    typeof data.start_ts === "number" &&
    typeof data.end_ts === "number"
  );
}

function isImageCapture(value: unknown): value is ImageCapture {
  const data = readObject(value);

  return (
    !!data &&
    typeof data.image_id === "string" &&
    typeof data.capture_ts === "number" &&
    typeof data.image_path === "string" &&
    typeof data.status === "string"
  );
}

function readObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }

  return null;
}

function readNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
