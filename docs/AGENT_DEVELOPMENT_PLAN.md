# EDU-Mate Agent / RAG Development Plan

`AGENTS.md` 是项目唯一主开发指南。本文件只记录 Agent、RAG、LLM、技能和
内部知识抽取相关的后续计划，避免和全局架构文档重复。

## 1. 当前 Agent 能力

已完成：

- `POST /agent/chat`
  - `mode=auto`
  - `mode=qa`
  - `mode=summary`
  - `mode=todos`
  - `mode=quiz`
- QA 支持：
  - `answer_mode=strict`
  - `answer_mode=grounded`
- `POST /agent/search` 跨历史课堂搜索。
- 课后自动生成：
  - `summary.md`
  - `todos.json`
- 用户主动生成：
  - `quiz.json`
- 持久化：
  - `agent_messages.json`
  - `agent_artifacts.json`
- RAG：
  - 默认词法检索
  - 可选单节课 LlamaIndex
  - 可选全局 LlamaIndex
- LLM：
  - 云端 OpenAI-compatible provider
  - 本地 OpenAI-compatible provider
  - `scripts/dev.sh llm-smoke`

重要边界：

- 外部 ASR/OCR 模块不负责知识抽取。
- `knowledge.extraction` 是 EDU-Mate 内部事件。
- 真实内部知识抽取模块仍是下一阶段重点。

## 2. 当前数据流

当前真实外部输入：

```text
ASR -> transcript.segment
OCR/VLM -> image.capture
```

当前图谱输入：

```text
mock sender/debug -> knowledge.extraction
KnowledgeGraphManager -> GraphPatch
```

目标图谱输入：

```text
transcript.segment + image.capture
→ EDU-Mate internal KnowledgeExtractor
→ internal knowledge.extraction
→ KnowledgeGraphManager
→ GraphPatch
```

## 3. 下一阶段：内部知识抽取

目标：只靠 ASR/OCR 输入也能让知识图谱增长。

建议新增：

```text
backend/app/extraction/
  __init__.py
  knowledge_extractor.py
  schemas.py
```

第一版使用规则抽取，不依赖 LLM：

- 从最近 N 条 transcript 中抽取候选术语。
- 从 OCR/caption 中抽取公式和概念。
- 用简单规则生成 relation：
  - `belongs_to`
  - `mentions`
  - `defines`
  - `related_to`
- 保留 source refs。

第二版接 LLM：

- 使用 `CloudLLMClient`。
- 输出结构必须校验为 `KnowledgeExtraction`。
- 失败时回退规则抽取或返回 warning。

触发策略建议：

```text
短期：session end 时批量抽取
中期：每 N 条 transcript 批量抽取
长期：后台队列异步抽取
```

不要在 `POST /events` 中做长时间阻塞。

## 4. RAG 后续计划

已完成：

- 单节课文档转换。
- 词法查询服务。
- 可选 LlamaIndex 查询服务。
- 全局搜索与全局索引目录。

下一步：

1. 补充真实 provider 安装文档。
2. 增加全局索引 rebuild 命令。
3. 增加 embedding provider 配置说明。
4. 增加 LlamaIndex 依赖缺失时的用户可读提示。
5. 为语义搜索增加固定评测 fixture。

暂缓：

- 录制中每条事件增量索引。
- 原因：性能、去重、ASR/OCR 延迟修正策略尚未稳定。

## 5. Skill 后续计划

已完成：

- QA
- Summarizer
- TodoDetective
- QuizMaster
- LLM 支持层

下一步：

- 提高 todos 截止时间解析。
- 为 quiz 增加题型选择。
- 为 summary 增加“按知识图谱组织”的版本。
- 将 source_refs 展示得更清晰。
- 增加导出格式：
  - Markdown
  - Mermaid
  - ICS
  - Anki

## 6. LLM 后续计划

已完成：

- 环境变量配置。
- cloud/local OpenAI-compatible provider。
- provider smoke 脚本。
- 自动化测试不依赖真实 provider。

下一步：

- 写 DeepSeek 配置示例。
- 写 Ollama/vLLM 配置示例。
- 增加模型输出 schema repair 策略。
- 增加 provider latency / failure 日志。

## 7. 前端 Agent 体验

已完成：

- AgentPanel。
- GlobalSearchPanel。
- PostClassArtifactsPanel。
- 历史课堂打开和来源定位。

下一步：

- 为 URL deep link 增加测试。
- 优化 source_refs 的可读展示。
- 点击图谱节点显示来源片段。
- 时间线与 transcript/visual 双向定位。
- 给 LLM warnings 更明显但不打扰的展示。

## 8. 推荐实现顺序

1. 内部规则版 `KnowledgeExtractor`。
2. 将 extractor 接到 session end，先保证结束课堂后自动生成图谱。
3. 将 extractor 接到录制中批量触发。
4. 给 extractor 增加 LLM-backed 可选实现。
5. 全局索引 rebuild 命令。
6. Provider / embedding 安装文档。
7. 前端 deep-link 和 source focus 测试。

## 9. 验收标准

内部知识抽取验收：

- 只发送 `transcript.segment` 和 `image.capture`，不发送 mock
  `knowledge.extraction`，结束课堂后仍生成知识图谱。
- 生成的节点有稳定 label。
- 生成的边有可解释 relation。
- 每个节点/边尽量带 source refs。
- 抽取失败不影响课堂保存。

Agent/RAG 验收：

- strict QA 不编造课堂资料外的信息。
- grounded QA 明确标注包含模型补充。
- LlamaIndex 不可用时自动回退词法检索。
- 自动化测试不需要网络和 API key。
