"""课堂课后技能包。

skills 层负责“把课堂资料变成具体学习产物”。它位于 Agent 和 RAG 之间：

- Agent 负责读取 session、判断意图、组装 API 响应。
- RAG 负责把课堂资料转换为可检索文档并完成查询。
- Skills 负责总结、待办、自测题、问答等具体能力。

这种拆分能让后续接入 LLM 时更稳：例如只替换 ``SummarizerSkill`` 的内部
实现，就可以把规则版总结升级为云端模型总结，而不影响 API 路由和前端。
"""

from .qa import QaSkill
from .quiz_master import QuizMasterSkill
from .schemas import SkillArtifact, SkillResult, SkillSourceRef
from .summarizer import SummarizerSkill
from .todo_detective import TodoDetectiveSkill


__all__ = [
    "QaSkill",
    "QuizMasterSkill",
    "SkillArtifact",
    "SkillResult",
    "SkillSourceRef",
    "SummarizerSkill",
    "TodoDetectiveSkill",
]
