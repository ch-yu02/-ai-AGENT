"""Orchestration for running internal extraction and applying graph updates."""

import os

from backend.app.core.context_manager import ContextEventError, ContextManager
from backend.app.core.knowledge_graph_manager import (
    KnowledgeGraphEventError,
    KnowledgeGraphManager,
)
from backend.app.models import ClassroomContext, ImageCapture, RealtimeEvent, TranscriptSegment

from .knowledge_extractor import KnowledgeExtractor
from .llm_extractor import LLMKnowledgeExtractor
from .rule_extractor import RuleKnowledgeExtractor
from .schemas import AppliedExtraction, ExtractionError, ExtractionResult


class KnowledgeExtractionService:
    """Run a configured extractor and route successful results into managers.

    The service is the bridge between "pure extraction" and the existing
    realtime pipeline. Extractors return ``KnowledgeExtraction`` models; this
    service wraps each one as an internal ``RealtimeEvent`` so the same
    ``ContextManager`` and ``KnowledgeGraphManager`` code path is used for
    rule-based extraction, future LLM extraction, mock sender data, and tests.
    """

    def __init__(self, extractor: KnowledgeExtractor | None = None) -> None:
        # Default to the offline rule extractor so automated tests and local
        # demos never require API keys or networked model services. Production
        # can opt into the LLM extractor with KNOWLEDGE_EXTRACTION_BACKEND=llm.
        self.extractor = extractor or build_default_extractor()

    def should_extract_realtime(
        self,
        context: ClassroomContext,
        event: RealtimeEvent,
        transcript_batch_size: int = 3,
    ) -> bool:
        """Return whether a just-accepted realtime event should trigger extraction.

        The rule extractor is cheap, but we still avoid invoking it on every
        transcript token. Transcript events trigger only after enough final,
        unprocessed segments have accumulated. A processed visual with OCR or a
        caption is allowed to trigger sooner because slide text often carries a
        complete formula or concept by itself.
        """
        if event.event_type not in {"transcript.segment", "image.capture"}:
            return False

        unprocessed_transcript, unprocessed_visuals = self._unprocessed_sources(context)
        if event.event_type == "transcript.segment":
            # Batch ASR text so the route does not run extraction for every
            # short sentence. The default threshold is intentionally tiny for
            # demo responsiveness and can become configurable later.
            return len(unprocessed_transcript) >= transcript_batch_size

        # Visual text often arrives as a complete slide/formula, so a single
        # processed image with OCR/caption is enough to justify extraction.
        return any(self._visual_has_text(visual) for visual in unprocessed_visuals)

    def extract_and_apply(
        self,
        context: ClassroomContext,
        context_manager: ContextManager,
        knowledge_graph_manager: KnowledgeGraphManager,
    ) -> ExtractionResult:
        """Extract knowledge and apply valid internal events to context and graph.

        Partial success is allowed. If one generated extraction cannot be
        applied, the error is reported in the returned result and later
        extractions still get a chance to apply. No exception escapes from this
        method for normal extraction failures.
        """
        result = self.extractor.extract(context)
        errors = list(result.errors)
        applied = []
        applied_details: list[AppliedExtraction] = []

        for extraction in result.extractions:
            # Keep the graph path identical to external/mock knowledge events.
            # This avoids a second implementation of timeline updates, source
            # refs, graph patching, and node/edge deduplication.
            event = RealtimeEvent(
                session_id=context.session_id,
                event_type="knowledge.extraction",
                payload=extraction.model_dump(),
            )
            try:
                context_update = context_manager.handle_event(event)
                patch = knowledge_graph_manager.handle_event(event)
            except (ContextEventError, KnowledgeGraphEventError) as exc:
                # A malformed extraction should be visible, but it should not
                # make the session end request fail after transcript/OCR data
                # has already been collected.
                errors.append(
                    ExtractionError(
                        provider=self.extractor.provider_name,
                        error_type=exc.__class__.__name__,
                        message=str(exc),
                        generated_graph=False,
                    )
                )
                continue
            if patch is not None and patch.operations:
                # Count only extractions that actually changed the graph. The
                # context still stores valid no-op extractions, but callers use
                # this result to report graph growth.
                applied.append(extraction)
                applied_details.append(
                    AppliedExtraction(
                        extraction=extraction,
                        context_update=context_update,
                        graph_patch=patch,
                    )
                )

        return ExtractionResult(
            extractions=applied,
            errors=errors,
            processed_source_ids=result.processed_source_ids,
            applied=applied_details,
        )

    def _unprocessed_sources(
        self,
        context: ClassroomContext,
    ) -> tuple[list[TranscriptSegment], list[ImageCapture]]:
        """Return final transcript and processed visuals not yet extracted.

        Existing ``context.knowledge_extractions`` are the source ledger. This
        keeps realtime and session-end extraction idempotent without a separate
        database table or background job state.
        """
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

    def _visual_has_text(self, visual: ImageCapture) -> bool:
        """Return true when OCR or VLM caption text is available to extract."""
        return bool(
            (visual.ocr_text and visual.ocr_text.strip())
            or (visual.caption and visual.caption.strip())
        )


def build_default_extractor() -> KnowledgeExtractor:
    """Build the configured extractor from backend-only environment variables.

    ``KNOWLEDGE_EXTRACTION_BACKEND`` is intentionally separate from the skill
    LLM settings. A project can enable LLM summarization or QA while keeping
    graph extraction deterministic, or opt into model-backed extraction only
    after prompt/schema behavior is acceptable.
    """
    backend = os.getenv("KNOWLEDGE_EXTRACTION_BACKEND", "rule").strip().lower()
    if backend == "llm":
        return LLMKnowledgeExtractor()
    return RuleKnowledgeExtractor()


knowledge_extraction_service = KnowledgeExtractionService()
