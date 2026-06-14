"""Legacy rule-based internal knowledge extractor.

This module is retained as a debug/comparison baseline, not as the production
knowledge-extraction path. Automatic graph growth now uses
``LLMKnowledgeExtractor``; when the LLM is unavailable, EDU-Mate reports an
explicit extraction error instead of silently falling back to these heuristics.
"""

import re

from backend.app.models import (
    ClassroomContext,
    ImageCapture,
    KnowledgeEntity,
    KnowledgeExtraction,
    KnowledgeRelation,
    TranscriptSegment,
)

from .knowledge_extractor import KnowledgeExtractor
from .schemas import ExtractionError, ExtractionResult


class RuleKnowledgeExtractor(KnowledgeExtractor):
    """Legacy extractor for local experiments and regression comparison.

    This extractor is deliberately conservative. It is not trying to solve
    Chinese NLP in full; it gives EDU-Mate a deterministic local baseline that
    can produce traceable graph nodes from common classroom phrases such as
    definitions, formulas, and "A maps/transforms to B" statements.
    """

    provider_name = "rule"

    _concept_suffixes = (
        "变换",
        "定理",
        "公式",
        "频域",
        "时域",
        "信号",
        "系统",
        "函数",
        "矩阵",
        "模型",
        "算法",
        "方法",
        "概念",
        "定义",
        "卷积",
        "采样",
    )
    _formula_markers = ("=", "∫", "∑", "π", "√", "^", "_", "→", "->")

    def extract(self, context: ClassroomContext) -> ExtractionResult:
        """Build one batch extraction from not-yet-processed sources.

        Existing ``knowledge_extractions`` are treated as the source ledger.
        If a transcript segment or visual has already appeared in a previous
        extraction, this method skips it so repeated session-end calls or later
        recording-time triggers do not keep creating duplicate graph events.
        """
        try:
            processed_segments, processed_visuals = self._processed_sources(context)
            # ASR interim hypotheses may later be corrected, so only final
            # transcript segments are eligible for graph extraction.
            transcript = [
                segment
                for segment in context.transcript
                if segment.is_final and segment.segment_id not in processed_segments
            ]
            # Visuals are useful only after OCR/VLM processing has completed.
            # Failed or still-processing captures should remain visible in the
            # visual panel, but they are not trusted as graph evidence.
            visuals = [
                visual
                for visual in context.visuals
                if visual.status == "processed" and visual.image_id not in processed_visuals
            ]
            if not transcript and not visuals:
                return ExtractionResult()

            extraction = self._extract_batch(context.session_id, transcript, visuals)
            source_ids = [
                *extraction.source_segment_ids,
                *extraction.source_visual_ids,
            ]
            if not extraction.entities and not extraction.relations:
                # Empty extraction is a normal outcome for filler speech. Do
                # not create placeholder knowledge nodes just to show activity.
                return ExtractionResult(processed_source_ids=source_ids)
            return ExtractionResult(
                extractions=[extraction],
                processed_source_ids=source_ids,
            )
        except Exception as exc:  # noqa: BLE001 - extraction errors are non-fatal.
            # The API layer should never see extraction failures as 500s. The
            # error object makes the failure inspectable while preserving the
            # user's transcript, visuals, and existing graph.
            return ExtractionResult(
                errors=[
                    ExtractionError(
                        provider=self.provider_name,
                        error_type=exc.__class__.__name__,
                        message=str(exc),
                        generated_graph=False,
                    )
                ]
            )

    def _extract_batch(
        self,
        session_id: str,
        transcript: list[TranscriptSegment],
        visuals: list[ImageCapture],
    ) -> KnowledgeExtraction:
        """Convert one group of transcript/visual sources into a payload.

        The current phase emits one extraction per batch. That keeps source
        refs simple and lets the graph manager do entity/edge deduplication.
        Later versions can split by topic block while keeping the same return
        schema.
        """
        text_sources: list[tuple[str, str]] = []
        for segment in transcript:
            text_sources.append(("segment", segment.text))
        for visual in visuals:
            text = "\n".join(
                value
                for value in (visual.ocr_text, visual.caption)
                if value and value.strip()
            )
            if text.strip():
                text_sources.append(("visual", text))

        entities = self._extract_entities(text_sources)
        relations = self._extract_relations(text_sources, entities)
        timestamp_range = self._timestamp_range(transcript, visuals)
        source_segment_ids = [segment.segment_id for segment in transcript]
        source_visual_ids = [visual.image_id for visual in visuals]

        return KnowledgeExtraction(
            extraction_id=self._extraction_id(session_id, source_segment_ids, source_visual_ids),
            session_id=session_id,
            source_segment_ids=source_segment_ids,
            source_visual_ids=source_visual_ids,
            timestamp_range=timestamp_range,
            entities=entities,
            relations=relations,
            importance=0.7 if entities or relations else None,
        )

    def _extract_entities(
        self,
        text_sources: list[tuple[str, str]],
    ) -> list[KnowledgeEntity]:
        """Find formulas, definition subjects, map endpoints, and terms."""
        entities: dict[str, KnowledgeEntity] = {}
        for source_type, text in text_sources:
            # OCR often contains compact mathematical expressions. These are
            # promoted first so formula nodes keep the stronger type even if
            # later text also matches a broad concept suffix.
            for formula in self._formula_candidates(text):
                self._add_entity(entities, formula, "formula")
            # Definition-like sentences are the most useful rule signal because
            # they can attach a short description to the concept node.
            for name, description in self._definition_candidates(text):
                self._add_entity(entities, name, "concept", description)
            # Relation rules also reveal useful endpoint entities. Add them up
            # front so the relation does not rely on graph-manager placeholders.
            for source, target in self._maps_to_candidates(text):
                self._add_entity(entities, source, "concept")
                self._add_entity(entities, target, "concept")
            # Finally add broad suffix-based concept candidates. This catches
            # classroom terms like "采样定理" even when there is no explicit
            # definition sentence nearby.
            for concept in self._concept_candidates(text):
                entity_type = "formula" if source_type == "visual" and self._looks_formula(concept) else "concept"
                self._add_entity(entities, concept, entity_type)
        return list(entities.values())

    def _extract_relations(
        self,
        text_sources: list[tuple[str, str]],
        entities: list[KnowledgeEntity],
    ) -> list[KnowledgeRelation]:
        """Create deterministic relation candidates from local co-text."""
        names = {entity.name for entity in entities}
        relations: dict[tuple[str, str, str], KnowledgeRelation] = {}
        for _, text in text_sources:
            # "时域信号转换到频域" is common in signal-processing lectures and
            # maps naturally to a directed graph edge.
            for source, target in self._maps_to_candidates(text):
                if source and target:
                    self._add_relation(relations, source, target, "maps_to")
                    names.update((source, target))
            # The object of a definition is noisy, but still useful as a simple
            # directed edge when the graph is otherwise sparse.
            for source, target in self._definition_relation_candidates(text):
                self._add_relation(relations, source, target, "defines")
                names.update((source, target))

            # Co-mentions provide low-strength structure without pretending we
            # know the exact semantic relation. Cap the count to avoid turning a
            # dense slide full of terms into a noisy complete graph.
            mentioned = [name for name in names if name and name in text]
            if 1 < len(mentioned) <= 5:
                anchor = mentioned[0]
                for target in mentioned[1:]:
                    self._add_relation(relations, anchor, target, "related_to")
        return list(relations.values())

    def _formula_candidates(self, text: str) -> list[str]:
        """Return compact lines that look like formulas."""
        candidates: list[str] = []
        for line in re.split(r"[\n;；。]", text):
            stripped = line.strip()
            if 4 <= len(stripped) <= 80 and self._looks_formula(stripped):
                candidates.append(stripped)
        return candidates

    def _definition_candidates(self, text: str) -> list[tuple[str, str]]:
        """Return pairs from simple Chinese definition patterns."""
        candidates: list[tuple[str, str]] = []
        pattern = re.compile(
            r"([\u4e00-\u9fffA-Za-z0-9（）()]{2,20})"
            r"(?:是|指的是|表示|定义为)"
            r"([^。；;,.，]{2,60})"
        )
        for match in pattern.finditer(text):
            name = self._clean_name(match.group(1))
            description = match.group(2).strip()
            if name:
                candidates.append((name, description))
        return candidates

    def _definition_relation_candidates(self, text: str) -> list[tuple[str, str]]:
        """Turn definition descriptions into coarse ``defines`` endpoints."""
        pairs: list[tuple[str, str]] = []
        for name, description in self._definition_candidates(text):
            target = self._clean_name(description[:20])
            if target and target != name:
                pairs.append((name, target))
        return pairs

    def _maps_to_candidates(self, text: str) -> list[tuple[str, str]]:
        """Return source/target pairs from transform-or-map expressions."""
        pairs: list[tuple[str, str]] = []
        pattern = re.compile(
            r"([\u4e00-\u9fffA-Za-z0-9（）()]{2,20})"
            r".{0,12}?(?:转换到|映射到|变换到)"
            r"([\u4e00-\u9fffA-Za-z0-9（）()]{2,20})"
        )
        for match in pattern.finditer(text):
            source = self._clean_name(match.group(1))
            target = self._clean_name(match.group(2))
            if source and target and source != target:
                pairs.append((source, target))
        return pairs

    def _concept_candidates(self, text: str) -> list[str]:
        """Find short terms ending in common classroom concept suffixes."""
        candidates: list[str] = []
        for suffix in self._concept_suffixes:
            pattern = re.compile(rf"[\u4e00-\u9fffA-Za-z0-9（）()]{{0,10}}{suffix}")
            for match in pattern.finditer(text):
                name = self._clean_name(match.group(0))
                if name:
                    candidates.append(name)
        return candidates

    def _add_entity(
        self,
        entities: dict[str, KnowledgeEntity],
        name: str,
        entity_type: str,
        description: str | None = None,
    ) -> None:
        """Insert or merge a candidate entity by normalized name."""
        cleaned = self._clean_name(name)
        if not cleaned:
            return
        key = cleaned.lower()
        existing = entities.get(key)
        if existing is None:
            entities[key] = KnowledgeEntity(
                entity_id=self._node_id(cleaned),
                name=cleaned,
                type=entity_type,
                description=description,
            )
            return
        # Preserve the first non-empty description, and upgrade broad concepts
        # to formulas when OCR/formula heuristics give stronger evidence.
        if description and not existing.description:
            existing.description = description
        if existing.type == "concept" and entity_type == "formula":
            existing.type = "formula"

    def _add_relation(
        self,
        relations: dict[tuple[str, str, str], KnowledgeRelation],
        source: str,
        target: str,
        relation: str,
    ) -> None:
        """Insert one relation while removing exact duplicates."""
        source = self._clean_name(source)
        target = self._clean_name(target)
        if not source or not target or source == target:
            return
        key = (source.lower(), target.lower(), relation)
        relations.setdefault(
            key,
            KnowledgeRelation(source=source, target=target, relation=relation),
        )

    def _processed_sources(self, context: ClassroomContext) -> tuple[set[str], set[str]]:
        """Collect source IDs already represented by existing extractions."""
        segments: set[str] = set()
        visuals: set[str] = set()
        for extraction in context.knowledge_extractions:
            segments.update(extraction.source_segment_ids)
            visuals.update(extraction.source_visual_ids)
        return segments, visuals

    def _timestamp_range(
        self,
        transcript: list[TranscriptSegment],
        visuals: list[ImageCapture],
    ) -> tuple[float, float] | None:
        """Compute the classroom-time span covered by the extraction batch."""
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
        """Create a deterministic extraction ID from session and source IDs."""
        source = "_".join([*segment_ids, *visual_ids]) or "empty"
        return f"ext_{self._slug(session_id)}_{self._slug(source)}"

    def _node_id(self, name: str) -> str:
        """Create a stable node ID compatible with KnowledgeGraphManager."""
        return f"node_{self._slug(name) or 'unknown'}"

    def _slug(self, value: str) -> str:
        """Keep Chinese/ASCII text while replacing separators for stable IDs."""
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", value.strip()).strip("_")
        return slug[:80]

    def _looks_formula(self, text: str) -> bool:
        """Detect formula-like text with cheap marker checks."""
        return any(marker in text for marker in self._formula_markers)

    def _clean_name(self, value: str) -> str:
        """Trim punctuation and remove common connector words from candidates."""
        cleaned = value.strip(" \t\r\n：:，,。；;、（）()[]【】")
        cleaned = re.sub(r"^(所以|然后|因为|其中|这个|我们|课件展示|重点是)", "", cleaned)
        for marker in ("可以把", "能够把"):
            if marker in cleaned:
                before, after = cleaned.split(marker, 1)
                cleaned = before if before.strip() else after
        for marker in ("转换到", "映射到", "变换到"):
            if marker in cleaned:
                before, after = cleaned.split(marker, 1)
                cleaned = after if after.strip() else before
        cleaned = re.sub(r"^(把|到)", "", cleaned)
        return cleaned.strip(" \t\r\n：:，,。；;、（）()[]【】")
