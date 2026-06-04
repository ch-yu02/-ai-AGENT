"""实时事件接收 API —— 课堂数据流的唯一入口。

本模块是 EDU-Mate 后端 **最重要的路由模块**。所有课堂实时数据
（ASR 语音识别文本、摄像头/截图画面、端侧 SLM 知识提取结果）都
通过 ``POST /api/events`` 进入后端，经过以下管道处理：

::

  前端/端侧 SDK
      │  POST /api/events  (RealtimeEvent)
      ▼
  events.py  receive_event()
      │
      ├── 1. SessionManager.require_recording()   ← 门控检查
      │     会话不存在 → 404；会话已结束 → 409
      │
      ├── 2. app_state.events[sid].append(event)   ← 临时暂存（向后兼容，后续移除）
      │
      ├── 3. ContextManager.handle_event()          ← 解析并更新课堂上下文
      │     ├─ transcript.segment  → 追加到 transcript / timeline
      │     ├─ image.capture      → 追加到 visuals / timeline
      │     └─ knowledge.extraction → 追加到 knowledge_extractions / timeline
      │     └─ 未知 event_type   → 400
      │
      ├── 4. KnowledgeGraphManager.handle_event()   ← 更新知识图谱
      │     └─ 仅处理 knowledge.extraction 事件
      │     └─ 非知识类事件返回 None（跳过图谱更新）
      │
      ├── 5. ConnectionManager.broadcast()           ← 推送 WebSocket
      │     └─ 广播 event.received 消息（含上下文更新摘要 + 图谱增量补丁）
      │
      └── 6. 返回 EventAcceptedResponse（HTTP 202）
"""

from fastapi import APIRouter, HTTPException, status

from backend.app.core import (
    ContextEventError,
    ContextNotFoundError,
    KnowledgeGraphEventError,
    KnowledgeGraphNotFoundError,
    SessionConflictError,
    SessionNotFoundError,
    context_manager,
    knowledge_graph_manager,
    session_manager,
)
from backend.app.models import EventAcceptedResponse, RealtimeEvent, WebSocketMessage

from .realtime import connection_manager
from .state import app_state


router = APIRouter(prefix="/events", tags=["events"])
"""事件路由实例，所有端点挂载在 ``/events`` 路径前缀下。"""


@router.post("", response_model=EventAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def receive_event(event: RealtimeEvent) -> EventAcceptedResponse:
    """接收并处理一条课堂实时事件，返回 HTTP 202 确认。

    每秒可能收到数十条事件（ASR 片段、截图、知识提取），因此这个端点
    必须轻量快速。所有处理都在内存中进行，业务逻辑委托给下游 Manager。

    请求体示例
    ----------
    ::

        {
            "session_id": "sess_abc123",
            "event_type": "transcript.segment",
            "payload": {
                "text": "牛顿第二定律指出，物体的加速度与合外力成正比",
                "start_ts": 120.5,
                "end_ts": 124.3,
                "speaker": "teacher",
                "segment_id": "seg_001"
            }
        }

    错误处理
    --------
    =====================  ======  ==========================================
    场景                    状态码  说明
    =====================  ======  ==========================================
    会话 ID 不存在          404    调用 ``session_manager.require_recording``
    会话已结束              409    已结束的课堂无法接收新事件
    上下文不存在            404    调用 ``context_manager.handle_event``
    事件格式错误            400    ContextManager 或 KnowledgeGraphManager 抛出异常
    知识图谱不存在          404    调用 ``knowledge_graph_manager.handle_event``
    =====================  ======  ==========================================
    """
    # ── 步骤 1：门控检查 ──────────────────────────────────────────
    # 只有 "recording" 状态的会话才能接收实时事件。已结束的课堂不可再写。
    try:
        session_manager.require_recording(event.session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except SessionConflictError:
        raise HTTPException(status_code=409, detail="Session is not recording")

    # ── 步骤 2：临时暂存（向后兼容） ─────────────────────────────
    # app_state 是 MVP 阶段的临时事件缓冲区。后续 Manager 层（ContextManager、
    # KnowledgeGraphManager）已就绪，但这行保留以保证旧测试和临时调试路径
    # 仍然可用。等 LocalStorage 就绪后会移除。
    app_state.events[event.session_id].append(event)
    event_count = len(app_state.events[event.session_id])

    # ── 步骤 3：更新课堂上下文 ────────────────────────────────────
    # ContextManager 根据 event_type 将 payload 解析为对应的结构化模型：
    #   - "transcript.segment"   → TranscriptSegment → 追加到 transcript + timeline
    #   - "image.capture"        → ImageCapture      → 追加到 visuals + timeline
    #   - "knowledge.extraction" → KnowledgeExtraction → 追加到 knowledge_extractions + timeline
    # 返回 ContextUpdate 摘要（含新增的 timeline_item、各数据源计数）。
    try:
        context_update = context_manager.handle_event(event)
    except ContextNotFoundError:
        raise HTTPException(status_code=404, detail="Context not found")
    except ContextEventError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── 步骤 4：更新知识图谱 ──────────────────────────────────────
    # KnowledgeGraphManager 只处理 "knowledge.extraction" 事件。
    # 字幕和图片事件会返回 None，表示没有图谱变更需要推送。
    # 返回值 GraphPatch 包含本次增量操作（add_node / update_node / add_edge）
    # 和版本号，前端可以直接应用到本地图谱缓存。
    try:
        graph_patch = knowledge_graph_manager.handle_event(event)
    except KnowledgeGraphNotFoundError:
        raise HTTPException(status_code=404, detail="Knowledge graph not found")
    except KnowledgeGraphEventError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── 步骤 5：WebSocket 广播 ─────────────────────────────────────
    # 将处理结果推送给该 session 的所有已连接前端。消息包含：
    #   - event_type / payload：原始事件信息（供前端判断事件种类）
    #   - event_count：该 session 累计事件数（可用于检测丢包）
    #   - context_update：ContextManager 处理后的上下文变更摘要
    #   - graph_patch：KnowledgeGraphManager 生成的图谱增量补丁
    await connection_manager.broadcast(
        event.session_id,
        WebSocketMessage(
            type="event.received",
            session_id=event.session_id,
            data={
                "event_type": event.event_type,
                "payload": event.payload,
                "event_count": event_count,
                "context_update": context_update.model_dump(),
                "graph_patch": graph_patch.model_dump() if graph_patch else None,
            },
        ),
    )

    # ── 步骤 6：返回确认 ──────────────────────────────────────────
    # 使用 HTTP 202 Accepted 表示事件已接收并开始处理，而非同步完成。
    # 前端收到此响应即可释放事件发送缓冲区，不需要等待后续广播到达。
    return EventAcceptedResponse(
        status="accepted",
        session_id=event.session_id,
        event_type=event.event_type,
        event_count=event_count,
    )
