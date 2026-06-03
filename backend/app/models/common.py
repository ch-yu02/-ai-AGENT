"""共享数据模型 —— 定义系统中通用的类型别名和基础 Pydantic 模型。

该模块被其他数据模型模块（如 notes.py、events.py 等）引用，
提供跨模块一致的类型定义。避免在各个模块中重复定义相同的
基础类型。
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel


# ── 类型别名 ────────────────────────────────────────────────────

SourceRefType = Literal["segment", "visual", "event"]
"""源引用类型。

- ``"segment"`` —— 引用一段文本/字幕片段
- ``"visual"``  —— 引用一帧画面/截图内容
- ``"event"``   —— 引用一个课堂事件（如切换页面、开始实验等）
"""


# ── 工具函数 ────────────────────────────────────────────────────

def utc_now_iso() -> str:
    """返回 ISO-8601 格式的 UTC 时间戳字符串。

    后端内部所有时间戳统一使用 UTC，避免时区混淆。生成笔记、
    事件等数据时调用此函数作为默认值。

    Returns:
        str: 如 ``2026-06-02T10:30:00.123456+00:00``

    Example:
        >>> utc_now_iso()
        '2026-06-02T10:30:00.123456+00:00'
    """
    return datetime.now(timezone.utc).isoformat()


# ── 基础数据模型 ────────────────────────────────────────────────

class SourceRef(BaseModel):
    """从衍生的笔记/分析数据指向原始课堂来源的引用。

    当 AI 分析生成笔记、识别知识点等内容时，使用 SourceRef 记录
    该条内容源自课堂中的具体哪个原始素材，方便追溯和上下文关联。

    Attributes:
        type: 原始素材的类型（片段 / 画面 / 事件）
        id:   原始素材的唯一标识符（UUID）
        ts:   素材在课堂时间轴上的时间位置（秒，可选）
    """

    type: SourceRefType
    """原始素材的类型。"""

    id: str
    """原始素材的唯一标识符（UUID 字符串）。"""

    ts: float | None = None
    """素材在课堂时间轴上的时间位置，单位为秒。``None`` 表示位置无关。"""
