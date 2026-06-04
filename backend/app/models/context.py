"""课堂上下文模型。

ContextManager 会把实时事件整理为这几个结构：
  - transcript：按时间排序的语音转写片段
  - visuals：课堂图片、OCR、VLM 描述
  - knowledge_extractions：端侧 SLM 输出的实体/关系结果
  - timeline：前端最容易消费的统一时间线

这些模型不负责处理业务逻辑，只描述“上下文长什么样”。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import utc_now_iso
from .events import ImageCapture, KnowledgeExtraction, TranscriptSegment


TimelineItemType = Literal["transcript", "visual", "knowledge"]
"""时间线条目类型，对应 ContextManager 当前支持的三类事件。"""


class TimelineItem(BaseModel):
    """课堂时间线上的一个可展示条目。"""

    item_id: str
    """时间线条目唯一 ID，通常来自源数据 ID。"""
    session_id: str
    """所属课堂 ID。"""
    type: TimelineItemType
    """条目类型：transcript / visual / knowledge。"""
    ts: float
    """条目在课堂内的相对时间，单位秒。"""
    title: str
    """前端列表中的短标题。"""
    data: dict[str, Any] = Field(default_factory=dict)
    """原始或派生数据，便于前端按需展开详情。"""
    created_at: str = Field(default_factory=utc_now_iso)
    """条目进入后端上下文的时间。"""


class ClassroomContext(BaseModel):
    """某一课堂 session 的完整内存上下文。"""

    session_id: str
    """所属课堂 ID。"""
    timeline: list[TimelineItem] = Field(default_factory=list)
    """统一课堂时间线，用于前端滚动展示和课后导出。"""
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    """语音转写片段列表。"""
    visuals: list[ImageCapture] = Field(default_factory=list)
    """图片、OCR、VLM 描述列表。"""
    knowledge_extractions: list[KnowledgeExtraction] = Field(default_factory=list)
    """知识抽取原始结构化结果，后续用于更新知识图谱。"""
    important_segments: list[str] = Field(default_factory=list)
    """重要片段 ID 列表，MVP 阶段按 importance 或关键词做轻量标记。"""
    updated_at: str = Field(default_factory=utc_now_iso)
    """上下文最后更新时间。"""


class ContextUpdate(BaseModel):
    """ContextManager 处理事件后的轻量返回值。"""

    session_id: str
    event_type: str
    timeline_item: TimelineItem | None = None
    transcript_count: int
    visual_count: int
    knowledge_extraction_count: int
