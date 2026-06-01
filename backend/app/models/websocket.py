from typing import Any

from pydantic import BaseModel, Field

from .common import utc_now_iso


class WebSocketMessage(BaseModel):
    """Message envelope pushed from backend to frontend subscribers."""

    type: str
    session_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
