from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


SessionStatus = Literal["recording", "ended"]


def utc_now_iso() -> str:
    """Return an ISO timestamp for API responses and in-memory events.

    Future extension: if the frontend needs local classroom time, convert only
    at presentation/export boundaries and keep the backend canonical timestamp
    timezone-aware.
    """
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    """Generate readable local session IDs for demo and file paths.

    Future extension: SessionManager may accept IDs from an external device or
    use database-generated IDs when persistent storage is introduced.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = uuid4().hex[:8]
    return f"lec_{timestamp}_{suffix}"


class StartSessionRequest(BaseModel):
    """Payload used by the frontend to start a classroom session."""

    title: str = Field(default="未命名课堂")
    course: str | None = None
    teacher: str | None = None
    language: str = Field(default="zh-CN")
    created_by: str = Field(default="student")
    device_id: str | None = None


class LectureSession(BaseModel):
    """Public classroom session model shared by HTTP, WebSocket, and storage."""

    session_id: str
    title: str
    course: str | None = None
    teacher: str | None = None
    start_time: str
    end_time: str | None = None
    status: SessionStatus
    language: str
    created_by: str
    device_id: str | None = None


class RealtimeEvent(BaseModel):
    """Generic input envelope for algorithm and mock realtime events.

    The event-specific fields intentionally live under payload for now. Later,
    this can become a discriminated union of TranscriptSegment, ImageCapture,
    and KnowledgeExtraction once those models stabilize with the algorithm team.
    """

    session_id: str
    event_type: str = Field(
        examples=["transcript.segment", "image.capture", "knowledge.extraction"]
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class EventAcceptedResponse(BaseModel):
    """Small acknowledgment returned after an event enters the backend."""

    status: Literal["accepted"]
    session_id: str
    event_type: str
    event_count: int


class WebSocketMessage(BaseModel):
    """Message envelope pushed from backend to frontend subscribers."""

    type: str
    session_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
