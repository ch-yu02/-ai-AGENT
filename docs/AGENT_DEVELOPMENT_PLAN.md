# EDU-Mate Agent Development Plan

本文档说明 EDU-Mate / Lecture-Link 从“实时课堂看板”升级为“课堂数据
Agent”的开发计划。目标是让用户可以在前端输入自然语言 prompt，后端
Agent 基于课堂数据完成问答、总结、待办提取和自测题生成。

## 1. 总体目标

当前系统已经具备：

1. 前端创建课堂 session。
2. 后端接收实时事件。
3. 前端实时展示字幕、时间线、图片/OCR 和知识图谱。
4. 结束课堂后保存本地文件。
5. mock sender 可以向前端已创建的 session 发送模拟课堂事件。

下一阶段 Agent 的目标是：

```text
用户自然语言 prompt
→ 后端 Agent 读取课堂数据
→ Agent 判断意图
→ 检索 transcript / timeline / OCR / knowledge graph
→ 调用对应技能
→ 返回答案、结构化结果和来源引用
→ 前端展示
```

Agent 第一版应服务于课堂数据，不做开放域闲聊。

## 2. Agent 能力范围

MVP Agent 需要支持四类 prompt：

| 用户意图 | 示例 prompt | 输出 |
| --- | --- | --- |
| 课堂问答 | `傅里叶变换这一段老师讲了什么？` | 带来源引用的回答 |
| 课堂总结 | `总结这节课的重点` | 分点总结 / 复习提纲 |
| 待办提取 | `老师布置了什么作业？` | 待办列表 |
| 自测题生成 | `根据这节课出 5 道题` | 题目、答案、解析 |

暂不支持：

- 开放域百科问答。
- 无课堂依据的自由创作。
- 自动控制硬件设备。
- 跨用户权限管理。
- 多 Agent 自主协作。

## 3. 推荐技术路线

分两层实现：

1. **轻量 Agent Router**
   - 负责接收 prompt。
   - 根据关键词或小模型判断用户意图。
   - 调用问答、总结、待办、出题等技能。
   - 第一版可以不依赖 LlamaIndex。

2. **LlamaIndex RAG 层**
   - 负责把课堂文件转换成可检索文档。
   - 建立单节课索引。
   - 检索相关片段。
   - 生成带来源的回答。

推荐顺序：

```text
先做可测试的 Agent API
→ 再接 LlamaIndex 单节课 RAG
→ 再做结构化 Skill
→ 最后做索引持久化和跨课堂检索
```

## 4. 目标目录结构

后端新增：

```text
backend/app/agent/
  __init__.py
  classroom_agent.py
  intent_router.py
  schemas.py
  source_refs.py

backend/app/rag/
  __init__.py
  documents.py
  index_manager.py
  query_service.py

backend/app/skills/
  __init__.py
  summarizer.py
  todo_detective.py
  quiz_master.py
  qa.py

backend/app/llm/
  __init__.py
  cloud_client.py
  settings.py
```

前端新增：

```text
frontend/src/components/AgentPanel.tsx
frontend/src/services/agentApi.ts
frontend/src/types/agent.ts
```

后续可新增：

```text
data/sessions/{session_id}/agent_messages.json
data/sessions/{session_id}/summary.md
data/sessions/{session_id}/todos.json
data/sessions/{session_id}/quiz.json
data/sessions/{session_id}/llama_index/
```

## 5. API 设计

新增接口：

```text
POST /agent/chat
```

请求：

```json
{
  "session_id": "lec_xxx",
  "prompt": "帮我总结这节课的重点",
  "mode": "auto"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `session_id` | string | 是 | 课堂 ID |
| `prompt` | string | 是 | 用户自然语言输入 |
| `mode` | string | 否 | `auto` / `qa` / `summary` / `todos` / `quiz` |

响应：

```json
{
  "session_id": "lec_xxx",
  "intent": "summary",
  "answer": "这节课主要讲了傅里叶变换的定义、时域和频域的关系……",
  "artifacts": [
    {
      "type": "summary",
      "title": "课堂总结",
      "content": "..."
    }
  ],
  "source_refs": [
    {
      "type": "segment",
      "id": "seg_002",
      "ts": 5.0,
      "text": "傅里叶变换可以把时域信号转换到频域……"
    }
  ],
  "warnings": []
}
```

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `intent` | string | Agent 判断出的意图 |
| `answer` | string | 给用户展示的主回答 |
| `artifacts` | object[] | 结构化结果，如 summary/todos/quiz |
| `source_refs` | object[] | 来源引用 |
| `warnings` | string[] | 数据不足、未找到依据、LLM 失败等提示 |

## 6. 阶段划分

### Phase 0：准备与契约确认

目标：明确 Agent 数据契约，不接 LlamaIndex，不接云端模型。

功能：

- 新增 `docs/AGENT_DEVELOPMENT_PLAN.md`。
- 在 `docs/API_SCHEMA.md` 中补充未来 `/agent/chat` 契约。
- 明确 Agent 只处理课堂数据。
- 明确 `source_refs` 格式。

验收：

- 文档能解释 Agent 能做什么、不能做什么。
- 前后端开发者能按文档实现第一版接口。

### Phase 1：本地 Agent 外壳

目标：先跑通前后端 Agent 闭环，不依赖 LlamaIndex 或云端 LLM。

后端功能：

- 新增 `backend/app/agent/schemas.py`。
- 新增 `ClassroomAgent`。
- 新增 `IntentRouter`。
- 新增 `POST /agent/chat`。
- 从内存中的 `ContextManager` 和 `KnowledgeGraphManager` 读取当前课堂数据。
- 对已结束课堂，优先复用后续 History API 的读取能力。

第一版路由规则：

```text
包含 总结 / 重点 / 提纲 → summary
包含 作业 / 待办 / 预习 / 考试 → todos
包含 出题 / 测验 / quiz / 选择题 → quiz
其他 → qa
```

第一版返回策略：

- `summary`：基于 transcript 前若干条和知识节点生成规则化摘要。
- `todos`：用关键词从 transcript 中提取疑似待办。
- `quiz`：用知识节点生成简单问答题。
- `qa`：关键词匹配 transcript，返回相关片段。

前端功能：

- 新增 `AgentPanel`。
- 用户输入 prompt。
- 调用 `POST /agent/chat`。
- 展示 answer、artifacts、source_refs、warnings。

测试：

- `test_agent_intent_router.py`
- `test_classroom_agent.py`
- 前端 service/reducer 测试。

验收：

- 用户能在前端输入 `总结这节课` 并看到结果。
- 用户能输入 `有什么作业` 并看到待办候选。
- 用户能输入 `出几道题` 并看到题目。
- 不需要 API key。

### Phase 2：History API 与历史课堂 Agent

目标：让 Agent 能处理后端重启后的历史课堂。

后端功能：

- 扩展 `LocalStorage` 读取：
  - `list_sessions()`
  - `read_session_artifacts(session_id)`
  - `read_transcript(session_id)`
  - `read_timeline(session_id)`
  - `read_knowledge_graph(session_id)`
- 新增历史接口：

```text
GET /history
GET /history/{session_id}
```

- Agent 查询 session 时：
  - 若 session 在内存中，读内存。
  - 若不在内存中，读本地保存文件。

前端功能：

- 历史课堂列表。
- 历史课堂详情。
- 在历史课堂详情中使用 AgentPanel。

测试：

- 存储读取测试使用 `tempfile.TemporaryDirectory()`。
- 不依赖真实 `data/sessions/`。

验收：

- 后端重启后仍可打开已保存课堂。
- 用户能对历史课堂提问。

### Phase 3：接入 LlamaIndex 单节课 RAG

目标：让问答从规则匹配升级为检索增强生成。

后端功能：

- 新增 `backend/app/rag/documents.py`：
  - transcript segment → LlamaIndex Document
  - visual OCR/caption → LlamaIndex Document
  - knowledge node/edge → LlamaIndex Document
- 每个 Document 携带 metadata：

```json
{
  "session_id": "lec_xxx",
  "type": "transcript",
  "source_id": "seg_002",
  "ts": 5.0
}
```

- 新增 `query_service.py`：
  - `query_session(session_id, prompt)`
  - 返回 answer 和 source refs。

依赖建议：

```text
llama-index
```

若使用本地中文 embedding，可能还需要：

```text
llama-index-embeddings-huggingface
sentence-transformers
torch
```

若使用云端模型，按 provider 添加：

```text
llama-index-llms-openai
```

或后续 DeepSeek/Qwen 兼容 OpenAI API 的 client。

第一版索引策略：

- 先临时构建内存索引。
- 每次 `/agent/chat` 根据 session artifacts 构建小型索引并查询。
- 课堂数据量变大后再做持久化。

Prompt 约束：

```text
只能基于课堂资料回答。
如果课堂资料中没有找到依据，明确说明没有找到。
回答必须尽量引用来源片段。
```

测试：

- 用小型 fixture 构造 transcript/timeline/graph。
- 单元测试只验证 documents 转换和 source_refs 映射。
- LLM 调用用 fake client 或 mock query service。

验收：

- 用户问具体知识点时，答案能引用相关字幕或 OCR。
- 找不到内容时不会编造。

### Phase 4：结构化 Skills

目标：把总结、待办和自测题变成正式课后产物。

后端功能：

- `SummarizerSkill`
  - 输出 `summary.md`。
  - 包含课堂重点、知识脉络、公式/概念、复习建议。

- `TodoDetectiveSkill`
  - 输出 `todos.json`。
  - 字段：`title`、`type`、`due_time`、`source_refs`、`confidence`。

- `QuizMasterSkill`
  - 输出 `quiz.json`。
  - 字段：`question`、`type`、`options`、`answer`、`explanation`、`source_refs`。

新增接口可选：

```text
POST /sessions/{session_id}/skills/summary
POST /sessions/{session_id}/skills/todos
POST /sessions/{session_id}/skills/quiz
```

也可以统一走：

```text
POST /agent/chat
```

前端功能：

- AgentPanel 展示结构化 artifact。
- 课后区域展示 summary/todos/quiz。
- 支持重新生成。

测试：

- 使用固定课堂 fixture。
- 检查结构化字段完整性。
- 检查结果保存路径。

验收：

- 用户输入 `总结这节课`，生成并展示 summary。
- 用户输入 `提取作业`，生成 todos。
- 用户输入 `出 5 道题`，生成 quiz。

### Phase 5：Cloud LLM Client

目标：统一管理云端模型调用，避免每个 Skill 自己访问 provider。

后端功能：

- 新增 `backend/app/llm/cloud_client.py`。
- 新增 `backend/app/llm/settings.py`。
- 支持环境变量配置：

```text
LLM_PROVIDER=deepseek
LLM_API_KEY=...
LLM_MODEL=...
LLM_BASE_URL=...
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=1
```

- 支持：
  - timeout
  - retry
  - 错误包装
  - structured JSON 输出校验
  - fallback 文案

当前实现状态：

- `CloudLLMClient` 使用 OpenAI-compatible `/chat/completions` 协议，默认支持
  DeepSeek，也可通过 `LLM_BASE_URL` 接入其他兼容供应商。
- 没有 `LLM_API_KEY` 时，系统不会创建云端客户端，summary/todos/quiz 继续走
  本地规则版。
- `SummarizerSkill`、`TodoDetectiveSkill`、`QuizMasterSkill` 已支持可选
  LLM-backed 输出；模型失败、超时、返回非 JSON 或结构不符合预期时会回退规则版。
- `QuizMasterSkill` 仍只在用户主动请求出题时运行；结束课堂只自动生成
  summary/todos，不自动写 `quiz.json`。
- 单元测试使用 fake client，不访问真实云端模型。

安全要求：

- API key 只在后端读取。
- 不允许前端直接持有 API key。
- `.env` 不提交 git。

测试：

- mock HTTP client。
- 测试超时、失败、非 JSON、schema 不匹配。

验收：

- Skill 可以切换 rule-based / LLM-backed 实现。
- LLM 失败时前端能看到明确错误，不影响课堂数据保存。

### Phase 6：索引持久化与增量更新

目标：提升历史课堂 Agent 的响应速度。

当前先完成 Phase 6a：可选 LlamaIndex 单节课临时索引。

启用方式：

```text
RAG_QUERY_BACKEND=llamaindex
```

可选依赖：

```text
llama-index
```

如果使用 OpenAI-compatible LLM 或 embedding provider，再按实际供应商安装
对应 LlamaIndex 扩展。当前代码不把 `llama-index` 作为硬依赖；未安装或查询
失败时会回退到本地词法检索，并在 warning 中说明。

已实现：

- `backend/app/rag/llama_query_service.py`
  - 把内部 `RagDocument` 转换为 `llama_index.core.Document`。
  - 使用 `VectorStoreIndex.from_documents()` 构建单节课内存索引。
  - 从 `response.source_nodes` 映射回 `RagSourceRef`。
  - 失败时回退 `QueryService`。
- `backend/app/rag/service_factory.py`
  - 默认使用词法检索。
  - `RAG_QUERY_BACKEND=llamaindex` 时切换到 LlamaIndex 服务。
- `QaSkill` 通过工厂创建查询服务，不直接绑定某个 RAG 实现。

后端功能：

- 结束课堂时构建索引：

```text
data/sessions/{session_id}/llama_index/
```

- 如果索引存在，直接加载。
- 如果索引不存在，按需重建。
- 未来支持课堂中周期性增量索引。

限制：

- 实时课堂不建议每条字幕都重建索引。
- 可以按 N 条 transcript 或 N 秒做批量更新。

验收：

- 历史课堂第一次查询可重建索引。
- 第二次查询能复用索引。

### Phase 7：跨课堂搜索与长期记忆

目标：支持跨多个 session 的学习助手能力。

功能：

- 全局索引：

```text
data/indexes/global/
```

- 支持问题：

```text
我之前哪节课讲过采样定理？
把最近三节通信原理课的重点串起来。
找出所有老师布置过的作业。
```

前端功能：

- 全局 Agent 入口。
- 按课程或日期过滤。
- 来源引用跳转到对应历史课堂。

验收：

- 可以跨 session 检索。
- 回答中能标注来自哪节课。

## 7. 数据转换设计

### Transcript Document

输入：

```json
{
  "segment_id": "seg_002",
  "start_ts": 5.0,
  "end_ts": 9.6,
  "text": "傅里叶变换可以把时域信号转换到频域。"
}
```

Document：

```text
text = "[5.0s-9.6s] 傅里叶变换可以把时域信号转换到频域。"
metadata = {
  session_id,
  type: "segment",
  source_id: "seg_002",
  ts: 5.0
}
```

### Visual Document

输入：

```json
{
  "image_id": "img_001",
  "capture_ts": 10.5,
  "ocr_text": "X(f)=∫x(t)e^{-j2πft}dt",
  "caption": "课件展示傅里叶变换公式。"
}
```

Document：

```text
text = "[10.5s] OCR: ... Caption: ..."
metadata = {
  session_id,
  type: "visual",
  source_id: "img_001",
  ts: 10.5
}
```

### Knowledge Document

输入：

```json
{
  "node_id": "node_fourier_transform",
  "label": "傅里叶变换",
  "summary": "将信号从时域表示转换为频域表示的数学工具"
}
```

Document：

```text
text = "知识点：傅里叶变换。说明：将信号从时域表示转换为频域表示的数学工具。"
metadata = {
  session_id,
  type: "knowledge_node",
  source_id: "node_fourier_transform"
}
```

## 8. 前端 AgentPanel 设计

组件职责：

- 接收当前 `session_id`。
- 输入自然语言 prompt。
- 调用 `agentApi.chat()`。
- 展示加载中、错误、回答、结构化产物和来源引用。

推荐交互：

```text
输入框 placeholder: "问问这节课，比如：总结重点 / 有什么作业 / 出几道题"
快捷按钮：总结重点、提取待办、生成自测题
回答区域：Markdown 文本
来源区域：segment / visual / knowledge 引用
```

前端状态：

```ts
type AgentMessage = {
  role: "user" | "assistant";
  content: string;
  intent?: string;
  artifacts?: AgentArtifact[];
  source_refs?: AgentSourceRef[];
  warnings?: string[];
};
```

## 9. 测试策略

后端测试：

- IntentRouter：
  - prompt 到 intent 的映射。
- Agent schema：
  - 请求/响应模型校验。
- Documents：
  - transcript/timeline/graph 到 Document 的转换。
- Query service：
  - fake query engine 返回可控结果。
- Skills：
  - 规则版 summary/todos/quiz 输出稳定。

前端测试：

- `agentApi.chat()` 请求格式。
- AgentPanel 基础渲染。
- loading/error/success 状态。
- artifacts/source_refs 展示。

不建议：

- 单元测试直接调用真实云端 LLM。
- 测试依赖真实 `data/sessions/`。
- 测试依赖前端 dev server。

## 10. 风险与限制

### 上下文长度

一节课 transcript 可能很长，不能直接塞进 prompt。

缓解：

- 使用 LlamaIndex 检索。
- 分段总结。
- 使用 `get_compressed_context()`。

### 幻觉

LLM 可能编造课堂中没有出现的内容。

缓解：

- 强制基于课堂资料回答。
- 找不到依据时明确说明。
- 返回 source_refs。
- 前端展示引用。

### 实时数据不完整

正在上课时，ASR/OCR/知识抽取可能尚未完整。

缓解：

- 响应中加入 warning。
- 标记 `data_status=recording`。
- 对高质量问答优先使用已结束课堂。

### 依赖变重

LlamaIndex、本地 embedding、torch 可能显著增加安装体积。

缓解：

- 第一版先不接 LlamaIndex。
- 允许使用云端 embedding。
- 本地 embedding 作为可选安装。

### API Key 与隐私

课堂内容可能被发送到云端模型。

缓解：

- API key 只放后端环境变量。
- `.env` 不提交 git。
- 前端提示云端调用。
- 后续支持本地模型模式。

## 11. 推荐立即执行顺序

当前最推荐的实际开发顺序：

1. 实现 History API 和 LocalStorage 读取能力。
2. 新增 `/agent/chat` schema 和空实现。
3. 实现 rule-based IntentRouter。
4. 实现不依赖 LLM 的 QA/Summary/Todos/Quiz 初版。
5. 前端新增 AgentPanel。
6. 接入 LlamaIndex 单节课 RAG。
7. 引入 CloudLLMClient。
8. 将 summary/todos/quiz 保存为课后产物。
9. 做索引持久化。
10. 做跨课堂搜索。

这样能保证每一步都有可演示结果，而不是一次性引入大模型和复杂 Agent
框架后才看到效果。
