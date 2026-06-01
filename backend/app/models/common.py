from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel


SourceRefType = Literal["segment", "visual", "event"]


def utc_now_iso() -> str:
    """Return a timezone-aware ISO timestamp for persisted API data.

    Keep timestamps canonical in UTC inside the backend. Local classroom time can
    be derived when rendering or exporting notes.
    """
    return datetime.now(timezone.utc).isoformat()


class SourceRef(BaseModel):
    """Reference from derived data back to the raw classroom source."""

    type: SourceRefType
    id: str
    ts: float | None = None
