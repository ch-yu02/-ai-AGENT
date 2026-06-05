import { useEffect, useReducer, useRef, useState } from "react";

import { ClassroomControls } from "./components/ClassroomControls";
import { KnowledgeGraphPanel } from "./components/KnowledgeGraphPanel";
import { RealtimeTranscriptPanel } from "./components/RealtimeTranscriptPanel";
import { StatusStrip } from "./components/StatusStrip";
import { TimelinePanel } from "./components/TimelinePanel";
import { VisualOcrPanel } from "./components/VisualOcrPanel";
import { ApiError, endSession, startSession } from "./services/api";
import { connectClassroomSocket } from "./services/websocket";
import { classroomReducer, initialDashboardState } from "./stores/classroomStore";
import type { WebSocketMessage } from "./types/classroom";

function App() {
  // 页面主状态由 classroomReducer 管理。
  //
  // useReducer 比多个 setState 更适合实时消息流：每条 WebSocket 消息都是一个
  // action，reducer 负责把 action 归并到课堂状态。这样 App.tsx 保持在
  // “连接服务 + 触发 action”的层次，具体的数据合并规则放在 stores/。
  const [state, dispatch] = useReducer(classroomReducer, initialDashboardState);

  // 开始/结束课堂都是异步 HTTP 请求。这个状态用于禁用按钮，避免用户
  // 连续点击导致重复创建 session 或重复结束课堂。
  const [isSessionRequestPending, setIsSessionRequestPending] = useState(false);

  // 轻量级页面提示。当前只显示 API 成功/失败信息；后续也可以显示
  // WebSocket 断线、mock sender 联调提示等运行状态。
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // 保存当前课堂的 WebSocket 实例。
  //
  // WebSocket 是浏览器对象，不属于可渲染 UI 数据，所以用 ref 而不是 state。
  // 这样关闭旧连接时不会触发额外渲染，也能避免开始新课堂后旧 socket 继续推消息。
  const socketRef = useRef<WebSocket | null>(null);

  // 组件卸载时关闭 WebSocket。
  // Vite 热更新、页面跳转或未来加路由时，如果不清理连接，后端还会保留旧订阅者。
  useEffect(() => {
    return () => {
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);

  // 为指定 session 建立 WebSocket 订阅。
  //
  // 这里与 startSession 分开写，是为了以后支持“重新连接”按钮：
  // 只要还持有 session_id，就可以复用这个函数重新订阅同一课堂。
  function connectWebSocket(sessionId: string) {
    // 开始新课堂或重连前，先关闭旧连接，保证页面只消费当前 session 的消息。
    socketRef.current?.close();

    dispatch({ type: "websocket.statusChanged", status: "connecting" });

    // 回调里会引用 socket 自身，用于判断事件是否来自当前连接。
    // WebSocket 的 close/error 事件可能在新连接建立后才到达；如果不做判断，
    // 旧连接的回调可能把新连接状态错误地改成 disconnected/error。
    let socket: WebSocket;
    const isCurrentSocket = () => socketRef.current === socket;

    socket = connectClassroomSocket(sessionId, {
      onOpen: () => {
        if (!isCurrentSocket()) {
          return;
        }

        // onOpen 表示浏览器和后端的 WebSocket 握手已经成功。
        // 后端随后还会推送 ws.connected；两者任意一个到达都可以认为已连接。
        dispatch({ type: "websocket.statusChanged", status: "connected" });
        setStatusMessage("WebSocket 已连接，等待实时事件。");
      },
      onMessage: (message) => {
        if (!isCurrentSocket()) {
          return;
        }

        handleWebSocketMessage(message);
      },
      onError: () => {
        if (!isCurrentSocket()) {
          return;
        }

        dispatch({ type: "websocket.statusChanged", status: "error" });
        setStatusMessage("WebSocket 连接异常，请确认后端服务仍在运行。");
      },
      onClose: (event) => {
        if (!isCurrentSocket()) {
          return;
        }

        // 如果是用户结束课堂或页面卸载触发的正常关闭，状态回到 disconnected。
        // 如果异常关闭但 onerror 没有先触发，这里也给出连接异常提示。
        dispatch({
          type: "websocket.statusChanged",
          status: event.wasClean ? "disconnected" : "error",
        });

        if (!event.wasClean) {
          setStatusMessage(`WebSocket 已断开：${event.code || "unknown"}`);
        }
      },
    });

    socketRef.current = socket;
  }

  // WebSocket 消息分发入口。
  //
  // App 不直接拆解 event.received。它只把完整 WebSocketMessage 交给 reducer，
  // 由 store 统一处理 context_update、payload、graph_patch 等字段。
  function handleWebSocketMessage(message: WebSocketMessage) {
    dispatch({ type: "websocket.messageReceived", message });

    if (message.type === "ws.connected") {
      setStatusMessage("WebSocket 订阅确认成功。");
      return;
    }

    if (message.type === "event.received") {
      setStatusMessage("收到实时事件，页面数据已更新。");
      return;
    }

    if (message.type === "session.ended") {
      setStatusMessage("收到课堂结束广播。");
    }
  }

  // 开始课堂：
  // 1. 调用后端 POST /sessions/start。
  // 2. 用返回的 LectureSession 初始化前端课堂状态。
  // 3. 清空上一节课残留的字幕、时间线、图片和图谱。
  // 4. 用 session_id 连接后端 /ws/{session_id}。
  async function handleStartSession() {
    setIsSessionRequestPending(true);
    setStatusMessage(null);

    try {
      const session = await startSession();
      dispatch({
        type: "session.started",
        session,
      });
      setStatusMessage("课堂已开始，正在连接 WebSocket。");
      connectWebSocket(session.session_id);
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
  // HTTP 响应和 session.ended 广播都可能更新同一状态，因此这里保持幂等：
  // 即使广播先到或后到，最终状态都是 ended + disconnected。
  async function handleEndSession() {
    if (!state.session) {
      return;
    }

    setIsSessionRequestPending(true);
    setStatusMessage(null);

    try {
      const session = await endSession(state.session.session_id);
      dispatch({
        type: "session.ended",
        session,
      });
      socketRef.current?.close();
      socketRef.current = null;
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
