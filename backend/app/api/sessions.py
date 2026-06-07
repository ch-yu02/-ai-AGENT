"""课堂会话 REST API —— 会话生命周期的 HTTP 入口。

本模块提供课堂会话的完整生命周期管理：创建、查询、结束。
每个写操作（创建/结束）都会通过 ``WebSocketManager`` 向 WebSocket
订阅者广播状态变更，保证前端实时感知会话状态。

端点一览
--------
=======================  ======  ==========================================
端点                      方法    用途
=======================  ======  ==========================================
``/sessions/start``       POST    创建新课堂会话，返回 LectureSession
``/sessions/{id}``        GET     按 ID 查询会话元数据
``/sessions/{id}/end``    POST    结束会话，状态 recording → ended
=======================  ======  ==========================================

分层约定
--------
本模块遵循 api 层的统一分层约定：

- **core 层**（SessionManager）抛出领域异常（SessionNotFoundError）
- **api 层**（本模块）将领域异常映射为 HTTP 状态码（404）

未来扩展
--------
- GET /sessions: 列表查询（分页），用于历史课堂浏览
- 持久化回退：GET 找不到内存中的会话时，尝试从 LocalStorage 读取
- end_session 触发持久化：metadata.json, transcript.md, timeline.json,
  knowledge_graph.json 写入磁盘
"""

from fastapi import APIRouter, HTTPException, status

from backend.app.core import (
    ContextNotFoundError,
    KnowledgeGraphNotFoundError,
    SessionNotFoundError,
    context_manager,
    knowledge_graph_manager,
    session_manager,
    websocket_manager,
)
from backend.app.models import (
    LectureSession,
    SessionDeleteResponse,
    SessionHistoryDetail,
    SessionHistoryListResponse,
    StartSessionRequest,
    WebSocketMessage,
)
from backend.app.skills import SummarizerSkill, TodoDetectiveSkill
from backend.app.storage import local_storage


router = APIRouter(prefix="/sessions", tags=["sessions"])
"""会话路由实例，所有端点挂载在 ``/sessions`` 路径前缀下。"""


# ── 创建会话 ──────────────────────────────────────────────────────


@router.post("/start", response_model=LectureSession, status_code=status.HTTP_201_CREATED)
async def start_session(request: StartSessionRequest) -> LectureSession:
    """创建新课堂会话并通知所有 WebSocket 订阅者。

    请求体示例
    ----------
    ::

        {
            "title": "牛顿力学导论",
            "course": "PHYS101",
            "teacher": "张老师",
            "language": "zh-CN",
            "created_by": "teacher-001",
            "device_id": "dev-abc123"
        }

    处理流程
    --------
    1. 调用 ``session_manager.create_session()`` 在内存中创建会话，
       自动生成唯一 session_id，状态固定为 ``"recording"``
    2. 通过 ``websocket_manager.broadcast()`` 向该 session 的所有
       WebSocket 订阅者推送 ``session.started`` 消息
    3. 返回完整的 ``LectureSession`` 对象（HTTP 201）

    未来扩展
    --------
    - 在 LocalStorage 中创建会话数据目录
    """
    session = session_manager.create_session(request)
    context_manager.start_session(session.session_id)
    knowledge_graph_manager.start_session(session.session_id)

    # 创建成功后立即广播，此时通常还没有 WebSocket 订阅者，
    # 但 broadcast 对空列表是安全的（直接跳过遍历）
    await websocket_manager.broadcast(
        session.session_id,
        WebSocketMessage(
            type="session.started",
            session_id=session.session_id,
            data={"session": session.model_dump()},
        ),
    )
    return session


# ── 查询会话 ──────────────────────────────────────────────────────


@router.get("/{session_id}", response_model=LectureSession)
async def get_session(session_id: str) -> LectureSession:
    """按 session_id 查询单个课堂会话的元数据。

    这是前端加载课堂详情页的主要入口。返回的数据包含标题、课程名、
    教师、开始时间、状态等元信息。

    错误处理
    --------
    将 core 层的 ``SessionNotFoundError`` 映射为 HTTP 404，
    前端可据此展示"课堂不存在或已过期"。

    未来扩展
    --------
    若 session 不在内存中（如后端重启后已结束的课堂），
    尝试从 LocalStorage 回退读取，使历史课堂仍可被查询。
    """
    try:
        return session_manager.get_session(session_id)
    except SessionNotFoundError:
        try:
            return LectureSession.model_validate(local_storage.read_metadata(session_id))
        except (FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail="Session not found")


@router.get("", response_model=SessionHistoryListResponse)
async def list_history_sessions() -> SessionHistoryListResponse:
    """读取已保存的历史课堂列表。

    返回本地 ``data/sessions`` 下已落盘课堂的元信息摘要。课堂仍在录制但
    尚未结束保存时不会出现在这个历史列表中。
    """
    return SessionHistoryListResponse(sessions=local_storage.list_sessions())


@router.get("/{session_id}/history", response_model=SessionHistoryDetail)
async def get_history_session(session_id: str) -> SessionHistoryDetail:
    """读取一节已保存课堂的课后历史内容。

    包含 metadata、transcript.md、timeline.json 和 knowledge_graph.json，
    供前端历史回放、课后总结和技能模块消费。
    """
    try:
        return local_storage.read_session(session_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Saved session not found")


@router.delete("/{session_id}/history", response_model=SessionDeleteResponse)
async def delete_history_session(session_id: str) -> SessionDeleteResponse:
    """删除一节已保存课堂的本地历史数据。

    只删除 ``data/sessions/{session_id}`` 下的课后档案文件，不修改
    SessionManager 中仍保留的内存 session。这样删除历史数据不会干扰当前
    运行中的课堂生命周期，但历史列表和详情将不再能读取该 session。
    """
    try:
        deleted = local_storage.delete_session(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    if not deleted:
        raise HTTPException(status_code=404, detail="Saved session not found")

    return SessionDeleteResponse(status="deleted", session_id=session_id)


# ── 结束会话 ──────────────────────────────────────────────────────


@router.post("/{session_id}/end", response_model=LectureSession)
async def end_session(session_id: str) -> LectureSession:
    """结束课堂会话并通知所有 WebSocket 订阅者。

    幂等性
    ------
    对已结束的会话再次调用此端点不会报错——``SessionManager.end_session()``
    幂等地返回已有的结束结果。这让前端可以安全重试（网络不稳定时重复发送
    结束请求不会产生副作用）。

    处理流程
    --------
    1. 调用 ``session_manager.end_session()`` 将状态从 ``"recording"``
       转为 ``"ended"``，同时记录 ``end_time``
    2. 从 ContextManager / KnowledgeGraphManager 读取课堂内存状态
    3. 调用 LocalStorage 保存 metadata / transcript / timeline / graph
    4. 通过 ``websocket_manager.broadcast()`` 推送 ``session.ended``，
       前端收到后可以停止事件上报、展示课堂总结等
    5. 返回更新后的 ``LectureSession`` 对象

    未来扩展
    --------
    触发 LocalStorage 持久化，将以下文件写入会话数据目录：
    - ``metadata.json`` —— 会话元信息
    - ``transcript.md`` —— 完整课堂文字记录
    - ``timeline.json`` —— 时间轴事件列表
    - ``knowledge_graph.json`` —— 知识图谱节点与边
    """
    try:
        context = context_manager.get_context(session_id)
    except ContextNotFoundError:
        raise HTTPException(status_code=404, detail="Context not found")

    try:
        knowledge_graph = knowledge_graph_manager.get_graph(session_id)
    except KnowledgeGraphNotFoundError:
        raise HTTPException(status_code=404, detail="Knowledge graph not found")

    try:
        ended_session = session_manager.end_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    storage_result = local_storage.save_session(
        session=ended_session,
        context=context,
        knowledge_graph=knowledge_graph,
    )
    post_class_files = _generate_and_save_post_class_artifacts(
        session_id=session_id,
        context=context,
        knowledge_graph=knowledge_graph,
    )

    await websocket_manager.broadcast(
        session_id,
        WebSocketMessage(
            type="session.ended",
            session_id=session_id,
            data={
                "session": ended_session.model_dump(),
                "storage": {
                    "session_dir": str(storage_result.session_dir),
                    "files": {
                        name: str(path)
                        for name, path in storage_result.files.items()
                    },
                    "post_class_files": {
                        name: str(path)
                        for name, path in post_class_files.items()
                    },
                },
            },
        ),
    )
    return ended_session


def _generate_and_save_post_class_artifacts(
    session_id: str,
    context,
    knowledge_graph,
) -> dict[str, object]:
    """结束课堂时自动生成并保存规则版“基础课后产物”。

    这里刻意只自动生成 summary.md 和 todos.json：
    - 总结、待办属于“结束课堂后通常就应该有”的基础学习材料；
    - quiz 属于主动练习场景，必须由用户在 AgentPanel 中点击“生成自测”或
      输入出题类 prompt 后再生成，避免系统在用户没有需求时提前写入题目。

    ``save_agent_artifacts()`` 仍会额外写出 agent_artifacts.json。这个快照只
    记录本次自动生成的 summary/todos，因此结束课堂时不会出现 quiz.json。

    这里仍然通过 LocalStorage 写文件，保持“API 不直接拼路径、不直接写磁盘”
    的存储边界。
    """
    skill_results = [
        SummarizerSkill().run(session_id, context, knowledge_graph),
        TodoDetectiveSkill().run(session_id, context, knowledge_graph),
    ]
    artifacts = [
        {
            "type": result.artifact.type,
            "title": result.artifact.title,
            "content": result.artifact.content,
        }
        for result in skill_results
        if result.artifact is not None
    ]
    return local_storage.save_agent_artifacts(session_id, artifacts)
