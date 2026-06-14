"""Base interface for internal knowledge extraction."""

from abc import ABC, abstractmethod

from backend.app.models import ClassroomContext

from .schemas import ExtractionResult


class KnowledgeExtractor(ABC):
    """Extract internal KnowledgeExtraction payloads from classroom context.

    Implementations are responsible only for turning already-normalized
    classroom context into candidate ``KnowledgeExtraction`` objects. They do
    not mutate context, update the graph, broadcast WebSocket messages, or write
    storage files. Keeping the interface pure makes the rule extractor easy to
    test and lets future LLM-backed extractors expose failures without half
    applying graph changes.
    """

    provider_name = "base"

    @abstractmethod
    def extract(self, context: ClassroomContext) -> ExtractionResult:
        """Return structured extractions and explicit non-fatal errors.

        Extractors should return an ``ExtractionResult`` even when they fail.
        The surrounding service decides how to surface errors and whether any
        successful extraction should be routed into the internal event pipeline.
        """
