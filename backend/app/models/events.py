"""课堂事件模型 —— 定义课堂中产生的各类原始事件及其结构化数据。

课堂进行过程中会产生多种事件流：
  - 语音识别（ASR）产生文本片段
  - 摄像头/截屏产生图像
  - 端侧 SLM 从文本和画面中提取知识点

RealtimeEvent 作为统一的消息信封，在后端入口处接收各类事件，
再由下游模块（ContextManager、KnowledgeGraphManager）按 event_type
分流解析。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import utc_now_iso


# ── 类型别名 ────────────────────────────────────────────────────

EventType = Literal[
    "transcript.segment",
    "image.capture",
    "knowledge.extraction",
]
"""当前支持的三种课堂事件类型。

- ``"transcript.segment"`` —— ASR 语音识别生成的文本片段
- ``"image.capture"``      —— 摄像头/截图捕获的画面
- ``"knowledge.extraction"`` —— 端侧 SLM 提取的知识图谱结果
"""


# ── 原始事件模型 ────────────────────────────────────────────────

class TranscriptSegment(BaseModel):
    """ASR 语音识别输出的实时文本片段。

    由 Whisper 或其他语音识别引擎产生，代表一段连续的课堂对话文本。

    Attributes:
        segment_id: 片段唯一标识
        session_id: 所属会话 ID
        start_ts:   片段开始时间（秒，相对课堂时间轴）
        end_ts:     片段结束时间（秒）
        text:       识别出的文本内容
        speaker:    说话人标识，默认 "teacher"
        confidence: 识别置信度（0~1），None 表示引擎未提供
        is_final:   是否为最终结果（False 表示临时中间结果）
        source:     识别引擎名称（如 "whisper", "ali_asr"）
        created_at: 记录创建时间（ISO-8601）
    """

    segment_id: str
    """片段唯一标识（UUID）。"""
    session_id: str
    """所属课堂会话 ID。"""
    start_ts: float
    """片段开始时间，单位秒。"""
    end_ts: float
    """片段结束时间，单位秒。"""
    text: str
    """ASR 识别的文本内容。"""
    speaker: str | None = "teacher"
    """说话人标签，默认假设为教师。"""
    confidence: float | None = None
    """识别置信度 0~1，None 表示未提供。"""
    is_final: bool = True
    """是否为最终片段。False 表示该片段后续可能会被修正。"""
    source: str | None = None
    """识别引擎标识，如 'whisper'。"""
    created_at: str = Field(default_factory=utc_now_iso)
    """记录创建时间。"""


class ImageCapture(BaseModel):
    """课堂过程中捕获的图像或视觉素材。

    来自学生端定时截图、教师端屏幕共享或白板拍摄。捕获后会上传
    到后端存储，并可能触发 OCR 文字提取和图文描述生成。

    Attributes:
        image_id:   图像唯一标识
        session_id: 所属会话 ID
        capture_ts: 捕获时刻（秒，相对课堂时间轴）
        upload_time: 上传完成时间
        image_path: 图像在后端存储的路径
        source:     来源标识（如 "camera", "screen_share"）
        image_type: 图像类型（如 "whiteboard", "slide", "experiment"）
        status:     处理状态（processed / processing / failed）
        ocr_text:   OCR 提取的文字内容（处理后填充）
        caption:    图像描述文本（由多模态模型生成，处理后填充）
    """

    image_id: str
    """图像唯一标识（UUID）。"""
    session_id: str
    """所属课堂会话 ID。"""
    capture_ts: float
    """捕获时刻，单位秒。"""
    upload_time: str = Field(default_factory=utc_now_iso)
    """上传完成时间（ISO-8601）。"""
    image_path: str
    """图像在后端本地或对象存储中的路径。"""
    source: str | None = None
    """来源标识，如 'camera' / 'screen_share'。"""
    image_type: str | None = None
    """图像内容分类，如 'whiteboard' / 'slide' / 'experiment'。"""
    status: str = "processed"
    """处理状态：processed / processing / failed。"""
    ocr_text: str | None = None
    """OCR 提取的文字内容（由下游处理模块填充）。"""
    caption: str | None = None
    """图像描述（由多模态模型生成，下游处理模块填充）。"""
    visual_text: list[str] = Field(default_factory=list)
    """多模态模型从图片中读到的关键文字/公式片段。"""
    key_points: list[str] = Field(default_factory=list)
    """多模态模型总结出的课堂要点。"""


# ── 知识提取子模型 ──────────────────────────────────────────────

class KnowledgeEntity(BaseModel):
    """端侧 SLM 从文本或画面中提取的知识实体。

    代表一个独立的知识概念，如公式定义、术语、人名等。

    Attributes:
        entity_id:   实体唯一标识（可选，由提取器生成）
        name:        实体名称
        type:        实体类型，默认 "concept"
        description: 实体描述/定义（可选）
    """

    entity_id: str | None = None
    """实体唯一标识（由提取器生成，可选）。"""
    name: str
    """实体名称（如 '牛顿第二定律'）。"""
    type: str = "concept"
    """实体类型，如 concept / formula / person / term。"""
    description: str | None = None
    """实体描述或定义。"""


class KnowledgeRelation(BaseModel):
    """两个知识实体之间的关系。

    Attributes:
        source:   源实体名称
        target:   目标实体名称
        relation: 关系类型（如 'belongs_to', 'derives_from', 'example_of'）
    """

    source: str
    """关系起点实体名称。"""
    target: str
    """关系终点实体名称。"""
    relation: str
    """关系类型标签。"""


class KnowledgeExtraction(BaseModel):
    """端侧 SLM 一次知识提取的结构化结果。

    对应 event_type = "knowledge.extraction" 的 payload 解析后的结构。
    包含从一段上下文（文本片段 + 画面）中提取的实体集合和关系集合。

    Attributes:
        extraction_id:     提取结果唯一标识
        session_id:        所属会话 ID
        source_segment_ids: 引用的 ASR 片段 ID 列表
        source_visual_ids:  引用的图像 ID 列表
        timestamp_range:    提取依据的时间段（起止秒数）
        entities:           提取到的知识实体列表
        relations:          实体间关系列表
        importance:         本次提取的重要度评分（0~1，可选）
    """

    extraction_id: str
    """提取结果唯一标识（UUID）。"""
    session_id: str
    """所属课堂会话 ID。"""
    source_segment_ids: list[str] = Field(default_factory=list)
    """引用的 ASR 文本片段 ID 列表。"""
    source_visual_ids: list[str] = Field(default_factory=list)
    """引用的图像 ID 列表。"""
    timestamp_range: tuple[float, float] | None = None
    """提取依据的时间段（开始秒, 结束秒）。"""
    entities: list[KnowledgeEntity] = Field(default_factory=list)
    """提取到的知识实体列表。"""
    relations: list[KnowledgeRelation] = Field(default_factory=list)
    """提取到的实体间关系列表。"""
    importance: float | None = None
    """本次提取对课堂的重要度（0~1）。"""


# ── 统一消息信封 ────────────────────────────────────────────────

class RealtimeEvent(BaseModel):
    """实时事件通用输入信封。

    所有课堂实时事件在进入后端时均封装为此模型。HTTP 或 WebSocket
    入口收到事件后，下游的 ContextManager 和 KnowledgeGraphManager
    根据 ``event_type`` 将 ``payload`` 解析为具体的结构化模型
    （如 TranscriptSegment、ImageCapture、KnowledgeExtraction）。

    MVP 阶段 payload 保持为通用的 dict，各集成路径就绪后再
    逐步迁移为强类型解析。

    Attributes:
        session_id: 所属会话 ID
        event_type: 事件类型标识
        payload:    事件体（原始数据，由下游按 event_type 解析）
        created_at: 事件到达后端时间
    """

    session_id: str
    """所属课堂会话 ID。"""
    event_type: EventType | str = Field(
        examples=["transcript.segment", "image.capture", "knowledge.extraction"]
    )
    """事件类型，决定 payload 的解析方式。"""
    payload: dict[str, Any] = Field(default_factory=dict)
    """事件具体数据，由下游模块按 event_type 解析。"""
    created_at: str = Field(default_factory=utc_now_iso)
    """事件到达后端的时间。"""


class EventAcceptedResponse(BaseModel):
    """事件入队成功后的轻量确认响应。

    后端收到实时事件后快速返回此确认，异步处理后续逻辑（如持久化、
    知识图谱更新），不阻塞前端事件上报。

    Attributes:
        status:      固定为 "accepted"
        session_id:  所属会话 ID
        event_type:  已接收的事件类型
        event_count: 该会话目前已累计的事件数
    """

    status: Literal["accepted"]
    """固定确认状态标志。"""
    session_id: str
    """所属会话 ID。"""
    event_type: str
    """已接收的事件类型。"""
    event_count: int
    """该会话累计事件计数（可用于前端确认无丢包）。"""
