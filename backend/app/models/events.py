from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import utc_now_iso


EventType = Literal[
    "transcript.segment",
    "image.capture",
    "knowledge.extraction",
]


class TranscriptSegment(BaseModel):
    """Realtime ASR text segment from Whisper or another speech recognizer."""

    segment_id: str
    session_id: str
    start_ts: float
    end_ts: float
    text: str
    speaker: str | None = "teacher"
    confidence: float | None = None
    is_final: bool = True
    source: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class ImageCapture(BaseModel):
    """Image or visual artifact captured during the classroom session."""

    image_id: str
    session_id: str
    capture_ts: float
    upload_time: str = Field(default_factory=utc_now_iso)
    image_path: str
    source: str | None = None
    image_type: str | None = None
    status: str = "processed"
    ocr_text: str | None = None
    caption: str | None = None


class KnowledgeEntity(BaseModel):
    """Entity extracted by the local SLM from text or visual context."""

    entity_id: str | None = None
    name: str
    type: str = "concept"
    description: str | None = None


class KnowledgeRelation(BaseModel):
    """Relationship extracted between two knowledge entities."""

    source: str
    target: str
    relation: str


class KnowledgeExtraction(BaseModel):
    """Structured extraction result produced by the local SLM."""

    extraction_id: str
    session_id: str
    source_segment_ids: list[str] = Field(default_factory=list)
    source_visual_ids: list[str] = Field(default_factory=list)
    timestamp_range: tuple[float, float] | None = None
    entities: list[KnowledgeEntity] = Field(default_factory=list)
    relations: list[KnowledgeRelation] = Field(default_factory=list)
    importance: float | None = None


class RealtimeEvent(BaseModel):
    """Generic input envelope for algorithm and mock realtime events.

    The event-specific data remains under payload during the first MVP phase.
    ContextManager and KnowledgeGraphManager can parse payload into the concrete
    models above once each integration path is ready.
    """

    session_id: str
    event_type: EventType | str = Field(
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
