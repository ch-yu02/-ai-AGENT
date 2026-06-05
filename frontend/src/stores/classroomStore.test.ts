import { describe, expect, it } from "vitest";

import { classroomReducer, initialDashboardState } from "./classroomStore";
import type { WebSocketMessage } from "../types/classroom";

// Store smoke tests.
//
// 这些测试不依赖浏览器、不连接真实后端，只验证 reducer 是否能正确消费
// 后端 WebSocket 的 event.received 信封。真实联调时，WebSocket service
// 只负责把 JSON 解析成 WebSocketMessage，然后 dispatch 给同一个 reducer。

describe("classroomReducer", () => {
  it("stores transcript event.received updates", () => {
    const message = eventReceivedMessage({
      event_type: "transcript.segment",
      event_count: 1,
      payload: {},
      context_update: {
        session_id: "lec_test",
        event_type: "transcript.segment",
        timeline_item: {
          item_id: "seg_001",
          session_id: "lec_test",
          type: "transcript",
          ts: 1,
          title: "傅里叶变换可以把时域信号转换到频域。",
          data: {
            segment_id: "seg_001",
            session_id: "lec_test",
            start_ts: 1,
            end_ts: 3,
            text: "傅里叶变换可以把时域信号转换到频域。",
          },
        },
        transcript_count: 1,
        visual_count: 0,
        knowledge_extraction_count: 0,
      },
      graph_patch: null,
    });

    const state = classroomReducer(initialDashboardState, {
      type: "websocket.messageReceived",
      message,
    });

    expect(state.eventCount).toBe(1);
    expect(state.timeline).toHaveLength(1);
    expect(state.transcript).toHaveLength(1);
    expect(state.transcript[0].text).toContain("傅里叶变换");
  });

  it("stores visual event.received updates", () => {
    const message = eventReceivedMessage({
      event_type: "image.capture",
      event_count: 1,
      payload: {},
      context_update: {
        session_id: "lec_test",
        event_type: "image.capture",
        timeline_item: {
          item_id: "img_001",
          session_id: "lec_test",
          type: "visual",
          ts: 10,
          title: "X(f)=∫x(t)e^{-j2πft}dt",
          data: {
            image_id: "img_001",
            session_id: "lec_test",
            capture_ts: 10,
            image_path: "local://sessions/lec_test/images/img_001.jpg",
            status: "processed",
            ocr_text: "X(f)=∫x(t)e^{-j2πft}dt",
          },
        },
        transcript_count: 0,
        visual_count: 1,
        knowledge_extraction_count: 0,
      },
      graph_patch: null,
    });

    const state = classroomReducer(initialDashboardState, {
      type: "websocket.messageReceived",
      message,
    });

    expect(state.timeline).toHaveLength(1);
    expect(state.visuals).toHaveLength(1);
    expect(state.visuals[0].ocr_text).toContain("X(f)");
  });

  it("applies knowledge graph patches from event.received updates", () => {
    const message = eventReceivedMessage({
      event_type: "knowledge.extraction",
      event_count: 1,
      payload: {},
      context_update: {
        session_id: "lec_test",
        event_type: "knowledge.extraction",
        timeline_item: {
          item_id: "ext_001",
          session_id: "lec_test",
          type: "knowledge",
          ts: 1,
          title: "知识点：傅里叶变换、频域",
          data: {},
        },
        transcript_count: 0,
        visual_count: 0,
        knowledge_extraction_count: 1,
      },
      graph_patch: {
        session_id: "lec_test",
        from_version: 0,
        to_version: 1,
        operations: [
          {
            op: "add_node",
            node: {
              node_id: "node_fourier",
              label: "傅里叶变换",
              type: "concept",
              summary: "将信号从时域表示转换到频域表示的数学工具",
              level: 0,
              importance: 0.92,
            },
            edge: null,
            data: {},
          },
          {
            op: "add_node",
            node: {
              node_id: "node_freq",
              label: "频域",
              type: "concept",
              summary: null,
              level: 0,
              importance: null,
            },
            edge: null,
            data: {},
          },
          {
            op: "add_edge",
            node: null,
            edge: {
              edge_id: "edge_fourier_freq",
              source: "node_fourier",
              target: "node_freq",
              relation: "maps_to",
            },
            data: {},
          },
        ],
      },
    });

    const state = classroomReducer(initialDashboardState, {
      type: "websocket.messageReceived",
      message,
    });

    expect(state.timeline).toHaveLength(1);
    expect(state.graph.version).toBe(1);
    expect(state.graph.nodes).toHaveLength(2);
    expect(state.graph.edges).toHaveLength(1);
    expect(state.graph.nodes[0].label).toBe("傅里叶变换");
  });
});

function eventReceivedMessage(data: Record<string, unknown>): WebSocketMessage {
  return {
    type: "event.received",
    session_id: "lec_test",
    data,
    created_at: "2026-06-05T00:00:00.000000+00:00",
  };
}
