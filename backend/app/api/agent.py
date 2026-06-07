"""课堂 Agent 的 HTTP 路由。

本模块保持 API 层“薄路由”原则：
- 请求/响应模型来自 ``backend.app.agent.schemas``。
- 业务逻辑全部委托给 ``ClassroomAgent``。
- 这里只做领域异常到 HTTP 状态码的映射。

这样后续给 Agent 接 LlamaIndex、Cloud LLM 或更多 Skill 时，不需要把复杂逻辑
搬进路由文件。
"""

from fastapi import APIRouter, HTTPException

from backend.app.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentSessionNotFoundError,
    GlobalSearchRequest,
    GlobalSearchResponse,
    classroom_agent,
    global_search_service,
)


router = APIRouter(prefix="/agent", tags=["agent"])
"""Agent API 路由，当前只有自然语言入口 ``POST /agent/chat``。"""


@router.post("/chat", response_model=AgentChatResponse)
async def chat(request: AgentChatRequest) -> AgentChatResponse:
    """针对一次 prompt 运行课堂 Agent。

    404 的语义是“内存和本地历史文件都找不到这个 session”。如果 session 存在
    但课堂资料不足，Agent 会正常返回 200，并在 ``warnings`` 中说明数据不足。
    """
    try:
        return classroom_agent.chat(request)
    except AgentSessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/search", response_model=GlobalSearchResponse)
async def search(request: GlobalSearchRequest) -> GlobalSearchResponse:
    """跨已保存历史课堂搜索课堂资料。

    这个接口是 Phase 7 的第一版“长期记忆”入口。它只读取本地已保存历史课堂，
    不搜索正在录制但尚未结束保存的内存课堂。这样用户得到的结果都能对应到
    ``data/sessions/{session_id}`` 中稳定存在的课后档案。
    """
    return global_search_service.search(request)
