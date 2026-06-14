"""Schemas used by internal knowledge extraction implementations."""

from pydantic import BaseModel, Field

from backend.app.models import KnowledgeExtraction


class ExtractionError(BaseModel):
    """A non-fatal extraction failure that should be surfaced explicitly.

    Extraction errors are data, not exceptions that escape to the session API.
    This matches the project policy that failed knowledge extraction must not
    block transcript/OCR display or classroom saving. ``generated_graph`` stays
    false when no graph mutation happened, which is especially important for
    future LLM-backed extraction where schema validation can fail after a model
    call succeeds.
    """

    provider: str
    error_type: str
    message: str
    generated_graph: bool = False


class ExtractionResult(BaseModel):
    """Structured result returned by a KnowledgeExtractor.

    ``extractions`` contains only payloads that passed local validation.
    ``errors`` contains explicit failure details to show or log. The
    ``processed_source_ids`` list is intentionally separate from successful
    graph writes: it lets callers understand what the extractor considered in
    this batch, including batches that produced no entities.
    """

    extractions: list[KnowledgeExtraction] = Field(default_factory=list)
    errors: list[ExtractionError] = Field(default_factory=list)
    processed_source_ids: list[str] = Field(default_factory=list)
