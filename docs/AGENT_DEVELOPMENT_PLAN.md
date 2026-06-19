# Agent Development Plan

Agent/RAG 的详细路线图已合并到根目录 `Tasks.md`，避免维护两份互相漂移的
计划文档。

当前阅读入口：

- 项目总览和目录边界：`AGENTS.md`
- 后续开发 checklist：`Tasks.md`
- API 契约：`docs/API_SCHEMA.md`
- 外部输入契约：`docs/INPUT_DATA_CONTRACT.md`
- LLM provider 配置：`docs/LLM_PROVIDER_SETUP.md`

与 Agent/RAG 直接相关的当前事实：

- `POST /agent/chat` 支持 QA、summary、todos、quiz。
- `POST /agent/search` 支持跨历史课堂搜索。
- `POST /agent/review` 支持基于跨课堂来源的课后复习问答。
- `GET /agent/courses` 支持按课程聚合历史课堂。
- `GET /agent/courses/{course}/knowledge-tree` 支持合并多节课知识树。
- `POST /agent/knowledge-tree/update-from-notes` 支持结构化 Markdown 笔记驱动图谱更新。
- `POST /agent/knowledge-tree/update-from-notes` 的 final 快照可由云端 LLM
  返回 `session_title` / `course`，后端同步课堂元信息并广播 `session.updated`。
- QA 来源引用已限制为短摘录，避免展示完整字幕或整份结构化笔记。
- 结构化笔记进入 RAG 时会排除完整字幕快照区块，优先索引课堂要点。
- 本地 Qwen 当前只负责生成/更新结构化课堂笔记，不再替换前端实时字幕。
- 前端知识图谱图形视图已支持关系簇布局、完整多行标签、缩放、拖拽和全屏。
