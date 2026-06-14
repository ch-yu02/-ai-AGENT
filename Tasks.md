# EDU-Mate Active Task List

本文件是 `AGENTS.md` 的任务清单版。项目当前状态、架构边界和开发规则以
`AGENTS.md` 为准；本文件只保留后续开发和验收用的 checklist。

## 0. 当前能力基线

已完成：

- [x] FastAPI 后端基础服务
- [x] React / Vite 前端基础界面
- [x] 课堂开始、查询、结束
- [x] 实时事件接收 `POST /events`
- [x] WebSocket 实时推送 `/ws/{session_id}`
- [x] 字幕、图片/OCR、时间线展示
- [x] 知识图谱管理和增量 patch
- [x] 本地保存 metadata/transcript/timeline/knowledge_graph
- [x] 历史课堂列表、详情、删除
- [x] mock sender 向前端创建的 session 喂数据
- [x] Agent chat：QA / summary / todos / quiz
- [x] 课后 summary/todos 自动产物
- [x] quiz 按需生成和保存
- [x] Agent 对话和 artifacts 保存
- [x] 单节课 RAG 词法检索与可选 LlamaIndex
- [x] 跨课堂搜索第一版
- [x] 可选全局 LlamaIndex 索引
- [x] 可选 cloud/local LLM provider
- [x] `scripts/dev.sh` 本地开发脚本
- [x] 输入数据契约 `docs/INPUT_DATA_CONTRACT.md`

明确边界：

- [x] 外部模块只需发送 `transcript.segment` 和 `image.capture`
- [x] `knowledge.extraction` 是 EDU-Mate 内部管线事件或 mock/debug 数据
- [x] LLM-backed 内部知识抽取已接入 session end
- [x] LLM-backed 内部知识抽取已接入录制中批量触发
- [x] 自动知识抽取已切到 LLM-only，不再使用规则版兜底

## 1. P0：内部知识抽取模块

目标：让真实图谱增长不依赖 mock sender 发送 `knowledge.extraction`。

- [x] 新建内部知识抽取模块目录，例如 `backend/app/extraction/`
- [x] 定义 `KnowledgeExtractor` 输入输出接口
- [x] 从 `ClassroomContext.transcript` 读取近期字幕
- [x] 从 `ClassroomContext.visuals` 读取 OCR/VLM 文本
- [x] 生成内部 `KnowledgeExtraction`
- [x] 保证 `source_segment_ids` 和 `source_visual_ids` 可追溯
- [x] 生成稳定 entity name、entity_id、relation
- [x] 将抽取结果交给 `ContextManager` / `KnowledgeGraphManager`
- [x] 确定触发策略：session end 批量触发，录制中每 3 条 final 字幕或带文字视觉事件触发
- [x] 避免在 `POST /events` 热路径中阻塞太久
- [x] 增加 LLM-backed extractor，并停用规则版生产入口
- [x] 增加单元测试和 fixture
- [x] 增加跨课程抽取质量 fixture 基线
- [x] 增加录制中每 N 条字幕或每 N 秒的批量触发

验收：

- [x] 配置 LLM 后，只发送 ASR/OCR 输入，结束课堂后知识图谱也能增长
- [x] mock sender 不再是图谱增长的唯一方式
- [x] 抽取失败不会影响字幕/OCR 展示或课堂保存
- [x] 来源引用能对应 transcript 或 visual
- [x] 配置 LLM 后，只发送 ASR/OCR 输入，录制中前端知识图谱也能实时增长
- [x] LLM 抽取失败会输出明确错误，不自动回退规则版
- [x] LLM schema 校验失败不会写入图谱

## 2. P0：能力边界与接口联调

- [ ] 与 ASR 组确认 `transcript.segment` HTTP 输入
- [ ] 与 OCR/VLM 组确认 `image.capture` HTTP 输入
- [ ] 与硬件组确认后端局域网访问方式
- [ ] 与硬件组确认图片保存路径或上传策略
- [ ] 与前端确认 session_id 展示与复制流程
- [ ] 用 `docs/INPUT_DATA_CONTRACT.md` 完成一次端到端联调
- [ ] 确认知识抽取由 EDU-Mate 项目内部完成，不要求外部 SLM 输出

## 3. P1：RAG 与 LLM 使用说明

- [x] 补充 LLM provider 配置说明
- [ ] 补充真实 LlamaIndex 安装说明
- [ ] 补充 embedding provider 选择说明
- [x] 补充 DeepSeek/OpenAI-compatible provider 配置说明
- [x] 补充 Ollama/vLLM 本地模型示例
- [ ] 说明 `RAG_QUERY_BACKEND=llamaindex`
- [ ] 说明 `GLOBAL_SEARCH_BACKEND=llamaindex`
- [ ] 说明 provider 失败时的回退行为

验收：

- [ ] 新开发者能按文档接入一个真实 provider
- [ ] 没有 API key 时默认测试仍可通过

## 4. P1：索引维护

- [x] 增加全局索引 rebuild 命令
- [x] 在 `scripts/dev.sh` 中加入 rebuild 入口
- [ ] 增加全局索引 manifest 校验说明
- [ ] 增加坏历史目录跳过测试
- [ ] 增加索引回退 warning 测试

验收：

- [ ] 首次搜索不必承担全部构建成本
- [ ] 删除历史后索引能正确重建或失效

## 5. P1：前端 Agent 与历史体验

- [ ] 增加 URL 深链接相关前端测试
- [ ] 增加 focused source 的 store 测试
- [ ] 优化 AgentPanel 的 loading/error/success 状态
- [ ] 优化 source_refs 展示和跳转
- [x] 知识图谱节点点击显示来源文本
- [ ] 时间线点击跳转对应内容
- [ ] 图片与语音片段按时间戳对齐展示

## 6. P2：导出与部署

- [ ] 导出完整课堂 Markdown 笔记
- [ ] 导出知识图谱 Mermaid 格式
- [ ] 导出待办事项 ICS 文件
- [ ] 导出 quiz / Anki 格式
- [ ] 一键打包课程数据
- [ ] 添加 API key / provider 配置页面
- [ ] 添加日志查看页面
- [ ] 添加模型服务状态显示
- [ ] 编写 Ubuntu / DK 设备部署文档
- [ ] 编写开机自启服务配置

## 8. 已补充的输入/文件能力

- [x] 增加课堂图片 raw bytes 上传接口
- [x] 增加课堂图片静态读取接口

## 7. 常用验收命令

```bash
scripts/dev.sh compile
scripts/dev.sh test
scripts/dev.sh build
```

局域网联调：

```bash
BACKEND_HOST=0.0.0.0 FRONTEND_HOST=0.0.0.0 scripts/dev.sh dev
```

mock 数据：

```bash
scripts/dev.sh mock --session-id REPLACE_WITH_SESSION_ID --no-end
```
