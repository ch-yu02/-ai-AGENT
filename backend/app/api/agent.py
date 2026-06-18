"""课堂 Agent 的 HTTP 路由。

本模块保持 API 层“薄路由”原则：
- 请求/响应模型来自 ``backend.app.agent.schemas``。
- 业务逻辑全部委托给 ``ClassroomAgent``。
- 这里只做领域异常到 HTTP 状态码的映射。

这样后续给 Agent 接 LlamaIndex、Cloud LLM 或更多 Skill 时，不需要把复杂逻辑
搬进路由文件。
"""

import asyncio
import time

from fastapi import APIRouter, HTTPException

from backend.app.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentSessionNotFoundError,
    GlobalSearchRequest,
    GlobalSearchResponse,
    NotesKnowledgeTreeUpdateRequest,
    NotesKnowledgeTreeUpdateResponse,
    classroom_agent,
    global_search_service,
    markdown_knowledge_tree_agent,
)
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
    websocket_manager,
)
from backend.app.models import ContextUpdate, GraphPatch, RealtimeEvent, WebSocketMessage


router = APIRouter(prefix="/agent", tags=["agent"])
"""Agent API 路由，当前只有自然语言入口 ``POST /agent/chat``。"""


def _notes_agent_log(message: str) -> None:
    """Emit a compact backend log line for notes-driven graph updates."""
    print(f"[notes-agent] {message}", flush=True)


@router.post("/chat", response_model=AgentChatResponse)
async def chat(request: AgentChatRequest) -> AgentChatResponse:
    """针对一次 prompt 运行课堂 Agent。

    404 的语义是“内存和本地历史文件都找不到这个 session”。如果 session 存在
    但课堂资料不足，Agent 会正常返回 200，并在 ``warnings`` 中说明数据不足。
    """
    try:
        return classroom_agent.chat(request)
    except AgentSessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/search", response_model=GlobalSearchResponse)
async def search(request: GlobalSearchRequest) -> GlobalSearchResponse:
    """跨已保存历史课堂搜索课堂资料。

    这个接口是 Phase 7 的第一版“长期记忆”入口。它只读取本地已保存历史课堂，
    不搜索正在录制但尚未结束保存的内存课堂。这样用户得到的结果都能对应到
    ``data/sessions/{session_id}`` 中稳定存在的课后档案。
    """
    return global_search_service.search(request)


@router.post(
    "/knowledge-tree/update-from-notes",
    response_model=NotesKnowledgeTreeUpdateResponse,
)
async def update_knowledge_tree_from_notes(
    request: NotesKnowledgeTreeUpdateRequest,
) -> NotesKnowledgeTreeUpdateResponse:
    """Use a structured Markdown note snapshot to update the live knowledge tree.

    This endpoint is meant for the local WhisperLive/Qwen note pipeline. The
    script uploads the current Markdown notes every N seconds; the backend keeps
    cloud credentials private, asks the configured cloud LLM for a grounded
    knowledge-tree extraction, and then reuses the existing ``knowledge.extraction``
    event path so the frontend receives the usual graph patch.
    """
    try:
        session_manager.require_recording(request.session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except SessionConflictError:
        raise HTTPException(status_code=409, detail="Session is not recording")

    try:
        context_manager.get_context(request.session_id)
    except ContextNotFoundError:
        raise HTTPException(status_code=404, detail="Context not found")

    try:
        knowledge_graph = knowledge_graph_manager.get_graph(request.session_id)
    except KnowledgeGraphNotFoundError:
        raise HTTPException(status_code=404, detail="Knowledge graph not found")

    started_at = time.monotonic()
    recent_count = len(request.recent_source_segments or request.source_segments)
    _notes_agent_log(
        "start "
        f"session={request.session_id} snapshot={request.snapshot_id} "
        f"seq={request.sequence} status={request.update_status} "
        f"markdown_chars={len(request.markdown)} "
        f"source_segments={len(request.source_segments)} "
        f"recent_segments={recent_count}"
    )

    # Cloud LLM calls use the blocking urllib client. Run extraction in a worker
    # thread so a slow DeepSeek request does not block /events transcript posts
    # and WebSocket subtitle updates on the FastAPI event loop.
    graph_snapshot = knowledge_graph.model_copy(deep=True)
    result = await asyncio.to_thread(
        markdown_knowledge_tree_agent.extract,
        request,
        graph_snapshot,
    )
    if result.failed:
        elapsed = time.monotonic() - started_at
        _notes_agent_log(
            "failed "
            f"session={request.session_id} snapshot={request.snapshot_id} "
            f"elapsed={elapsed:.2f}s warnings={list(result.warnings)}"
        )
        return NotesKnowledgeTreeUpdateResponse(
            status="failed",
            session_id=request.session_id,
            snapshot_id=request.snapshot_id,
            markdown_hash=result.markdown_hash,
            warnings=list(result.warnings),
        )

    if result.extraction is None:
        if result.markdown_hash:
            markdown_knowledge_tree_agent.remember_processed(
                request.session_id,
                result.markdown_hash,
            )
        elapsed = time.monotonic() - started_at
        _notes_agent_log(
            "skipped "
            f"session={request.session_id} snapshot={request.snapshot_id} "
            f"elapsed={elapsed:.2f}s warnings={list(result.warnings)}"
        )
        return NotesKnowledgeTreeUpdateResponse(
            status="skipped",
            session_id=request.session_id,
            snapshot_id=request.snapshot_id,
            markdown_hash=result.markdown_hash,
            warnings=list(result.warnings),
        )

    event = RealtimeEvent(
        session_id=request.session_id,
        event_type="knowledge.extraction",
        payload=result.extraction.model_dump(),
    )
    try:
        context_update = context_manager.handle_event(event)
        graph_patch = knowledge_graph_manager.handle_event(event)
    except ContextEventError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KnowledgeGraphEventError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (ContextNotFoundError, KnowledgeGraphNotFoundError):
        raise HTTPException(status_code=404, detail="Session graph context not found")

    markdown_knowledge_tree_agent.remember_processed(
        request.session_id,
        result.markdown_hash,
    )
    await _broadcast_notes_knowledge_update(
        event=event,
        context_update=context_update,
        graph_patch=graph_patch,
    )
    operation_count = len(graph_patch.operations) if graph_patch else 0
    elapsed = time.monotonic() - started_at
    _notes_agent_log(
        f"{'applied' if operation_count else 'skipped'} "
        f"session={request.session_id} snapshot={request.snapshot_id} "
        f"elapsed={elapsed:.2f}s ops={operation_count} "
        f"extraction={result.extraction.extraction_id} warnings={list(result.warnings)}"
    )
    return NotesKnowledgeTreeUpdateResponse(
        status="applied" if operation_count else "skipped",
        session_id=request.session_id,
        snapshot_id=request.snapshot_id,
        markdown_hash=result.markdown_hash,
        extraction_id=result.extraction.extraction_id,
        graph_patch_operations=operation_count,
        warnings=list(result.warnings),
    )


async def _broadcast_notes_knowledge_update(
    *,
    event: RealtimeEvent,
    context_update: ContextUpdate,
    graph_patch: GraphPatch | None,
) -> None:
    """Broadcast the standard realtime envelope for notes-driven graph updates."""
    event_count = (
        context_update.transcript_count
        + context_update.visual_count
        + context_update.knowledge_extraction_count
    )
    await websocket_manager.broadcast(
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
