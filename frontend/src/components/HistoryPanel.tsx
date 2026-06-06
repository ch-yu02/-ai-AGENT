import type { LectureSession, SessionHistorySummary } from "../types/classroom";

// 左侧历史课程栏。
//
// 这是一个纯展示/交互组件：
// - 不直接调用 fetch。
// - 不知道历史详情如何合并进 dashboard。
// - 只把“刷新列表”“打开某节课”“删除某节课”三个用户动作交给 App。
//
// 这样未来如果引入路由、分页或搜索，这个组件仍然可以复用为列表视图。
type HistoryPanelProps = {
  // GET /sessions 返回的已保存课堂摘要。这里不展示完整 transcript/graph，
  // 只展示足够让用户识别课程的信息。
  sessions: SessionHistorySummary[];
  // 当前右侧看板正在查看的历史 session_id。null 表示没有选中历史课，
  // 通常是还没打开历史，或当前正在看实时课堂。
  selectedSessionId: string | null;
  // 正在刷新列表时禁用刷新按钮，并展示读取中的空状态文案。
  isLoading: boolean;
  // 正在打开详情时禁用所有历史项，避免用户快速连点导致请求竞态。
  isOpening: boolean;
  // 正在删除的 session_id。只禁用对应删除按钮并展示“删除中”，其它历史项
  // 仍可浏览，减少一次删除操作对整个列表的打断。
  deletingSessionId: string | null;
  // App 在“课堂正在录制”时传 true。这里统一禁用历史项，避免打开历史
  // 详情时关闭当前录制课堂的 WebSocket。
  isOpenDisabled: boolean;
  onRefresh: () => void;
  onOpen: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
};

export function HistoryPanel({
  sessions,
  selectedSessionId,
  isLoading,
  isOpening,
  deletingSessionId,
  isOpenDisabled,
  onRefresh,
  onOpen,
  onDelete,
}: HistoryPanelProps) {
  return (
    <aside className="history-panel" aria-labelledby="history-title">
      <div className="history-header">
        <div>
          <h2 id="history-title">历史课程</h2>
          {/* 这个数量只代表后端已经落盘的课程，不包含还在录制中的内存 session。 */}
          <span>{sessions.length} 节已保存</span>
        </div>
        <button
          className="icon-text-button"
          type="button"
          disabled={isLoading}
          onClick={onRefresh}
        >
          {isLoading ? "刷新中" : "刷新"}
        </button>
      </div>

      {sessions.length === 0 ? (
        <div className="history-empty">
          {isLoading ? "正在读取历史课程" : "暂无已保存课程"}
        </div>
      ) : (
        <div className="history-list" aria-label="历史课程列表">
          {sessions.map((item) => {
            const sessionId = item.session.session_id;
            const isSelected = sessionId === selectedSessionId;
            const isDeleting = sessionId === deletingSessionId;

            return (
              <article
                className={isSelected ? "history-item active" : "history-item"}
                key={sessionId}
              >
                <button
                  className="history-open-button"
                  disabled={isOpenDisabled || isOpening || isDeleting}
                  type="button"
                  onClick={() => onOpen(sessionId)}
                >
                  <span className="history-title">{item.session.title}</span>
                  <span className="history-meta">{historyMeta(item.session)}</span>
                  <span className="history-foot">
                    <span>{item.event_count} 个事件</span>
                    <span>{item.session.status === "ended" ? "已结束" : "录制中"}</span>
                  </span>
                </button>
                <button
                  className="history-delete-button"
                  disabled={isDeleting}
                  type="button"
                  onClick={() => onDelete(sessionId)}
                >
                  {isDeleting ? "删除中" : "删除"}
                </button>
              </article>
            );
          })}
        </div>
      )}
    </aside>
  );
}

function historyMeta(session: LectureSession): string {
  // 历史列表空间有限，只保留“课程名 + 开始时间”。教师、设备等信息仍在
  // 详情 API 的 session 字段里，后续详情页需要时再展示。
  const course = session.course || "未命名课程";
  return `${course} · ${formatAbsoluteTime(session.start_time)}`;
}

function formatAbsoluteTime(value: string): string {
  // 后端存的是 ISO-8601 字符串。浏览器 Date 会按用户本地时区展示，
  // 这符合本地课堂回放的直觉；解析失败时原样返回，方便暴露异常数据。
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
