"""Backward-compatible re-exports for route schemas.

New code should import shared contracts from ``backend.app.models``. This module
stays in place so existing route imports continue to work while the backend is
being split into API, core, and storage layers.
"""

from backend.app.models import (  # noqa: F401
    EventAcceptedResponse,
    GraphPatch,
    ImageCapture,
    KnowledgeEdge,
    KnowledgeExtraction,
    KnowledgeNode,
    KnowledgeTree,
    LectureSession,
    RealtimeEvent,
    SessionStatus,
    StartSessionRequest,
    TranscriptSegment,
    WebSocketMessage,
    new_session_id,
    utc_now_iso,
)
