# EDU-Mate Agent Development Plan

本文档记录 EDU-Mate / Lecture-Link 课堂 Agent 的当前状态和后续开发重点。
项目已经从“实时课堂看板”进入“可演示课堂 Agent”阶段。

## 当前状态

已完成能力：

- 实时课堂：创建/结束课堂、接收事件、WebSocket 推送字幕、图片/OCR、时间线和知识图谱。
- 历史课堂：结束后保存本地文件，前端可打开历史详情并删除本地历史。
- 单节课堂 Agent：`POST /agent/chat` 支持 `qa` / `summary` / `todos` / `quiz`；QA 支持 strict 与 grounded 两种答疑模式。
- 课后产物：
  - 结束课堂自动生成 `summary.md` 和 `todos.json`。
  - `quiz.json` 只在用户主动生成自测题后保存。
  - Agent 对话保存到 `agent_messages.json`，打开历史课堂时恢复。
- 可选 LLM：云端 provider 配置 `LLM_API_KEY` 后启用；`LLM_PROVIDER=local` 可连接本地 OpenAI-compatible 服务。
- 可选单节课 LlamaIndex：`RAG_QUERY_BACKEND=llamaindex` 时启用，结束课堂后尝试保存 `llama_index/`，查询失败时回退词法检索。
- 跨课堂搜索第一版：`POST /agent/search` 可搜索已保存历史课堂，支持课程和日期过滤，前端可打开命中课堂并定位来源。
- 可选全局 LlamaIndex：`GLOBAL_SEARCH_BACKEND=llamaindex` 时启用，使用 `data/indexes/global/llama_index/` 作为全局向量索引目录，失败时回退词法搜索。
- URL 深链接：历史课堂支持 `session_id/source_type/source_id` query，刷新或复制链接后可恢复定位。
- Provider smoke：`scripts/dev.sh llm-smoke` 可手动验证真实 LLM provider。

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
data/indexes/global/manifest.json
data/indexes/global/llama_index/
```

## 当前接口

### `POST /agent/chat`

单节课堂 Agent 入口，用于对录制中课堂或历史课堂问答、总结、提取待办、生成自测题。

请求：

```json
{
  "session_id": "lec_xxx",
  "prompt": "帮我总结这节课的重点",
  "mode": "auto",
  "answer_mode": "strict"
}
```

`mode` 可选：`auto` / `qa` / `summary` / `todos` / `quiz`。
`answer_mode` 只对 QA 生效：

- `strict`：默认模式，只依据课堂资料回答。
- `grounded`：先依据课堂资料，再允许 LLM 使用通用知识补充解释；返回 warning 标明包含模型补充。

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
  global_index_service.py
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
- URL query 可恢复历史课堂和来源定位，例如
  `?session_id=lec_xxx&source_type=segment&source_id=seg_001`。
- 知识图谱节点/边也支持搜索来源高亮。

## 剩余能力

### 已完成：真实全局向量索引入口

当前已经有可选全局 LlamaIndex 主链路：

- 默认 `GLOBAL_SEARCH_BACKEND=lexical`，继续使用确定性词法搜索。
- 设置 `GLOBAL_SEARCH_BACKEND=llamaindex` 后，`POST /agent/search` 会优先构建或加载 `data/indexes/global/llama_index/`。
- `manifest.json` 记录文档快照指纹，历史课堂变化后自动重建索引。
- 索引不可用、依赖未安装或 provider 失败时，自动回退词法搜索并返回 warning。

仍可增强：

1. 增加真实 embedding provider 的安装说明。
2. 为全局索引增加独立 rebuild 命令，避免首次搜索承担全部构建成本。
3. 增加更多语义搜索评测 fixture。

### 暂缓：录制中增量索引

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

本阶段按需求暂不开发。

### 已完成：真实 Provider Smoke Test

当前已增加：

- `backend/scripts/llm_smoke.py`
- `scripts/dev.sh llm-smoke`

行为：

- 云端 provider 无 `LLM_API_KEY` 时跳过。
- 有真实 provider 或 `LLM_PROVIDER=local` 时，用固定课堂 fixture 测 summary/todos/quiz。
- 任一技能回退或产生 warning 时，脚本返回失败，便于手动联调定位。

### 已完成：URL 深链接

当前已支持：

- 打开历史课堂时写入 `?session_id=...`。
- 从搜索命中打开时写入 `source_type`、`source_id` 和可选 `ts`。
- 页面首次加载会读取 URL，自动打开历史课堂并定位来源。
- 字幕、图片/OCR、时间线、知识图谱节点/边都可以接收 focused source。

示例：

```text
/?session_id=lec_xxx&source_type=segment&source_id=seg_001
```

### 已完成：本地模型模式入口

当前已支持：

- `LLM_PROVIDER=local`
- `LLM_BASE_URL=http://127.0.0.1:11434/v1`
- `LLM_MODEL=llama3.1`
- 本地 provider 允许 `LLM_API_KEY` 为空。
- HTTP 请求无 key 时不会发送空 Authorization header。

示例：

```text
LLM_PROVIDER=local
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=...
```

仍可增强：

1. 补充 Ollama/vLLM 具体启动示例。
2. 增加本地 embedding provider 文档。
3. 为本地模型输出稳定性建立手动评测样例。

## 下一步顺序

建议按验证收益优先：

1. 补充真实 LlamaIndex/embedding provider 安装文档。
2. 增加全局索引 rebuild 命令。
3. 增加 URL 深链接的前端测试覆盖。
4. 增加 Ollama/vLLM 本地模型 smoke 文档。
5. 录制中批量增量索引继续暂缓。

默认测试仍应保持不依赖网络、不依赖真实 API key、不依赖重量级本地模型。
