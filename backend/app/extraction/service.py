"""Orchestration for running internal extraction and applying graph updates."""

from backend.app.core.context_manager import ContextEventError, ContextManager
from backend.app.core.knowledge_graph_manager import (
    KnowledgeGraphEventError,
    KnowledgeGraphManager,
)
from backend.app.models import ClassroomContext, RealtimeEvent

from .knowledge_extractor import KnowledgeExtractor
from .rule_extractor import RuleKnowledgeExtractor
from .schemas import ExtractionError, ExtractionResult


class KnowledgeExtractionService:
    """Run a configured extractor and route successful results into managers.

    The service is the bridge between "pure extraction" and the existing
    realtime pipeline. Extractors return ``KnowledgeExtraction`` models; this
    service wraps each one as an internal ``RealtimeEvent`` so the same
    ``ContextManager`` and ``KnowledgeGraphManager`` code path is used for
    rule-based extraction, future LLM extraction, mock sender data, and tests.
    """

    def __init__(self, extractor: KnowledgeExtractor | None = None) -> None:
        self.extractor = extractor or RuleKnowledgeExtractor()

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
                context_manager.handle_event(event)
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

        return ExtractionResult(
            extractions=applied,
            errors=errors,
            processed_source_ids=result.processed_source_ids,
        )


knowledge_extraction_service = KnowledgeExtractionService()
