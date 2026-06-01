from fastapi import APIRouter, HTTPException, status

from .realtime import connection_manager
from .schemas import EventAcceptedResponse, RealtimeEvent, WebSocketMessage
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
    session = app_state.sessions.get(event.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "recording":
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
