"""课后技能层的内部结果模型。

这些模型刻意放在 ``backend/app/skills`` 下，而不是复用 Agent API 的
Pydantic 响应模型。原因是技能层应该独立于 HTTP/API 契约：未来同一个技能
既可以被 ``/agent/chat`` 调用，也可以被独立的
``/sessions/{session_id}/skills/summary`` 这类接口调用。

Agent 层会在边界处把 ``SkillResult`` 转换成 ``AgentChatResponse``。
这样可以避免 skills 和 agent 互相导入，降低循环依赖风险。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillSourceRef:
    """技能结果里的来源引用。

    字段形态和 Agent API 的 ``AgentSourceRef`` 接近，但这里不直接依赖
    agent.schemas。这样技能层可以保持纯业务模块，后续也更容易复用到批处理、
    定时任务或独立课后产物生成接口。
    """

    type: str
    """来源类型，例如 segment / visual / knowledge_node。"""
    id: str
    """来源对象 ID，例如字幕片段 ID、图片 ID、知识节点 ID。"""
    text: str
    """展示给用户或写入产物时使用的引用摘要。"""
    ts: float | None = None
    """课堂内相对时间，单位秒；知识节点可能没有时间戳。"""


@dataclass(frozen=True)
class SkillArtifact:
    """技能生成的结构化产物。

    ``content`` 暂时保持宽松：总结是字符串，待办和自测题是结构化列表。
    等技能输出格式稳定后，可以拆成 SummaryArtifact、TodoArtifact、
    QuizArtifact 等更强类型。
    """

    type: str
    """产物类型，例如 summary / todos / quiz。"""
    title: str
    """前端展示标题，也是本地保存时判断文件名的依据。"""
    content: str | list[dict[str, Any]] | dict[str, Any]
    """产物正文。"""


@dataclass(frozen=True)
class SkillResult:
    """一次技能调用的统一结果。"""

    answer: str
    """可直接返回给用户的主回答。"""
    artifact: SkillArtifact | None = None
    """结构化产物。普通问答可以没有产物。"""
    source_refs: list[SkillSourceRef] = field(default_factory=list)
    """回答依据。"""
    warnings: list[str] = field(default_factory=list)
    """非致命提示，例如数据不足或规则版结果需要人工确认。"""


__all__ = ["SkillArtifact", "SkillResult", "SkillSourceRef"]
