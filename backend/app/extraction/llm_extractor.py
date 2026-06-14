"""LLM-backed internal knowledge extractor.

This is the production knowledge-extraction path. The older rule extractor is
kept only as a legacy/debug baseline; automatic extraction should use the LLM
path and surface failures explicitly instead of silently creating weaker graph
nodes.
"""

from typing import Any, Protocol

from pydantic import ValidationError

from backend.app.llm import CloudLLMClient, CloudLLMError, load_llm_settings
from backend.app.models import (
    ClassroomContext,
    ImageCapture,
    KnowledgeExtraction,
    TranscriptSegment,
)

from .knowledge_extractor import KnowledgeExtractor
from .schemas import ExtractionError, ExtractionResult


class JsonLLMClient(Protocol):
    """Minimum LLM interface needed by the extractor.

    Tests inject a fake implementation of this protocol. Production uses
    ``CloudLLMClient``. Keeping the dependency this small prevents the extractor
    from depending on HTTP details or provider-specific SDKs.
    """

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Return one JSON object from the model."""


class LLMKnowledgeExtractor(KnowledgeExtractor):
    """Generate ``KnowledgeExtraction`` payloads with an OpenAI-compatible LLM."""

    provider_name = "llm"

    def __init__(self, llm_client: JsonLLMClient | None = None) -> None:
        # ``llm_client`` is optional so tests can inject fakes and production can
        # lazily build from backend-only environment variables. If settings are
        # missing, extraction returns an explicit error instead of falling back.
        self.llm_client = llm_client

    def extract(self, context: ClassroomContext) -> ExtractionResult:
        """Ask the model for a validated extraction from unprocessed sources."""
        transcript, visuals = self._unprocessed_sources(context)
        processed_source_ids = [
            *[segment.segment_id for segment in transcript],
            *[visual.image_id for visual in visuals],
        ]
        if not transcript and not visuals:
            return ExtractionResult()

        client = self._client_or_none()
        if client is None:
            return self._error_result(
                "LLMNotConfigured",
                "LLM knowledge extraction requires a configured LLM provider",
                processed_source_ids,
            )

        try:
            payload = client.complete_json(
                self._system_prompt(),
                self._user_prompt(context, transcript, visuals),
                temperature=0.1,
            )
            extraction = self._validate_payload(
                payload,
                context.session_id,
                transcript,
                visuals,
            )
        except (CloudLLMError, ValidationError, KeyError, TypeError, ValueError) as exc:
            return self._error_result(
                exc.__class__.__name__,
                str(exc),
                processed_source_ids,
            )

        if not extraction.entities and not extraction.relations:
            return ExtractionResult(processed_source_ids=processed_source_ids)
        return ExtractionResult(
            extractions=[extraction],
            processed_source_ids=processed_source_ids,
        )

    def _client_or_none(self) -> JsonLLMClient | None:
        """Return an injected or configured client, or None when disabled."""
        if self.llm_client is not None:
            return self.llm_client

        settings = load_llm_settings()
        if not settings.enabled:
            return None
        return CloudLLMClient(settings)

    def _validate_payload(
        self,
        payload: dict[str, Any],
        session_id: str,
        transcript: list[TranscriptSegment],
        visuals: list[ImageCapture],
    ) -> KnowledgeExtraction:
        """Validate model JSON and force source/session fields to safe values.

        The model is allowed to propose entities and relations, but it is not
        trusted to invent session IDs or source references. We overwrite
        ``session_id``, constrain source IDs to the batch actually shown in the
        prompt, and compute the timestamp range locally.
        """
        segment_ids = [segment.segment_id for segment in transcript]
        visual_ids = [visual.image_id for visual in visuals]
        safe_payload = {
            **payload,
            "extraction_id": str(
                payload.get("extraction_id")
                or self._extraction_id(session_id, segment_ids, visual_ids)
            ),
            "session_id": session_id,
            "source_segment_ids": self._valid_ids(
                payload.get("source_segment_ids"),
                segment_ids,
            ),
            "source_visual_ids": self._valid_ids(
                payload.get("source_visual_ids"),
                visual_ids,
            ),
            "timestamp_range": self._timestamp_range(transcript, visuals),
        }
        return KnowledgeExtraction.model_validate(safe_payload)

    def _system_prompt(self) -> str:
        """Prompt contract for stable graph extraction JSON."""
        return (
            "You are EDU-Mate's internal classroom knowledge extractor. "
            "Return only a JSON object matching this schema: "
            "{extraction_id:string optional, source_segment_ids:string[], "
            "source_visual_ids:string[], entities:[{entity_id?:string, "
            "name:string, type:string, description?:string}], "
            "relations:[{source:string,target:string,relation:string}], "
            "importance:number optional}. "
            "Use only the provided classroom transcript/OCR/caption sources. "
            "Do not invent source ids. Prefer concise Chinese entity names. "
            "Relations must use snake_case labels such as defines, mentions, "
            "related_to, maps_to, belongs_to, part_of, derives_from."
        )

    def _user_prompt(
        self,
        context: ClassroomContext,
        transcript: list[TranscriptSegment],
        visuals: list[ImageCapture],
    ) -> str:
        """Build a compact, source-ID-preserving prompt for the model."""
        lines = [f"session_id: {context.session_id}", "", "transcript:"]
        if transcript:
            for segment in transcript:
                lines.append(
                    "- "
                    f"id={segment.segment_id}; "
                    f"ts={segment.start_ts:.2f}-{segment.end_ts:.2f}; "
                    f"text={segment.text}"
                )
        else:
            lines.append("- none")

        lines.extend(["", "visuals:"])
        if visuals:
            for visual in visuals:
                ocr = visual.ocr_text or ""
                caption = visual.caption or ""
                lines.append(
                    "- "
                    f"id={visual.image_id}; "
                    f"ts={visual.capture_ts:.2f}; "
                    f"ocr={ocr}; "
                    f"caption={caption}"
                )
        else:
            lines.append("- none")
        return "\n".join(lines)

    def _unprocessed_sources(
        self,
        context: ClassroomContext,
    ) -> tuple[list[TranscriptSegment], list[ImageCapture]]:
        """Use existing extractions as the idempotency ledger."""
        processed_segments = set()
        processed_visuals = set()
        for extraction in context.knowledge_extractions:
            processed_segments.update(extraction.source_segment_ids)
            processed_visuals.update(extraction.source_visual_ids)

        transcript = [
            segment
            for segment in context.transcript
            if segment.is_final and segment.segment_id not in processed_segments
        ]
        visuals = [
            visual
            for visual in context.visuals
            if visual.status == "processed" and visual.image_id not in processed_visuals
        ]
        return transcript, visuals

    def _valid_ids(self, value: object, allowed: list[str]) -> list[str]:
        """Keep model source refs only when they were present in the prompt."""
        if not isinstance(value, list):
            return allowed
        allowed_set = set(allowed)
        valid = [str(item) for item in value if str(item) in allowed_set]
        return valid or allowed

    def _timestamp_range(
        self,
        transcript: list[TranscriptSegment],
        visuals: list[ImageCapture],
    ) -> tuple[float, float] | None:
        """Compute source coverage locally instead of trusting the model."""
        timestamps: list[float] = []
        for segment in transcript:
            timestamps.extend([segment.start_ts, segment.end_ts])
        for visual in visuals:
            timestamps.append(visual.capture_ts)
        if not timestamps:
            return None
        return (min(timestamps), max(timestamps))

    def _extraction_id(
        self,
        session_id: str,
        segment_ids: list[str],
        visual_ids: list[str],
    ) -> str:
        """Create a readable deterministic ID for model output batches."""
        source = "_".join([*segment_ids, *visual_ids]) or "empty"
        return f"ext_llm_{session_id}_{source}"

    def _error_result(
        self,
        error_type: str,
        message: str,
        processed_source_ids: list[str],
    ) -> ExtractionResult:
        """Return a failed extraction as explicit data, never as fallback."""
        return ExtractionResult(
            errors=[
                ExtractionError(
                    provider=self.provider_name,
                    error_type=error_type,
                    message=message,
                    generated_graph=False,
                )
            ],
            processed_source_ids=processed_source_ids,
        )
