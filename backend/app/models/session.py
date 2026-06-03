"""课堂会话模型 —— 定义课堂会话的创建请求和状态表示。

该模块提供：
1. 会话生命周期管理（'recording' → 'ended'）的状态类型
2. 前端发起课堂时的请求模型 ``StartSessionRequest``
3. 核心的 ``LectureSession`` 模型，在 HTTP API、WebSocket
   和持久化存储之间共享
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# ── 类型别名 ────────────────────────────────────────────────────

SessionStatus = Literal["recording", "ended"]
"""课堂会话的生命周期状态。

- ``"recording"`` —— 正在录制/进行中
- ``"ended"``     —— 已结束
"""


# ── 工具函数 ────────────────────────────────────────────────────

def new_session_id() -> str:
    """生成可读的本地会话 ID，用于演示、日志和文件路径。

    ID 格式为 ``lec_{UTC时间戳}_{UUID前缀}``，兼顾可读性和唯一性：
      - 时间戳部分（``YYYYmmdd_HHMMSS``）便于在文件系统中按时间排序
      - UUID 前缀（8位十六进制）确保高并发下不冲突

    Returns:
        str: 如 ``lec_20260602_143021_a1b2c3d4``

    Note:
        Demo 阶段由后端本地生成。后续若对接硬件设备 ID 或外部存储，
        ``SessionManager`` 可能改为接受外部传入的 ID。
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = uuid4().hex[:8]
    return f"lec_{timestamp}_{suffix}"


# ── 会话模型 ────────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    """前端发起课堂会话的请求体模型。

    Attributes:
        title:      课堂标题，UI 侧默认为"未命名课堂"
        course:     课程名称（可选，如"高等数学"）
        teacher:    教师姓名（可选）
        language:   课堂使用的语言代码，默认 "zh-CN"
        created_by: 创建者角色，默认 "student"（课堂由学生端发起）
        device_id:  发起设备的硬件标识（可选，后续用于多端配对）
    """

    title: str = Field(default="未命名课堂")
    """课堂标题。"""
    course: str | None = None
    """课程名称（可选）。"""
    teacher: str | None = None
    """教师姓名（可选）。"""
    language: str = Field(default="zh-CN")
    """课堂语言代码，默认中文。"""
    created_by: str = Field(default="student")
    """创建者身份标识（student / teacher），默认学生端发起。"""
    device_id: str | None = None
    """发起设备的硬件标识（可选），后续用于多设备配对。"""


class LectureSession(BaseModel):
    """课堂会话的完整数据模型，在 HTTP API、WebSocket 和存储之间共享。

    一条会话记录代表一次完整的课堂录制周期，从创建（recording）
    到结束（ended）。所有时间戳统一使用 ``utc_now_iso()`` 的
    ISO-8601 格式。

    Attributes:
        session_id: 全局唯一会话 ID（由 new_session_id() 生成）
        title:      课堂标题
        course:     课程名称
        teacher:    教师姓名
        start_time: 课堂开始时间（ISO-8601 格式）
        end_time:   课堂结束时间（结束前为 None）
        status:     当前状态（recording / ended）
        language:   课堂语言
        created_by: 创建者
        device_id:  发起设备标识
    """

    session_id: str
    """全局唯一的会话标识符。"""
    title: str
    """课堂标题。"""
    course: str | None = None
    """课程名称。"""
    teacher: str | None = None
    """教师姓名。"""
    start_time: str
    """课堂开始时间的 ISO-8601 字符串。"""
    end_time: str | None = None
    """课堂结束时间（会话进行中为 None）。"""
    status: SessionStatus
    """会话当前状态。"""
    language: str
    """课堂使用的语言代码。"""
    created_by: str
    """创建者身份标识。"""
    device_id: str | None = None
    """发起设备的硬件标识。"""
