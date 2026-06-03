"""WebSocket 消息模型 —— 定义后端推送给前端订阅者的消息信封。

在课堂进行过程中，后端需要将实时产生的各种数据（ASR 文本、
图像捕获、知识图谱增量等）推送到前端。WebSocketMessage 是
所有推送消息的统一信封，前端根据 ``type`` 字段分发到不同
的 UI 组件进行渲染。

使用场景：
  - 推送给 WebSocket 连接的课堂订阅者
  - 推送实时 ASR 文本片段、知识图谱更新、状态变更等
"""

from typing import Any

from pydantic import BaseModel, Field

from .common import utc_now_iso


class WebSocketMessage(BaseModel):
    """后端推送给前端 WebSocket 订阅者的统一消息信封。

    所有推送给前端的实时数据都封装为此格式，前端根据 ``type``
    字段选择对应的 UI 组件和数据解析逻辑进行处理。

    常见消息类型（type）示例：
      - ``"transcript"``        —— ASR 文本片段（data 为 TranscriptSegment 的 dict）
      - ``"image.captured"``    —— 图像已捕获
      - ``"graph.patch"``       —— 知识图谱增量更新（data 为 GraphPatch 的 dict）
      - ``"session.started"``   —— 课堂会话已开始
      - ``"session.ended"``     —— 课堂会话已结束

    Attributes:
        type:       消息类型标识，前端据此分发
        session_id: 所属会话 ID
        data:       消息体数据（具体的结构化数据）
        created_at: 消息生成时间
    """

    type: str
    """消息类型标识，前端按 type 分发到对应 UI 组件。"""
    session_id: str
    """所属课堂会话 ID。"""
    data: dict[str, Any] = Field(default_factory=dict)
    """消息体数据，包含具体的业务数据（如 ASR 文本、图更新等）。"""
    created_at: str = Field(default_factory=utc_now_iso)
    """消息生成时间戳（ISO-8601 格式）。"""
