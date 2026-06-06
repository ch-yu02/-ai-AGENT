import { requestJson } from "./api";
import type { AgentChatRequest, AgentChatResponse } from "../types/agent";

// Agent HTTP client。
//
// 组件层不直接 fetch，继续沿用 frontend/src/services 的边界。这样 API_BASE_URL、
// Content-Type、错误转换都复用 api.ts 里的 requestJson，AgentPanel 只处理 UI 状态。
export function chatWithAgent(request: AgentChatRequest): Promise<AgentChatResponse> {
  return requestJson<AgentChatResponse>("/agent/chat", {
    method: "POST",
    body: JSON.stringify({
      // 默认 auto，允许调用方通过 request.mode 覆盖为 summary/todos/quiz/qa。
      mode: "auto",
      ...request,
    }),
  });
}
