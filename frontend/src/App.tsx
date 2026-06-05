import { useState } from "react";

import { ClassroomControls } from "./components/ClassroomControls";
import { KnowledgeGraphPanel } from "./components/KnowledgeGraphPanel";
import { RealtimeTranscriptPanel } from "./components/RealtimeTranscriptPanel";
import { StatusStrip } from "./components/StatusStrip";
import { TimelinePanel } from "./components/TimelinePanel";
import { VisualOcrPanel } from "./components/VisualOcrPanel";
import { ApiError, endSession, startSession } from "./services/api";
import type { ClassroomDashboardState } from "./types/classroom";

// 课堂看板的空状态。
//
// 目前前端 MVP 还没有接入全局 store，所以 App 直接持有这一份状态。
// 后续接 WebSocket 时，可以继续沿用这个结构：
// - session: 当前课堂元信息，由 POST /sessions/start 和 /end 返回。
// - websocketStatus: /ws/{session_id} 的连接状态。
// - eventCount: 后端 event.received 消息里的累计事件数。
// - transcript/timeline/visuals: 从 context_update.timeline_item 或 payload 归并。
// - graph: 从 graph_patch.operations 增量归并。
const initialDashboardState: ClassroomDashboardState = {
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

function App() {
  // 页面主状态。MVP 阶段放在 App 内部，优点是数据流非常直观：
  // 控制按钮触发 API -> App 更新 state -> 各展示组件通过 props 重渲染。
  // 当 WebSocket reducer 变复杂时，可以把这块迁移到 src/stores/。
  const [state, setState] = useState<ClassroomDashboardState>(initialDashboardState);

  // 开始/结束课堂都是异步 HTTP 请求。这个状态用于禁用按钮，避免用户
  // 连续点击导致重复创建 session 或重复结束课堂。
  const [isSessionRequestPending, setIsSessionRequestPending] = useState(false);

  // 轻量级页面提示。当前只显示 API 成功/失败信息；后续也可以显示
  // WebSocket 断线、mock sender 联调提示等运行状态。
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // 开始课堂：
  // 1. 调用后端 POST /sessions/start。
  // 2. 用返回的 LectureSession 初始化前端课堂状态。
  // 3. 清空上一节课残留的字幕、时间线、图片和图谱。
  //
  // 下一步接 WebSocket 时，应在这里拿到 session.session_id 后连接
  // /ws/{session_id}，并把 websocketStatus 更新为 connecting/connected。
  async function handleStartSession() {
    setIsSessionRequestPending(true);
    setStatusMessage(null);

    try {
      const session = await startSession();
      setState({
        ...initialDashboardState,
        session,
      });
      setStatusMessage("课堂已开始，等待 WebSocket 接入。");
    } catch (error) {
      setStatusMessage(formatApiError(error, "开始课堂失败"));
    } finally {
      setIsSessionRequestPending(false);
    }
  }

  // 结束课堂：
  // 1. 只有存在当前 session 时才允许调用。
  // 2. 调用后端 POST /sessions/{session_id}/end。
  // 3. 后端会保存本地文件并广播 session.ended。
  //
  // 当前还没有 WebSocket，所以这里直接用 HTTP 响应更新 session 状态。
  // 接入 WebSocket 后，HTTP 响应和 session.ended 广播都可能更新同一状态，
  // reducer 需要保持幂等。
  async function handleEndSession() {
    if (!state.session) {
      return;
    }

    setIsSessionRequestPending(true);
    setStatusMessage(null);

    try {
      const session = await endSession(state.session.session_id);
      setState((current) => ({
        ...current,
        session,
        websocketStatus: "disconnected",
      }));
      setStatusMessage("课堂已结束，本地文件已由后端保存。");
    } catch (error) {
      setStatusMessage(formatApiError(error, "结束课堂失败"));
    } finally {
      setIsSessionRequestPending(false);
    }
  }

  return (
    <main className="app-shell">
      {/* 顶部区域只放课堂控制和产品身份，不承载实时数据。 */}
      <section className="top-bar" aria-label="课堂控制">
        <div className="brand-block">
          <span className="brand-mark">EDU</span>
          <div>
            <h1>课堂实时看板</h1>
            <p>Lecture-Link MVP</p>
          </div>
        </div>
        <ClassroomControls
          session={state.session}
          isBusy={isSessionRequestPending}
          onStart={handleStartSession}
          onEnd={handleEndSession}
        />
      </section>

      {/* 状态条展示跨模块状态：session、WebSocket 和事件计数。 */}
      <StatusStrip
        session={state.session}
        websocketStatus={state.websocketStatus}
        eventCount={state.eventCount}
      />

      {statusMessage ? <div className="status-message">{statusMessage}</div> : null}

      {/* 四个实时数据面板共享 App 状态，但组件内部不直接请求后端。 */}
      <section className="dashboard-grid" aria-label="课堂实时内容">
        <RealtimeTranscriptPanel transcript={state.transcript} />
        <TimelinePanel timeline={state.timeline} />
        <VisualOcrPanel visuals={state.visuals} />
        <KnowledgeGraphPanel graph={state.graph} />
      </section>
    </main>
  );
}

// 把 service 层抛出的错误转换成用户可读文案。
// ApiError 保留了后端 HTTP status 和 detail；普通 Error 通常来自 fetch
// 网络失败、浏览器 CORS 拒绝等前端侧问题。
function formatApiError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return `${fallback}：${error.detail}`;
  }

  if (error instanceof Error) {
    return `${fallback}：${error.message}`;
  }

  return fallback;
}

export default App;
