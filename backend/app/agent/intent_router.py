"""Rule-based intent routing for the first classroom Agent.

第一版 Agent 的目标是“先跑通可测试闭环”，所以这里使用可预测的关键词规则，
而不是直接接 LLM 做意图分类。这样做有三个好处：

1. 单元测试稳定，不依赖网络、API key 或模型版本。
2. 前端 demo 可离线运行，符合当前本地 MVP 阶段。
3. 后续替换为小模型/LLM router 时，只需要保持 ``route()`` 的输入输出契约。
"""

from .schemas import AgentIntent, ResolvedAgentIntent


class IntentRouter:
    """Resolve a user prompt to one of the supported classroom skills.

    路由优先级是 summary → todos → quiz → qa。这个顺序有意把“总结重点”
    这类高频入口放前面；如果 prompt 同时包含多个关键词，显式快捷按钮应通过
    ``mode`` 指定目标技能，避免关键词冲突。
    """

    # 关键词覆盖中文课堂场景和少量英文入口。规则保持简单，避免把 router
    # 写成隐形 NLP 系统；真正复杂的意图理解留给后续 LLM Router。
    _summary_keywords = ("总结", "重点", "提纲", "复习", "概括", "summary")
    _todo_keywords = ("作业", "待办", "预习", "考试", "任务", "todo", "deadline")
    _quiz_keywords = ("出题", "出", "测验", "quiz", "选择题", "自测", "题目", "练习")

    def route(self, prompt: str, mode: AgentIntent = "auto") -> ResolvedAgentIntent:
        """Return the requested intent, honoring explicit non-auto modes.

        ``mode`` 是前端快捷按钮和未来技能入口的“人工指定路线”。只要它不是
        ``auto``，这里就直接返回，不再检查 prompt。这让 UI 能稳定调用某个
        技能，即使按钮文案后来变化也不会影响后端行为。
        """
        if mode != "auto":
            return mode

        # 统一小写主要服务英文关键词；中文不受影响。
        normalized = prompt.strip().lower()
        if any(keyword in normalized for keyword in self._summary_keywords):
            return "summary"
        if any(keyword in normalized for keyword in self._todo_keywords):
            return "todos"
        if any(keyword in normalized for keyword in self._quiz_keywords):
            return "quiz"
        return "qa"


__all__ = ["IntentRouter"]
