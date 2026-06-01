from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.models import WebSocketMessage

from .realtime import connection_manager


router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{session_id}")
async def session_updates(websocket: WebSocket, session_id: str) -> None:
    """Subscribe one frontend client to realtime updates for a session.

    Future extension: validate that the session exists before accepting, then
    send a snapshot of current transcript/timeline/knowledge graph immediately
    after connection.
    """
    await connection_manager.connect(session_id, websocket)
    await websocket.send_json(
        WebSocketMessage(
            type="ws.connected",
            session_id=session_id,
            data={"message": "connected"},
        ).model_dump()
    )

    try:
        # Keep the socket open. Incoming client messages are ignored for now,
        # but this gives us a place to add ping, cursor sync, or commands later.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connection_manager.disconnect(session_id, websocket)
