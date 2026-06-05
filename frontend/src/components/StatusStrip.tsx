import type { LectureSession, WebSocketStatus } from "../types/classroom";

// 页面顶部的状态摘要。
// 它把跨模块状态放在一个容易扫读的位置：当前课堂、session_id、WS 状态、
// 事件计数。后续 mock sender 联调时，session_id 是最常用的信息。
type StatusStripProps = {
  session: LectureSession | null;
  websocketStatus: WebSocketStatus;
  eventCount: number;
};

// 内部状态值保持英文，便于代码分支；展示文案在这里统一映射成中文。
const statusLabels: Record<WebSocketStatus, string> = {
  disconnected: "未连接",
  connecting: "连接中",
  connected: "已连接",
  error: "连接异常",
};

export function StatusStrip({ session, websocketStatus, eventCount }: StatusStripProps) {
  return (
    <section className="status-strip" aria-label="课堂状态">
      <div>
        <span>课堂</span>
        <strong>{session?.title || "未开始"}</strong>
      </div>
      <div>
        <span>Session ID</span>
        <strong>{session?.session_id || "-"}</strong>
      </div>
      <div>
        <span>WebSocket</span>
        <strong className={`ws-state ${websocketStatus}`}>
          {statusLabels[websocketStatus]}
        </strong>
      </div>
      <div>
        <span>事件数</span>
        <strong>{eventCount}</strong>
      </div>
    </section>
  );
}
