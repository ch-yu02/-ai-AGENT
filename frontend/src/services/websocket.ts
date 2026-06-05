import type { WebSocketMessage } from "../types/classroom";

// WebSocket 基地址。
// 后端实际订阅地址是 /ws/{session_id}，所以这里保留到 /ws。
// 可以通过 .env 设置 VITE_WS_BASE_URL 覆盖，例如部署到别的主机时使用。
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || "ws://127.0.0.1:8000/ws";

// 创建课堂 WebSocket 连接。
//
// 这个 service 只负责“建立连接 + 解析消息”，不直接修改 React state。
// 调用方通过 onMessage 决定如何处理：
// - ws.connected -> 更新连接状态
// - event.received -> 追加字幕/时间线/图片/图谱
// - session.ended -> 标记课堂结束
//
// 返回原生 WebSocket，方便调用方绑定 onopen/onclose/onerror 或主动 close。
export function connectClassroomSocket(
  sessionId: string,
  onMessage: (message: WebSocketMessage) => void,
): WebSocket {
  const socket = new WebSocket(`${WS_BASE_URL}/${sessionId}`);

  // 后端统一推送 WebSocketMessage JSON 信封。这里先做最小解析；
  // 后续如果需要更强健，可以在这里增加 try/catch 和运行时字段校验。
  socket.onmessage = (event) => {
    onMessage(JSON.parse(event.data) as WebSocketMessage);
  };

  return socket;
}
