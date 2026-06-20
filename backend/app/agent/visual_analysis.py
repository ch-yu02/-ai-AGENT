"""Cloud multimodal analysis for classroom camera snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any, Protocol

from pydantic import ValidationError

from backend.app import prompts
from backend.app.knowledge_quality import is_low_value_entity_name
from backend.app.llm import CloudLLMClient, CloudLLMError, LLMSettings, load_llm_settings
from backend.app.models import (
    ClassroomContext,
    ImageCapture,
    KnowledgeEntity,
    KnowledgeExtraction,
    KnowledgeRelation,
    KnowledgeTree,
)

from .schemas import VisualAnalysisRequest

VISUAL_TIMEOUT_FAILURE_STEP = 0.8
VISUAL_TIMEOUT_MAX_SECONDS = 300.0


class MultimodalJsonLLMClient(Protocol):
    """Minimum multimodal JSON interface used by visual analysis."""

    def complete_json_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        image_bytes: bytes,
        media_type: str,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Return a JSON object from a text+image prompt."""


@dataclass(frozen=True)
class VisualAnalysisResult:
    """Normalized result from one classroom image analysis."""

    visual: ImageCapture | None = None
    extraction: KnowledgeExtraction | None = None
    warnings: tuple[str, ...] = ()
    failed: bool = False
    skipped: bool = False


class ClassroomVisualAnalysisAgent:
    """Analyze a saved classroom image with a cloud multimodal model."""

    provider_name = "cloud_multimodal_llm"

    def __init__(self, llm_client: MultimodalJsonLLMClient | None = None) -> None:
        self.llm_client = llm_client
        self._processed_images: dict[str, set[str]] = {}
        self._failed_images: dict[str, dict[str, int]] = {}

    def reset(self) -> None:
        """Clear in-memory duplicate tracking; mainly used by tests."""
        self._processed_images.clear()
        self._failed_images.clear()

    def analyze(
        self,
        request: VisualAnalysisRequest,
        *,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
        image_bytes: bytes,
        media_type: str,
    ) -> VisualAnalysisResult:
        """Run multimodal analysis and convert the output into classroom events."""
        visual = _find_visual(context, request.image_id)
        if visual is None:
            return VisualAnalysisResult(
                failed=True,
                warnings=(f"Image not found in classroom context: {request.image_id}",),
            )

        fingerprint = _image_fingerprint(image_bytes)
        if (
            not request.force
            and fingerprint in self._processed_images.get(request.session_id, set())
            and visual.status == "processed"
        ):
            return VisualAnalysisResult(visual=visual, skipped=True)

        failure_count = self._failure_count(request.session_id, request.image_id)
        client = self._client_or_none(failure_count=failure_count)
        if client is None:
            warning = "Cloud multimodal LLM is not configured for image analysis."
            failed_visual = visual.model_copy(
                update={"status": "failed", "caption": warning}
            )
            return VisualAnalysisResult(
                visual=failed_visual,
                failed=True,
                warnings=(warning,),
            )

        try:
            payload = client.complete_json_with_image(
                prompts.visual_analysis_system_prompt(),
                prompts.visual_analysis_user_prompt(
                    session_id=request.session_id,
                    image_id=request.image_id,
                    capture_ts=visual.capture_ts,
                    recent_transcript=[
                        segment.model_dump()
                        for segment in context.transcript[-8:]
                    ],
                    existing_nodes=[node.label for node in knowledge_graph.nodes],
                    structured_notes_excerpt=None,
                ),
                image_bytes=image_bytes,
                media_type=media_type,
                temperature=0.1,
            )
            normalized_visual, extraction, warnings = self._validate_payload(
                payload,
                request=request,
                source_visual=visual,
            )
        except (CloudLLMError, ValidationError, KeyError, TypeError, ValueError) as exc:
            next_failure_count = self._record_failure(request.session_id, request.image_id)
            next_timeout = _visual_timeout_seconds(
                load_llm_settings().timeout_seconds,
                next_failure_count,
            )
            warning = f"Cloud multimodal image analysis failed: {exc}"
            if isinstance(exc, CloudLLMError):
                warning = f"{warning}; next retry timeout: {next_timeout:.0f}s"
            failed_visual = visual.model_copy(
                update={"status": "failed", "caption": warning}
            )
            return VisualAnalysisResult(
                visual=failed_visual,
                failed=True,
                warnings=(warning,),
            )

        self._processed_images.setdefault(request.session_id, set()).add(fingerprint)
        self._clear_failure(request.session_id, request.image_id)
        return VisualAnalysisResult(
            visual=normalized_visual,
            extraction=extraction,
            warnings=tuple(warnings),
        )

    def _client_or_none(self, *, failure_count: int = 0) -> MultimodalJsonLLMClient | None:
        if self.llm_client is not None:
            return self.llm_client
        settings = load_llm_settings()
        if not settings.enabled:
            return None
        settings = _settings_with_visual_timeout(settings, failure_count)
        return CloudLLMClient(settings)

    def _failure_count(self, session_id: str, image_id: str) -> int:
        return self._failed_images.get(session_id, {}).get(image_id, 0)

    def _record_failure(self, session_id: str, image_id: str) -> int:
        session_failures = self._failed_images.setdefault(session_id, {})
        next_count = session_failures.get(image_id, 0) + 1
        session_failures[image_id] = next_count
        return next_count

    def _clear_failure(self, session_id: str, image_id: str) -> None:
        session_failures = self._failed_images.get(session_id)
        if not session_failures:
            return
        session_failures.pop(image_id, None)
        if not session_failures:
            self._failed_images.pop(session_id, None)

    def _validate_payload(
        self,
        payload: dict[str, Any],
        *,
        request: VisualAnalysisRequest,
        source_visual: ImageCapture,
    ) -> tuple[ImageCapture, KnowledgeExtraction | None, list[str]]:
        warnings: list[str] = []
        caption = clean_text(payload.get("caption"))
        visual_text = clean_list(payload.get("visual_text"))
        key_points = clean_list(payload.get("key_points"))
        if not caption:
            caption = "图片已分析，但模型没有返回可展示描述。"
            warnings.append("Multimodal model returned empty caption.")

        visual = source_visual.model_copy(
            update={
                "status": "processed",
                "caption": caption,
                "visual_text": visual_text,
                "key_points": key_points,
            }
        )

        entities = normalize_entities(payload.get("entities"), warnings)
        relations = normalize_relations(payload.get("relations"), warnings)
        if not entities and not relations:
            return visual, None, warnings

        extraction_payload = {
            "extraction_id": (
                clean_text(payload.get("extraction_id"))
                or f"ext_visual_{request.image_id}_{_short_hash(caption)}"
            ),
            "session_id": request.session_id,
            "source_segment_ids": [],
            "source_visual_ids": [request.image_id],
            "timestamp_range": (source_visual.capture_ts, source_visual.capture_ts),
            "entities": entities,
            "relations": relations,
            "importance": normalize_importance(payload.get("importance")),
        }
        return visual, KnowledgeExtraction.model_validate(extraction_payload), warnings


def _find_visual(context: ClassroomContext, image_id: str) -> ImageCapture | None:
    for visual in context.visuals:
        if visual.image_id == image_id:
            return visual
    return None


def _settings_with_visual_timeout(settings: LLMSettings, failure_count: int) -> LLMSettings:
    timeout_seconds = _visual_timeout_seconds(settings.timeout_seconds, failure_count)
    if timeout_seconds == settings.timeout_seconds:
        return settings
    return replace(settings, timeout_seconds=timeout_seconds)


def _visual_timeout_seconds(base_timeout: float, failure_count: int) -> float:
    base_timeout = max(1.0, base_timeout)
    if failure_count <= 0:
        return base_timeout
    cap = max(VISUAL_TIMEOUT_MAX_SECONDS, base_timeout)
    return min(cap, base_timeout * (1 + VISUAL_TIMEOUT_FAILURE_STEP * failure_count))


def _image_fingerprint(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]  # noqa: S324 - local id.


def normalize_entities(value: object, warnings: list[str]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    entities: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        name = clean_text(item.get("name"))
        if not name or is_low_value_entity_name(name):
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        entity = KnowledgeEntity(
            entity_id=clean_text(item.get("entity_id")) or None,
            name=name,
            type=clean_relation_label(item.get("type"), default="concept"),
            description=clean_text(item.get("description")) or None,
        )
        entities.append(entity.model_dump())
    if value and not entities:
        warnings.append("Multimodal model returned only low-value visual entities.")
    return entities


def normalize_relations(value: object, warnings: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    relations: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        source = clean_text(item.get("source"))
        target = clean_text(item.get("target"))
        relation = clean_relation_label(item.get("relation"), default="related_to")
        if (
            not source
            or not target
            or source == target
            or is_low_value_entity_name(source)
            or is_low_value_entity_name(target)
        ):
            continue
        key = (source.casefold(), relation, target.casefold())
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            KnowledgeRelation(
                source=source,
                target=target,
                relation=relation,
            ).model_dump()
        )
    if value and not relations:
        warnings.append("Multimodal model returned only low-value visual relations.")
    return relations


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = clean_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
    return items[:12]


def clean_relation_label(value: object, *, default: str) -> str:
    text = clean_text(value).lower()
    if not text:
        text = default
    cleaned = "".join(char if char.isalnum() else "_" for char in text)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or default


def normalize_importance(value: object) -> float | None:
    try:
        importance = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, importance))


visual_analysis_agent = ClassroomVisualAnalysisAgent()
