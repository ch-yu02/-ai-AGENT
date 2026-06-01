from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


SessionStatus = Literal["recording", "ended"]


def new_session_id() -> str:
    """Generate readable local session IDs for demo, logs, and file paths.

    Future extension: SessionManager may accept IDs from hardware or storage
    once those modules become the source of truth.
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
