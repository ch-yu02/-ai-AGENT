// 前端 Agent API 类型。
//
// 字段名保持后端 Pydantic 模型的 snake_case，不在服务层做转换。这样
// docs/API_SCHEMA.md、后端 schemas.py 和前端类型可以一一对照，减少联调歧义。

export type AgentIntent = "auto" | "qa" | "summary" | "todos" | "quiz";
// strict 只基于课堂资料；grounded 允许模型结合课堂来源做补充解释。
export type AgentAnswerMode = "strict" | "grounded";
// 后端已经解析出的最终意图。响应里不会返回自动路由模式。
export type ResolvedAgentIntent = "qa" | "summary" | "todos" | "quiz";

export type AgentChatRequest = {
  // 当前正在录制或已打开历史课堂的 session_id。
  session_id: string;
  // 用户自然语言输入。
  prompt: string;
  // 自动路由模式表示交给后端 IntentRouter；快捷按钮会传显式模式。
  mode?: AgentIntent;
  // 只对 qa 生效。summary/todos/quiz 使用各自技能策略。
  answer_mode?: AgentAnswerMode;
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
  type: "segment" | "visual" | "knowledge_node" | "structured_note" | "timeline";
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

export type GlobalSearchRequest = {
  // 跨课堂搜索关键词或自然语言问题。
  query: string;
  // 可选课程过滤；为空时搜索全部历史课堂。
  course?: string | null;
  // 可选日期范围，格式 YYYY-MM-DD。
  date_from?: string | null;
  date_to?: string | null;
  // 最多返回多少条命中。
  limit?: number;
};

export type GlobalSearchSourceRef = {
  // 允许 knowledge_edge 等全局 RAG 文档类型，所以这里保持 string。
  type: string;
  id: string;
  ts?: number | null;
  text: string;
};

export type GlobalSearchHit = {
  session_id: string;
  title: string;
  course?: string | null;
  score: number;
  source_ref: GlobalSearchSourceRef;
};

export type GlobalSearchResponse = {
  query: string;
  answer: string;
  hits: GlobalSearchHit[];
  warnings: string[];
};

export type CourseSummary = {
  course: string;
  session_count: number;
  latest_session_id?: string | null;
  latest_title?: string | null;
  latest_start_time?: string | null;
  node_count: number;
  edge_count: number;
};

export type CourseListResponse = {
  courses: CourseSummary[];
  warnings: string[];
};

export type CourseKnowledgeTreeResponse = {
  course: string;
  session_count: number;
  knowledge_graph: unknown;
  warnings: string[];
};

// AgentPanel 内部消息模型。
//
// Agent 聊天记录主要存在组件状态里，不进入 classroomReducer 的实时消息合并。
// 历史课堂会从 data/sessions/{session_id}/agent_messages.json 读取旧对话，并在
// AgentPanel 初始化时恢复展示。
export type AgentMessage = {
  role: "user" | "assistant";
  content: string;
  intent?: ResolvedAgentIntent;
  artifacts?: AgentArtifact[];
  source_refs?: AgentSourceRef[];
  warnings?: string[];
};
