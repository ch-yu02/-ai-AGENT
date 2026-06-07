"""课堂 Agent 包入口。

这里集中导出 Agent 层的公共类型，并创建默认 ``classroom_agent`` 单例。
API 路由导入这个单例即可复用全局的 ContextManager、KnowledgeGraphManager
和 LocalStorage，与现有 sessions/events 路由保持同一套运行时状态。
"""

from backend.app.core import context_manager, knowledge_graph_manager
from backend.app.storage import local_storage

from .classroom_agent import AgentSessionNotFoundError, ClassroomAgent
from .intent_router import IntentRouter
from .schemas import (
    AgentArtifact,
    AgentChatRequest,
    AgentChatResponse,
    AgentSourceRef,
)


classroom_agent = ClassroomAgent(
    context_manager=context_manager,
    knowledge_graph_manager=knowledge_graph_manager,
    storage=local_storage,
)
"""默认 Agent 实例。

测试中通常直接创建 ``ClassroomAgent`` 并传入临时管理器/存储；生产路由
使用这里的全局实例，读取当前应用正在维护的课堂内存和本地历史文件。
"""


__all__ = [
    "AgentArtifact",
    "AgentChatRequest",
    "AgentChatResponse",
    "AgentSessionNotFoundError",
    "AgentSourceRef",
    "ClassroomAgent",
    "IntentRouter",
    "classroom_agent",
]
