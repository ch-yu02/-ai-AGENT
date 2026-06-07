"""课堂 Agent API 的 Pydantic 契约模型。

这些模型是 ``POST /agent/chat`` 的稳定边界。Agent 内部第一版使用规则
实现，后续可能切换为 LlamaIndex RAG、Cloud LLM 或结构化技能，但前端
仍应只依赖这里定义的请求/响应字段。

设计原则：
- ``answer`` 永远是可直接展示给用户的主回答。
- ``artifacts`` 承载结构化产物，例如 summary/todos/quiz，方便未来保存为
  ``summary.md``、``todos.json``、``quiz.json``。
- ``source_refs`` 明确回答依据，避免 Agent 变成无来源的开放域闲聊。
- ``warnings`` 用于传递数据不足、规则版候选、课堂仍在录制等非致命提示。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentIntent = Literal["auto", "qa", "summary", "todos", "quiz"]
"""前端可请求的模式。``auto`` 表示让后端根据 prompt 自动判断意图。"""

ResolvedAgentIntent = Literal["qa", "summary", "todos", "quiz"]
"""后端最终执行的技能类型，不包含 ``auto``。"""

SourceRefType = Literal["segment", "visual", "knowledge_node", "timeline"]
"""来源引用类型，对应课堂素材中的字幕、视觉内容、知识节点或时间线条目。"""


class AgentChatRequest(BaseModel):
    """``POST /agent/chat`` 的请求体。

    ``mode`` 默认为 ``auto``，用于普通自然语言入口。快捷按钮或后续结构化
    技能页面可以显式传 ``summary`` / ``todos`` / ``quiz``，从而绕过
    关键词路由，直接调用目标能力。
    """

    session_id: str
    """要查询的课堂 ID。可以是内存中的录制中课堂，也可以是已保存历史课堂。"""
    prompt: str
    """用户自然语言输入。第一版只处理课堂数据相关问题。"""
    mode: AgentIntent = "auto"
    """路由模式：auto 或显式技能类型。"""


class AgentArtifact(BaseModel):
    """Agent 技能生成的结构化产物。

    这里故意保持 ``content`` 比较宽松：规则版 todos/quiz 会返回类 JSON
    列表，summary 会返回 Markdown/纯文本。等 Phase 4 结构化技能稳定后，
    可以再把不同产物拆成更强类型的模型。
    """

    type: str
    """产物类型，例如 summary / todos / quiz。"""
    title: str
    """前端展示标题。"""
    content: str | list[dict[str, Any]] | dict[str, Any]
    """产物正文，可以是文本，也可以是结构化 JSON 对象或数组。"""


class AgentSourceRef(BaseModel):
    """随 Agent 回答一起展示的课堂依据引用。

    Agent 第一版不会生成“看似聪明但没有依据”的答案。所有能匹配到课堂素材的
    回答都会尽量携带 source_refs，供前端展示和未来跳转到历史回放位置。
    """

    type: SourceRefType
    """来源类型。"""
    id: str
    """来源对象 ID，例如 segment_id / image_id / node_id。"""
    ts: float | None = None
    """课堂内相对时间，单位秒。知识节点可能没有时间戳。"""
    text: str
    """给用户看的引用摘要。"""


class AgentChatResponse(BaseModel):
    """``POST /agent/chat`` 的响应体。"""

    session_id: str
    """本次回答所属课堂 ID。"""
    intent: ResolvedAgentIntent
    """后端实际执行的意图。auto 请求会在这里返回解析结果。"""
    answer: str
    """可直接渲染的主回答。"""
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    """结构化产物列表，普通 QA 可以为空。"""
    source_refs: list[AgentSourceRef] = Field(default_factory=list)
    """回答依据列表。找不到依据时允许为空，并在 warnings 中解释。"""
    warnings: list[str] = Field(default_factory=list)
    """非致命提示，例如数据不足、仍在录制、规则版候选需要人工确认。"""


__all__ = [
    "AgentArtifact",
    "AgentChatRequest",
    "AgentChatResponse",
    "AgentIntent",
    "AgentSourceRef",
    "ResolvedAgentIntent",
]
