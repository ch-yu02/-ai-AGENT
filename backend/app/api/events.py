from fastapi import APIRouter, HTTPException, status

from backend.app.core import (
    SessionConflictError,
    SessionNotFoundError,
    session_manager,
)
from backend.app.models import EventAcceptedResponse, RealtimeEvent, WebSocketMessage

from .realtime import connection_manager
from .state import app_state


router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def receive_event(event: RealtimeEvent) -> EventAcceptedResponse:
    """Accept one realtime event from ASR/OCR/VLM/SLM or a mock sender.

    Future extension:
    - transcript.segment -> ContextManager transcript and timeline update
    - image.capture -> ContextManager visual/timeline update
    - knowledge.extraction -> KnowledgeGraphManager graph patch
    - every derived update -> WebSocket push using frontend-specific types
    """
    try:
        session_manager.require_recording(event.session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except SessionConflictError:
        raise HTTPException(status_code=409, detail="Session is not recording")

    # For the MVP route layer, keep the raw event. The later manager layer should
    # produce normalized transcript/timeline/graph state from this same envelope.
    app_state.events[event.session_id].append(event)
    event_count = len(app_state.events[event.session_id])

    await connection_manager.broadcast(
        event.session_id,
        WebSocketMessage(
            type="event.received",
            session_id=event.session_id,
            data={
                "event_type": event.event_type,
                "payload": event.payload,
                "event_count": event_count,
            },
        ),
    )

    return EventAcceptedResponse(
        status="accepted",
        session_id=event.session_id,
        event_type=event.event_type,
        event_count=event_count,
    )
