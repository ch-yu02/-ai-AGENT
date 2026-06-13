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

AgentAnswerMode = Literal["strict", "grounded"]
"""问答依据模式。strict 只用课堂资料；grounded 允许模型补充通用解释。"""

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
    answer_mode: AgentAnswerMode = "strict"
    """问答依据模式。只对 qa 生效，summary/todos/quiz 仍由各自技能决定。"""


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


class GlobalSearchRequest(BaseModel):
    """``POST /agent/search`` 的跨课堂搜索请求。

    Phase 7 第一版只搜索已保存到 ``data/sessions`` 的历史课堂。正在录制但尚未
    结束保存的课堂不在搜索范围内，避免全局搜索读到不完整或尚未授权落盘的数据。
    """

    query: str
    """用户问题或关键词，例如“哪节课讲过采样定理”。"""
    course: str | None = None
    """可选课程过滤。为空时搜索全部历史课堂。"""
    date_from: str | None = None
    """可选开始日期，格式 YYYY-MM-DD，按课堂 start_time 过滤。"""
    date_to: str | None = None
    """可选结束日期，格式 YYYY-MM-DD，按课堂 start_time 过滤。"""
    limit: int = Field(default=8, ge=1, le=20)
    """最多返回多少条来源命中。"""


class GlobalSearchSourceRef(BaseModel):
    """跨课堂搜索中的来源引用。

    与单课堂 ``AgentSourceRef`` 相比，这里允许 ``knowledge_edge`` 等 RAG 文档
    类型，并且每个引用都会被外层 hit 绑定到具体 session。
    """

    type: str
    """来源类型，例如 segment / visual / knowledge_node / knowledge_edge。"""
    id: str
    """来源对象 ID。"""
    ts: float | None = None
    """课堂内时间，单位秒。"""
    text: str
    """命中文档正文摘要。"""


class GlobalSearchHit(BaseModel):
    """一次跨课堂搜索命中。"""

    session_id: str
    """命中来源所属课堂。"""
    title: str
    """课堂标题。"""
    course: str | None = None
    """课程名。"""
    score: int
    """词法相关性分数，用于排序和调试。"""
    source_ref: GlobalSearchSourceRef
    """具体命中的课堂资料来源。"""


class GlobalSearchResponse(BaseModel):
    """``POST /agent/search`` 的响应。"""

    query: str
    """原始查询。"""
    answer: str
    """可直接展示的跨课堂搜索摘要。"""
    hits: list[GlobalSearchHit] = Field(default_factory=list)
    """按相关性排序的命中列表。"""
    warnings: list[str] = Field(default_factory=list)
    """非致命提示，例如没有历史课堂或没有找到依据。"""


__all__ = [
    "AgentArtifact",
    "AgentAnswerMode",
    "AgentChatRequest",
    "AgentChatResponse",
    "AgentIntent",
    "AgentSourceRef",
    "GlobalSearchHit",
    "GlobalSearchRequest",
    "GlobalSearchResponse",
    "GlobalSearchSourceRef",
    "ResolvedAgentIntent",
]
