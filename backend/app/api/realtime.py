"""Compatibility layer for the old API-level realtime import path.

WebSocket connection management now lives in ``backend.app.core.websocket_manager``.
This module re-exports the core manager so older route imports continue to work
while the codebase migrates toward core managers.
"""

from backend.app.core.websocket_manager import (  # noqa: F401
    BroadcastResult,
    WebSocketManager,
    connection_manager,
    websocket_manager,
)
