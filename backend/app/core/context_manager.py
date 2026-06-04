"""课堂上下文管理器。

ContextManager 的职责是把“实时事件”变成“课堂上下文”。

输入：
  - RealtimeEvent(event_type="transcript.segment", payload={...})
  - RealtimeEvent(event_type="image.capture", payload={...})
  - RealtimeEvent(event_type="knowledge.extraction", payload={...})

输出：
  - ClassroomContext：保存 transcript / visuals / knowledge_extractions
  - TimelineItem：给前端展示的统一时间线条目
  - compressed context：后续给课后总结、待办、出题技能使用

它不负责：
  - 判断 session 是否存在或能否写入（SessionManager 负责）
  - 构建知识图谱节点/边（KnowledgeGraphManager 负责）
  - 写文件或数据库（LocalStorage 负责）
"""

from typing import Any

from pydantic import ValidationError

from backend.app.models import (
    ClassroomContext,
    ContextUpdate,
    ImageCapture,
    KnowledgeExtraction,
    RealtimeEvent,
    TimelineItem,
    TranscriptSegment,
    utc_now_iso,
)


class ContextNotFoundError(Exception):
    """Raised when a context operation references an unknown session."""


class ContextEventError(Exception):
    """Raised when a realtime event cannot be parsed into a context model."""


class ContextManager:
    """Maintains per-session classroom context in memory.

    每个 session_id 对应一个 ClassroomContext。MVP 阶段放在内存中；
    后续 Storage 模块可以在课堂开始时创建目录，在课堂结束时把该
    context 序列化到本地文件。
    """

    def __init__(self) -> None:
        self._contexts: dict[str, ClassroomContext] = {}

    def start_session(self, session_id: str) -> ClassroomContext:
        """Create or reset the context for a new classroom session."""
        context = ClassroomContext(session_id=session_id)
        self._contexts[session_id] = context
        return context

    def get_context(self, session_id: str) -> ClassroomContext:
        """Return the current context for a session."""
        context = self._contexts.get(session_id)
        if context is None:
            raise ContextNotFoundError(f"Context not found: {session_id}")
        return context

    def clear(self) -> None:
        """Clear all in-memory contexts for tests and local demo restarts."""
        self._contexts.clear()

    def handle_event(self, event: RealtimeEvent) -> ContextUpdate:
        """Parse one realtime event and merge it into the session context.

        路由层只需要把统一事件信封传进来；这里根据 event_type 分流到
        具体处理函数，并返回本次更新的摘要。未知 event_type 会被拒绝，
        防止上下文里混入无法解释的数据。
        """
        context = self.get_context(event.session_id)

        if event.event_type == "transcript.segment":
            timeline_item = self._add_transcript_segment(context, event)
        elif event.event_type == "image.capture":
            timeline_item = self._add_image_capture(context, event)
        elif event.event_type == "knowledge.extraction":
            timeline_item = self._add_knowledge_extraction(context, event)
        else:
            raise ContextEventError(f"Unsupported event_type: {event.event_type}")

        context.updated_at = utc_now_iso()
        self._sort_timeline(context)

        return ContextUpdate(
            session_id=event.session_id,
            event_type=event.event_type,
            timeline_item=timeline_item,
            transcript_count=len(context.transcript),
            visual_count=len(context.visuals),
            knowledge_extraction_count=len(context.knowledge_extractions),
        )

    def get_compressed_context(
        self,
        session_id: str,
        max_transcript_segments: int = 20,
    ) -> dict[str, Any]:
        """Return a compact context snapshot for post-class skills.

        课后总结、待办提取、出题不一定需要完整原始数据；这个方法返回
        最近若干条字幕、OCR/图片描述和知识实体名称，减少后续云端调用
        的 token 压力。
        """
        context = self.get_context(session_id)
        recent_transcript = context.transcript[-max_transcript_segments:]

        entities: list[str] = []
        for extraction in context.knowledge_extractions:
            entities.extend(entity.name for entity in extraction.entities)

        return {
            "session_id": session_id,
            "transcript_text": "\n".join(segment.text for segment in recent_transcript),
            "visual_notes": [
                {
                    "image_id": visual.image_id,
                    "ts": visual.capture_ts,
                    "ocr_text": visual.ocr_text,
                    "caption": visual.caption,
                }
                for visual in context.visuals
            ],
            "knowledge_entities": sorted(set(entities)),
            "important_segments": list(context.important_segments),
            "timeline_count": len(context.timeline),
            "updated_at": context.updated_at,
        }

    def _add_transcript_segment(
        self,
        context: ClassroomContext,
        event: RealtimeEvent,
    ) -> TimelineItem:
        """Parse ASR payload and append it to transcript and timeline."""
        payload = self._payload_with_defaults(
            event,
            {
                "segment_id": self._next_id(context, "seg", len(context.transcript)),
                "start_ts": 0.0,
                "end_ts": 0.0,
                "text": "",
            },
        )

        try:
            segment = TranscriptSegment.model_validate(payload)
        except ValidationError as exc:
            raise ContextEventError(f"Invalid transcript.segment payload: {exc}") from exc

        context.transcript.append(segment)
        if self._is_important(event.payload):
            context.important_segments.append(segment.segment_id)

        item = TimelineItem(
            item_id=segment.segment_id,
            session_id=context.session_id,
            type="transcript",
            ts=segment.start_ts,
            title=segment.text[:40] or "语音片段",
            data=segment.model_dump(),
        )
        context.timeline.append(item)
        return item

    def _add_image_capture(
        self,
        context: ClassroomContext,
        event: RealtimeEvent,
    ) -> TimelineItem:
        """Parse visual payload and append it to visuals and timeline."""
        image_id = self._next_id(context, "img", len(context.visuals))
        payload = self._payload_with_defaults(
            event,
            {
                "image_id": image_id,
                "capture_ts": 0.0,
                "image_path": f"local://sessions/{context.session_id}/images/{image_id}.jpg",
            },
        )

        try:
            visual = ImageCapture.model_validate(payload)
        except ValidationError as exc:
            raise ContextEventError(f"Invalid image.capture payload: {exc}") from exc

        context.visuals.append(visual)

        title = visual.ocr_text or visual.caption or visual.image_type or "课堂图片"
        item = TimelineItem(
            item_id=visual.image_id,
            session_id=context.session_id,
            type="visual",
            ts=visual.capture_ts,
            title=title[:40],
            data=visual.model_dump(),
        )
        context.timeline.append(item)
        return item

    def _add_knowledge_extraction(
        self,
        context: ClassroomContext,
        event: RealtimeEvent,
    ) -> TimelineItem:
        """Parse SLM extraction payload and append it to knowledge context."""
        payload = self._payload_with_defaults(
            event,
            {
                "extraction_id": self._next_id(
                    context,
                    "ext",
                    len(context.knowledge_extractions),
                )
            },
        )

        try:
            extraction = KnowledgeExtraction.model_validate(payload)
        except ValidationError as exc:
            raise ContextEventError(
                f"Invalid knowledge.extraction payload: {exc}"
            ) from exc

        context.knowledge_extractions.append(extraction)

        if extraction.importance is not None and extraction.importance >= 0.8:
            context.important_segments.extend(extraction.source_segment_ids)

        names = [entity.name for entity in extraction.entities]
        start_ts = extraction.timestamp_range[0] if extraction.timestamp_range else 0.0
        item = TimelineItem(
            item_id=extraction.extraction_id,
            session_id=context.session_id,
            type="knowledge",
            ts=start_ts,
            title="知识点：" + "、".join(names[:3]) if names else "知识抽取",
            data=extraction.model_dump(),
        )
        context.timeline.append(item)
        return item

    def _payload_with_defaults(
        self,
        event: RealtimeEvent,
        defaults: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge event payload with required defaults and session_id.

        算法组或 mock 脚本有时只传核心字段，例如只传 text。这里补齐
        session_id 和最小 ID，降低联调门槛。显式传入的 payload 字段
        优先级最高，不会被默认值覆盖。
        """
        return {
            **defaults,
            **event.payload,
            "session_id": event.payload.get("session_id", event.session_id),
        }

    def _next_id(self, context: ClassroomContext, prefix: str, current_count: int) -> str:
        """Generate deterministic local IDs for mock events that omit IDs."""
        return f"{prefix}_{context.session_id}_{current_count + 1:06d}"

    def _sort_timeline(self, context: ClassroomContext) -> None:
        """Keep timeline ordered by classroom timestamp after each update."""
        context.timeline.sort(key=lambda item: item.ts)

    def _is_important(self, payload: dict[str, Any]) -> bool:
        """Lightweight MVP importance heuristic.

        后续可以替换为 SLM 输出的显式重要度；现在支持 mock payload 里
        传 importance，也会识别一些课堂常见关键词。
        """
        importance = payload.get("importance")
        if isinstance(importance, int | float) and importance >= 0.8:
            return True

        text = str(payload.get("text", ""))
        return any(keyword in text for keyword in ("重点", "考试", "作业", "必须"))


context_manager = ContextManager()
"""ContextManager 的全局单例实例。"""
