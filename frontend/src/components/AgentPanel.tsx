import { useState } from "react";

import { chatWithAgent } from "../services/agentApi";
import { ApiError } from "../services/api";
import type {
  AgentArtifact,
  AgentIntent,
  AgentMessage,
  AgentSourceRef,
} from "../types/agent";
import type { LectureSession } from "../types/classroom";
import { formatClassTime } from "../utils/time";

// 课堂 Agent 面板。
//
// 它只依赖当前 dashboard 里选中的 session：
// - 实时课堂：session 来自 POST /sessions/start。
// - 历史课堂：session 来自 GET /sessions/{session_id}/history 后的 reducer 状态。
//
// 组件不读取 transcript/timeline/graph props，因为 Agent 的资料读取统一放在后端；
// 前端只负责把 prompt 和 session_id 发给 /agent/chat，并展示响应。
type AgentPanelProps = {
  session: LectureSession | null;
};

// 快捷按钮使用显式 mode，绕过后端关键词路由。这样即使 prompt 文案以后调整，
// 点击“总结重点”仍会稳定执行 summary skill。
const quickPrompts: Array<{ label: string; prompt: string; mode: AgentIntent }> = [
  { label: "总结重点", prompt: "总结这节课的重点", mode: "summary" },
  { label: "提取待办", prompt: "老师布置了什么作业或待办？", mode: "todos" },
  { label: "生成自测", prompt: "根据这节课出几道自测题", mode: "quiz" },
];

const intentLabels: Record<string, string> = {
  qa: "问答",
  summary: "总结",
  todos: "待办",
  quiz: "自测",
};

export function AgentPanel({ session }: AgentPanelProps) {
  // prompt 是输入框草稿；messages 是本面板的轻量聊天记录。它们不进入全局
  // classroomReducer，因为 Agent 对话不参与实时事件合并。
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitAgentPrompt(nextPrompt = prompt, mode: AgentIntent = "auto") {
    const trimmedPrompt = nextPrompt.trim();
    // 没有选中课堂时禁用提交；后端 Agent 必须拿到 session_id 才能读取课堂资料。
    if (!session || !trimmedPrompt || isLoading) {
      return;
    }

    setIsLoading(true);
    setError(null);
    // 先把用户消息追加到本地，让界面立即响应。若请求失败，只显示错误，不回滚
    // 用户输入记录，方便用户改写后重试。
    setMessages((current) => [
      ...current,
      {
        role: "user",
        content: trimmedPrompt,
      },
    ]);

    try {
      // 后端会根据 session_id 自行判断读取内存课堂还是历史课堂文件。
      const response = await chatWithAgent({
        session_id: session.session_id,
        prompt: trimmedPrompt,
        mode,
      });
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: response.answer,
          intent: response.intent,
          artifacts: response.artifacts,
          source_refs: response.source_refs,
          warnings: response.warnings,
        },
      ]);
      // 成功后清空输入框；快捷按钮提交时 nextPrompt 不等于当前 prompt，也同样安全。
      setPrompt("");
    } catch (caughtError) {
      setError(formatAgentError(caughtError));
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="panel agent-panel" aria-labelledby="agent-title">
      <div className="panel-header">
        <div>
          <h2 id="agent-title">课堂 Agent</h2>
          <span>{session ? session.title : "未选择课堂"}</span>
        </div>
      </div>

      <div className="agent-body">
        <div className="agent-quick-row">
          {quickPrompts.map((item) => (
            <button
              className="icon-text-button"
              disabled={!session || isLoading}
              key={item.mode}
              onClick={() => void submitAgentPrompt(item.prompt, item.mode)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="agent-messages" aria-live="polite">
          {/* aria-live 让辅助技术能感知新回答。这里不用复杂 markdown 渲染，
              第一版 answer 只按纯文本和换行展示。 */}
          {messages.length === 0 ? (
            <div className="agent-empty">选择课堂后即可提问</div>
          ) : (
            messages.map((message, index) => (
              <article className={`agent-message ${message.role}`} key={index}>
                <div className="agent-message-top">
                  <strong>{message.role === "user" ? "你" : "Agent"}</strong>
                  {message.intent ? <span>{intentLabels[message.intent]}</span> : null}
                </div>
                <p>{message.content}</p>
                {/* artifacts 是结构化结果，例如 todos/quiz。第一版用 details
                    保持紧凑展示，后续可替换为专门的卡片/列表组件。 */}
                {message.artifacts?.length ? (
                  <div className="agent-artifacts">
                    {message.artifacts.map((artifact, artifactIndex) => (
                      <ArtifactView artifact={artifact} key={artifactIndex} />
                    ))}
                  </div>
                ) : null}
                {/* source_refs 是 Agent 可信度的关键：用户能看到回答来自哪段字幕、
                    OCR 或知识节点。未来这里可以扩展为点击跳转到时间线。 */}
                {message.source_refs?.length ? (
                  <SourceRefs refs={message.source_refs} />
                ) : null}
                {message.warnings?.length ? (
                  <ul className="agent-warnings">
                    {message.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : null}
              </article>
            ))
          )}
        </div>

        {error ? <div className="agent-error">{error}</div> : null}

        <form
          className="agent-input-row"
          onSubmit={(event) => {
            event.preventDefault();
            void submitAgentPrompt();
          }}
        >
          <input
            disabled={!session || isLoading}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="问问这节课"
            value={prompt}
          />
          <button className="primary-button" disabled={!session || !prompt.trim() || isLoading}>
            {isLoading ? "处理中" : "发送"}
          </button>
        </form>
      </div>
    </section>
  );
}

function ArtifactView({ artifact }: { artifact: AgentArtifact }) {
  // 后端 artifact.content 允许文本或 JSON-like 结构。这里统一转成可读文本，
  // 保持组件无依赖；等 todos/quiz schema 固定后再做更精致的结构化渲染。
  const content =
    typeof artifact.content === "string"
      ? artifact.content
      : JSON.stringify(artifact.content, null, 2);

  return (
    <details>
      <summary>{artifact.title}</summary>
      <pre>{content}</pre>
    </details>
  );
}

function SourceRefs({ refs }: { refs: AgentSourceRef[] }) {
  // 来源列表目前只展示类型、时间和文本；不拼后端文件路径，避免前端绕过 API
  // 直接依赖 data/sessions 的本地存储结构。
  return (
    <div className="agent-source-list">
      {refs.map((ref) => (
        <div className="agent-source" key={`${ref.type}-${ref.id}`}>
          <span>
            {ref.type}
            {typeof ref.ts === "number" ? ` · ${formatClassTime(ref.ts)}` : ""}
          </span>
          <p>{ref.text}</p>
        </div>
      ))}
    </div>
  );
}

function formatAgentError(error: unknown): string {
  // ApiError 来自 services/api.ts，保留了后端返回的 detail。普通 Error 通常是
  // 网络/CORS/浏览器侧异常。
  if (error instanceof ApiError) {
    return error.detail;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Agent 请求失败";
}
