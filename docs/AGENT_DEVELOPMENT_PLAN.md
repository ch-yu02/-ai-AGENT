# EDU-Mate Agent Development Plan

本文档记录 EDU-Mate / Lecture-Link 课堂 Agent 的当前状态和后续开发重点。
项目已经从“实时课堂看板”进入“可演示课堂 Agent”阶段。

## 当前状态

已完成能力：

- 实时课堂：创建/结束课堂、接收事件、WebSocket 推送字幕、图片/OCR、时间线和知识图谱。
- 历史课堂：结束后保存本地文件，前端可打开历史详情并删除本地历史。
- 单节课堂 Agent：`POST /agent/chat` 支持 `qa` / `summary` / `todos` / `quiz`。
- 课后产物：
  - 结束课堂自动生成 `summary.md` 和 `todos.json`。
  - `quiz.json` 只在用户主动生成自测题后保存。
  - Agent 对话保存到 `agent_messages.json`，打开历史课堂时恢复。
- 可选 Cloud LLM：配置 `LLM_API_KEY` 后，summary/todos/quiz 优先尝试云端模型，失败时回退规则版。
- 可选单节课 LlamaIndex：`RAG_QUERY_BACKEND=llamaindex` 时启用，结束课堂后尝试保存 `llama_index/`，查询失败时回退词法检索。
- 跨课堂搜索第一版：`POST /agent/search` 可搜索已保存历史课堂，支持课程和日期过滤，前端可打开命中课堂并定位来源。
- 本地全局搜索快照：跨课堂搜索会写出 `data/indexes/global/documents.json`，但目前仍是词法搜索快照，不是真正向量索引。

主要运行时产物：

```text
data/sessions/{session_id}/metadata.json
data/sessions/{session_id}/transcript.md
data/sessions/{session_id}/timeline.json
data/sessions/{session_id}/knowledge_graph.json
data/sessions/{session_id}/summary.md
data/sessions/{session_id}/todos.json
data/sessions/{session_id}/quiz.json
data/sessions/{session_id}/agent_messages.json
data/sessions/{session_id}/agent_artifacts.json
data/sessions/{session_id}/llama_index/
data/indexes/global/documents.json
```

## 当前接口

### `POST /agent/chat`

单节课堂 Agent 入口，用于对录制中课堂或历史课堂问答、总结、提取待办、生成自测题。

请求：

```json
{
  "session_id": "lec_xxx",
  "prompt": "帮我总结这节课的重点",
  "mode": "auto"
}
```

`mode` 可选：`auto` / `qa` / `summary` / `todos` / `quiz`。

响应核心字段：

- `intent`：识别出的意图。
- `answer`：主回答。
- `artifacts`：结构化产物。
- `source_refs`：来源引用。
- `warnings`：数据不足、LLM 失败、检索回退等提示。

### `POST /agent/search`

跨课堂搜索入口，用于在已保存历史课堂中搜索知识点、作业、概念或其他课堂资料。

请求：

```json
{
  "query": "哪节课讲过采样定理",
  "course": "通信原理",
  "date_from": "2026-06-01",
  "date_to": "2026-06-09",
  "limit": 8
}
```

响应核心字段：

- `answer`：搜索结果摘要。
- `hits`：命中列表，每项包含 `session_id`、课堂标题、课程、分数和 `source_ref`。
- `warnings`：坏历史目录跳过、索引回退等提示。

## 后端结构

核心模块：

```text
backend/app/agent/
  classroom_agent.py
  global_search.py
  intent_router.py
  schemas.py
  source_refs.py

backend/app/rag/
  documents.py
  query_service.py
  llama_query_service.py
  service_factory.py

backend/app/skills/
  qa.py
  summarizer.py
  todo_detective.py
  quiz_master.py
  llm_support.py

backend/app/llm/
  cloud_client.py
  settings.py
```

职责边界：

- API 路由只做参数接收、错误转换和 manager/agent 调用。
- 课堂数据读写继续放在 `LocalStorage`。
- Agent 负责意图识别和技能编排。
- RAG 层负责把课堂历史转换为可检索文档。
- Skill 层负责生成 summary/todos/quiz/qa 结果。

## 前端结构

核心入口：

```text
frontend/src/components/AgentPanel.tsx
frontend/src/components/GlobalSearchPanel.tsx
frontend/src/services/agentApi.ts
frontend/src/types/agent.ts
```

已完成表现：

- 历史课堂详情中可直接查看 summary/todos/quiz。
- 用户主动点击或输入后才生成 quiz。
- Agent 对话在历史课堂重新打开后可以恢复。
- 全局搜索结果可以打开对应历史课堂，并尽量高亮字幕、图片/OCR 或时间线来源。

## 未完成能力

### 真实全局向量索引

当前只有 `data/indexes/global/documents.json` 文档快照，搜索仍是词法评分。

未完成原因：

- 需要选择 embedding provider 和索引持久化策略。
- LlamaIndex、embedding、本地模型依赖较重，不适合作为默认硬依赖。
- 历史课堂删除后，全局索引也要同步更新或重建。

建议实现：

1. 新增 `backend/app/rag/global_index_service.py`。
2. 使用 `data/indexes/global/` 保存真正 LlamaIndex 全局索引。
3. `POST /agent/search` 优先查全局向量索引，失败时回退当前词法搜索。
4. 删除历史课堂后同步重建或标记相关文档失效。

### 录制中增量索引

当前单节课索引主要在结束课堂后持久化；录制中 QA 仍依赖内存文档和当前查询服务。

未完成原因：

- 每条字幕都重建索引会浪费性能。
- ASR/OCR/VLM 结果可能延迟或修正，需要去重和更新策略。
- 实时事件请求不应被重索引阻塞。

建议实现：

1. 为 session 增加 dirty 标记。
2. 每 N 条字幕或 N 秒批量刷新临时索引。
3. 结束课堂时构建最终完整索引。
4. 后续可把刷新放入后台任务队列。

### 真实 Provider Smoke Test

当前 LLM 和 LlamaIndex 测试都使用 fake client，不访问真实 provider。

未完成原因：

- 真实调用需要 API key、网络、额度和模型版本。
- 不同 provider 的 JSON 输出稳定性不同。
- 云端调用涉及课堂隐私，需要明确开关和文档。

建议实现：

1. 增加 `scripts/dev.sh llm-smoke`。
2. 无 `LLM_API_KEY` 时跳过并提示。
3. 有 key 时用固定课堂 fixture 测 summary/todos/quiz。
4. 检查结构化输出，不合格时确认 fallback 和 warning。

### URL 深链接

当前搜索结果可以在当前页面打开历史课堂并高亮来源，但刷新页面后状态会丢失。

未完成原因：

- 前端还没有路由层。
- 当前历史课堂和 source_ref 只存在 App 内存状态里。
- 图谱节点/边的精确聚焦还不完整。

建议实现：

```text
/?session_id=lec_xxx&source_type=segment&source_id=seg_001
```

App 启动时读取 URL，自动打开历史课堂，并把 focused source 传给对应面板。

### 本地模型模式

当前支持规则版 fallback 和 OpenAI-compatible 云端模型，还没有正式接本地 LLM/embedding。

未完成原因：

- 本地模型运行时差异大，例如 Ollama、vLLM、llama.cpp。
- 本地 embedding 依赖和硬件要求较重。
- 本地模型的结构化 JSON 稳定性需要单独验证。

建议实现：

```text
LLM_PROVIDER=local
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=...
```

先支持 OpenAI-compatible 本地服务，再补充 smoke 文档，不放入默认测试。

## 下一步顺序

建议按验证收益优先：

1. 增加真实 LLM smoke 脚本和使用文档。
2. 做 URL 深链接和图谱来源高亮。
3. 做全局 LlamaIndex 向量索引。
4. 做录制中批量增量索引。
5. 做本地模型模式文档和 smoke test。

默认测试仍应保持不依赖网络、不依赖真实 API key、不依赖重量级本地模型。
