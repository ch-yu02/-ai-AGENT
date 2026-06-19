"""课堂会话管理器 —— 会话生命周期的唯一真相源。

SessionManager 是 MVP 阶段后端内存中的会话注册中心，负责：
  1. 创建课堂会话（前端发起请求 → 生成 LectureSession）
  2. 查询会话（按 session_id 检索，找不到则为 API 层抛出领域异常）
  3. 结束会话（状态转换 "recording" → "ended"，幂等）
  4. 门控检查（确保只有 recording 状态的会话才能接收实时事件）

设计要点
--------
- **内存存储**：MVP 阶段使用 dict 在内存中管理。后续 LocalStorage
  或数据库接入时，可在 SessionManager 内部切换，对 API 路由层的
  调用方式保持透明。
- **领域异常**：SessionManager 不关心 HTTP 状态码。它抛出
  SessionNotFoundError / SessionConflictError，由路由层映射到
  404 / 409 响应。
- **单例**：模块级 session_manager 实例是进程内唯一入口。测试时
  可通过 :meth:`SessionManager.clear` 重置。
- **结束后可读**：ended 会话保留在 _sessions 字典中，前端在课堂
  结束后仍可查询标题、笔记等只读数据。
"""

from backend.app.models import (
    LectureSession,
    StartSessionRequest,
    new_session_id,
    utc_now_iso,
)


# ── 领域异常 ────────────────────────────────────────────────────
# 这些异常是纯领域层面的语义，不携带任何 HTTP 状态码。
# API 路由层在 except 块中将它们映射到对应的 HTTP 响应。


class SessionNotFoundError(Exception):
    """Raised when a route or manager asks for an unknown classroom session.

    触发场景：
      - 前端用无效/过期的 session_id 调用 API
      - WebSocket 连接携带不存在的 session_id

    API 层映射：404 Not Found
    """


class SessionConflictError(Exception):
    """Raised when an operation conflicts with the current session state.

    触发场景：
      - 尝试向已结束的会话上报事件（require_recording 拒绝）
      - 后续可能扩展：重复启动同一个硬件设备上的会话等冲突

    API 层映射：409 Conflict
    """


# ── 会话管理器 ──────────────────────────────────────────────────


class SessionManager:
    """Owns the classroom session lifecycle.

    This manager is the single in-memory source of truth for sessions during the
    MVP phase. Storage can later hydrate this manager at startup and persist
    ended sessions without changing the API route surface.

    职责边界
    --------
    SessionManager 只负责会话的**生命周期状态**（创建 / 查询 /
    结束 / 门控）。它不负责：
      - 事件处理（由 ContextManager 等模块负责）
      - 知识图谱构建（由 KnowledgeGraphManager 负责）
      - 持久化（后续接入 LocalStorage / 数据库，对调用方透明）
    """

    def __init__(self) -> None:
        # Keyed by session_id. Values include both recording and ended sessions
        # so callers can still fetch metadata after a class is closed.
        self._sessions: dict[str, LectureSession] = {}

    # ── 创建 ─────────────────────────────────────────────────

    def create_session(self, request: StartSessionRequest) -> LectureSession:
        """Create a new recording session from the frontend request payload.

        调用时机：POST /api/sessions → API 路由调用此方法。

        流程：
          1. 用 new_session_id() 生成全局唯一 ID
          2. 组装 LectureSession，status 固定为 "recording"
          3. 存入 _sessions 字典
          4. 返回完整会话对象
        """
        session = LectureSession(
            session_id=new_session_id(),
            title=request.title,
            course=request.course,
            teacher=request.teacher,
            start_time=utc_now_iso(),
            status="recording",
            language=request.language,
            created_by=request.created_by,
            device_id=request.device_id,
        )
        self._sessions[session.session_id] = session
        return session

    # ── 查询 ─────────────────────────────────────────────────

    def get_session(self, session_id: str) -> LectureSession:
        """Return a session or raise a domain error for the API layer to map.

        这是所有读路径的统一入口。API 路由、WebSocket 处理器及其
        他核心模块都通过它获取会话引用，保证会话存在性检查一致。

        Raises:
            SessionNotFoundError: session_id 不存在。
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return session

    def update_session_metadata(
        self,
        session_id: str,
        updates: dict[str, object],
    ) -> LectureSession:
        """Update mutable session metadata for recording or ended sessions."""
        session = self.get_session(session_id)
        if not updates:
            return session

        updated_session = session.model_copy(update=updates)
        self._sessions[session_id] = updated_session
        return updated_session

    # ── 状态转换 ─────────────────────────────────────────────

    def end_session(self, session_id: str) -> LectureSession:
        """Mark a session as ended.

        Ending is idempotent: calling this for an already ended session returns
        the existing ended metadata. That makes retries from the frontend safe.

        幂等设计的原因：前端可能因网络不稳定而重复发送结束请求。
        直接返回已有的结束结果，不抛异常、不重复写入。
        """
        session = self.get_session(session_id)
        if session.status == "ended":
            return session

        # 使用 Pydantic model_copy 创建新对象，保持不可变语义
        ended_session = session.model_copy(
            update={
                "status": "ended",
                "end_time": utc_now_iso(),
            }
        )
        self._sessions[session_id] = ended_session
        return ended_session

    # ── 门控 ─────────────────────────────────────────────────

    def require_recording(self, session_id: str) -> LectureSession:
        """Return a session only if it can still accept realtime events.

        这是 get_session 的加强版——不仅检查存在性，还验证状态。
        调用时机：POST /api/events 等需要向会话写入数据的入口。

        Raises:
            SessionConflictError: 会话已结束，无法接收新数据。
        """
        session = self.get_session(session_id)
        if session.status != "recording":
            raise SessionConflictError(f"Session is not recording: {session_id}")
        return session

    # ── 批量操作 ─────────────────────────────────────────────

    def list_sessions(self) -> list[LectureSession]:
        """Return all known sessions.

        Future extension: support pagination and filtering once history reading
        moves from in-memory data to LocalStorage.

        MVP 阶段为全量返回，仅用于 Demo 列表页。
        """
        return list(self._sessions.values())

    def clear(self) -> None:
        """Reset in-memory sessions for tests and local demo restarts.

        仅用于测试和本地 Demo 重置，不应在生产代码中调用。
        """
        self._sessions.clear()


# ── 模块级单例 ──────────────────────────────────────────────────
# 整个后端进程共享一个 SessionManager 实例。各模块通过
# from backend.app.core import session_manager 获取。

session_manager = SessionManager()
"""SessionManager 的全局单例实例。"""
