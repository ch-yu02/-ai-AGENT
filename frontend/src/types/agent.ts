// 前端 Agent API 类型。
//
// 字段名保持后端 Pydantic 模型的 snake_case，不在 service 层做转换。这样
// docs/API_SCHEMA.md、后端 schemas.py 和前端类型可以一一对照，减少联调歧义。

export type AgentIntent = "auto" | "qa" | "summary" | "todos" | "quiz";
// 后端已经解析出的最终意图。响应里不会返回 auto。
export type ResolvedAgentIntent = "qa" | "summary" | "todos" | "quiz";

export type AgentChatRequest = {
  // 当前正在录制或已打开历史课堂的 session_id。
  session_id: string;
  // 用户自然语言输入。
  prompt: string;
  // auto 表示交给后端 IntentRouter；快捷按钮会传显式模式。
  mode?: AgentIntent;
};

export type AgentArtifact = {
  // summary / todos / quiz 等产物类型。
  type: string;
  // 前端折叠区标题。
  title: string;
  // 规则版 summary 是字符串；todos/quiz 是结构化数组。后续 Skill 稳定后可再收紧。
  content: string | Record<string, unknown> | Array<Record<string, unknown>>;
};

export type AgentSourceRef = {
  // 来源类型与后端 AgentSourceRef 对齐。
  type: "segment" | "visual" | "knowledge_node" | "timeline";
  // segment_id / image_id / node_id / timeline item_id。
  id: string;
  // 课堂内时间，知识节点可能没有。
  ts?: number | null;
  // 展示给用户看的引用文本。
  text: string;
};

export type AgentChatResponse = {
  session_id: string;
  intent: ResolvedAgentIntent;
  answer: string;
  artifacts: AgentArtifact[];
  source_refs: AgentSourceRef[];
  warnings: string[];
};

// AgentPanel 内部消息模型。
//
// 目前 Agent 聊天记录只存在组件状态里，不进入 classroomReducer。原因是它不参与
// 实时事件合并，也不会影响 transcript/timeline/visual/graph 四个课堂面板。
// 后续如果要保存 data/sessions/{session_id}/agent_messages.json，可再提升到 store。
export type AgentMessage = {
  role: "user" | "assistant";
  content: string;
  intent?: ResolvedAgentIntent;
  artifacts?: AgentArtifact[];
  source_refs?: AgentSourceRef[];
  warnings?: string[];
};
