from fastapi import WebSocket

from backend.app.models import WebSocketMessage


class ConnectionManager:
    """Track WebSocket clients by classroom session.

    Future extension: add heartbeat/ping handling, stale connection cleanup,
    and per-client replay of the latest transcript/timeline when connecting.
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.setdefault(session_id, []).append(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        connections = self.active_connections.get(session_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self.active_connections.pop(session_id, None)

    async def broadcast(self, session_id: str, message: WebSocketMessage) -> None:
        # Copy the list before iterating so disconnects during send do not mutate
        # the collection we are looping over.
        connections = list(self.active_connections.get(session_id, []))
        for websocket in connections:
            await websocket.send_json(message.model_dump())


connection_manager = ConnectionManager()
