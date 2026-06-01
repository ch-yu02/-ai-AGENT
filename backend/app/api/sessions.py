from fastapi import APIRouter, HTTPException, status

from backend.app.models import (
    LectureSession,
    StartSessionRequest,
    WebSocketMessage,
    new_session_id,
    utc_now_iso,
)

from .realtime import connection_manager
from .state import app_state


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/start", response_model=LectureSession, status_code=status.HTTP_201_CREATED)
async def start_session(request: StartSessionRequest) -> LectureSession:
    """Create a classroom session and notify realtime subscribers.

    Future extension: move creation rules into SessionManager, initialize
    ContextManager/KnowledgeGraphManager, and create the session data directory.
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
    app_state.sessions[session.session_id] = session

    await connection_manager.broadcast(
        session.session_id,
        WebSocketMessage(
            type="session.started",
            session_id=session.session_id,
            data={"session": session.model_dump()},
        ),
    )
    return session


@router.get("/{session_id}", response_model=LectureSession)
async def get_session(session_id: str) -> LectureSession:
    """Return one session by ID.

    Future extension: if the session is not in memory, fall back to LocalStorage
    so ended classes can still be opened after a backend restart.
    """
    session = app_state.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/end", response_model=LectureSession)
async def end_session(session_id: str) -> LectureSession:
    """Mark a classroom session as ended and notify realtime subscribers.

    Future extension: trigger LocalStorage persistence here:
    metadata.json, transcript.md, timeline.json, and knowledge_graph.json.
    """
    session = app_state.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "ended":
        return session

    ended_session = session.model_copy(
        update={
            "status": "ended",
            "end_time": utc_now_iso(),
        }
    )
    app_state.sessions[session_id] = ended_session

    await connection_manager.broadcast(
        session_id,
        WebSocketMessage(
            type="session.ended",
            session_id=session_id,
            data={"session": ended_session.model_dump()},
        ),
    )
    return ended_session
