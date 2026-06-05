import type { LectureSession } from "../types/classroom";

// 后端 API 基地址。
// 默认指向 AGENTS.md / API_SCHEMA.md 约定的本地 FastAPI 服务。
// 如果以后前后端不在同一机器，可以通过 .env 设置 VITE_API_BASE_URL 覆盖。
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

// POST /sessions/start 的请求体。
// 字段名保持后端契约的 snake_case，避免在 service 层做不必要转换。
export type StartSessionPayload = {
  title?: string;
  course?: string | null;
  teacher?: string | null;
  language?: string;
  created_by?: string;
  device_id?: string | null;
};

// 统一 API 错误类型。
// 组件层捕获这个错误时，可以拿到 status 做更细的 UI 分支：
// 404 -> session 不存在，409 -> session 已结束，等等。
export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// 统一 JSON 请求 helper。
//
// 这里集中处理：
// - 拼接 API_BASE_URL。
// - 设置 Content-Type。
// - 把非 2xx 响应转换成 ApiError。
//
// UI 组件不要直接 fetch 后端，避免错误处理和 URL 配置散落在页面里。
async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response));
  }

  return response.json() as Promise<T>;
}

// FastAPI 的错误响应通常是 {"detail": "..."}。
// 如果后端返回非 JSON 或空 body，这里退回到 status 文案，保证页面总能显示
// 一个可读错误，而不是把 JSON 解析异常直接暴露给用户。
async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Fall through to a status-based message when the backend returns no JSON.
  }

  return `Request failed with status ${response.status}`;
}

// 创建课堂 session。
//
// 前端 MVP 给一组默认字段，这样用户点击“开始课堂”即可联调，不需要先填表单。
// 调用成功后，后端会返回 LectureSession，并在内存中创建对应 context 和图谱。
export function startSession(payload: StartSessionPayload = {}): Promise<LectureSession> {
  return requestJson<LectureSession>("/sessions/start", {
    method: "POST",
    body: JSON.stringify({
      title: "前端联调课堂",
      course: "EDU-Mate MVP",
      language: "zh-CN",
      created_by: "student",
      ...payload,
    }),
  });
}

// 结束课堂 session。
//
// 后端 end 接口是幂等的：重复结束同一节课不会产生重复事件语义。
// 结束时后端会保存 metadata/transcript/timeline/knowledge_graph 到 data/sessions。
export function endSession(sessionId: string): Promise<LectureSession> {
  return requestJson<LectureSession>(`/sessions/${sessionId}/end`, {
    method: "POST",
  });
}
