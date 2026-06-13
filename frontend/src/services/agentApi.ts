import { requestJson } from "./api";
import type {
  AgentChatRequest,
  AgentChatResponse,
  GlobalSearchRequest,
  GlobalSearchResponse,
} from "../types/agent";

// Agent HTTP 客户端。
//
// 组件层不直接 fetch，继续沿用 frontend/src/services 的边界。这样 API 基地址、
// 请求头和错误转换都复用 api.ts 里的 requestJson，AgentPanel 只处理界面状态。
export function chatWithAgent(request: AgentChatRequest): Promise<AgentChatResponse> {
  return requestJson<AgentChatResponse>("/agent/chat", {
    method: "POST",
    body: JSON.stringify({
      // 默认自动路由，允许调用方通过 request.mode 覆盖为 summary/todos/quiz/qa。
      mode: "auto",
      // 默认严格依据课堂资料；用户在 AgentPanel 开启“模型补充”后才会切换。
      answer_mode: "strict",
      ...request,
    }),
  });
}

export function searchAcrossClassrooms(
  request: GlobalSearchRequest,
): Promise<GlobalSearchResponse> {
  return requestJson<GlobalSearchResponse>("/agent/search", {
    method: "POST",
    body: JSON.stringify({
      limit: 8,
      ...request,
    }),
  });
}
