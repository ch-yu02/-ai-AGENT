# EDU-Mate API Schema

本文档描述当前后端 MVP 的接口契约，供前端、算法模块、硬件采集模块和
mock sender 联调使用。

当前后端职责：

1. 创建课堂 session。
2. 接收外部实时输入：字幕、图片/OCR/VLM。
3. 在 EDU-Mate 内部生成知识抽取结果。
4. 更新课堂上下文和知识图谱。
5. 通过 WebSocket 推送增量更新。
6. 结束课堂并保存本地文件。

## 1. 基础约定

默认后端地址：

```text
http://127.0.0.1:8000
```

默认 WebSocket 地址：

```text
ws://127.0.0.1:8000/ws/{session_id}
```

HTTP 请求统一使用 JSON：

```http
Content-Type: application/json
```

时间字段分两类：

- `start_time` / `end_time` / `created_at` / `upload_time`：ISO-8601 字符串。
- `start_ts` / `end_ts` / `capture_ts` / `timestamp_range`：课堂内相对时间，单位秒。

课堂 session 存在于内存中。后端重启后，历史文件仍在磁盘，但旧 session
不会自动恢复为可写状态。

## 2. 系统接口

### GET /

检查服务基本信息。

响应示例：

```json
{
  "name": "Lecture-Link Agent Backend",
  "version": "0.1.0",
  "status": "ok"
}
```

### GET /health

健康检查。

响应示例：

```json
{
  "status": "ok"
}
```

## 3. 会话接口

### POST /sessions/start

创建一节课堂。后端会自动生成 `session_id`，并初始化课堂上下文和知识图谱。

请求体：

```json
{
  "title": "通信原理第8讲：傅里叶变换",
  "course": "通信原理",
  "teacher": "张老师",
  "language": "zh-CN",
  "created_by": "student",
  "device_id": "dk2500_001"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 否 | 课堂标题，默认 `"未命名课堂"` |
| `course` | string/null | 否 | 课程名称 |
| `teacher` | string/null | 否 | 教师姓名 |
| `language` | string | 否 | 语言代码，默认 `"zh-CN"` |
| `created_by` | string | 否 | 创建者，默认 `"student"` |
| `device_id` | string/null | 否 | 设备 ID |

响应状态码：`201 Created`

响应体 `LectureSession`：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "title": "通信原理第8讲：傅里叶变换",
  "course": "通信原理",
  "teacher": "张老师",
  "start_time": "2026-06-05T01:02:03.000000+00:00",
  "end_time": null,
  "status": "recording",
  "language": "zh-CN",
  "created_by": "student",
  "device_id": "dk2500_001"
}
```

### PATCH /sessions/{session_id}

更新课堂标题和课程名称。用于前端手动改名，也用于 WhisperLive/Qwen 最终笔记
生成后由云端 notes-agent 把推断出的课堂名称同步到后端。本地 Qwen 只负责
结构化笔记，不负责最终课堂命名。

请求体：

```json
{
  "title": "傅里叶变换专题",
  "course": "信号与系统"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 否 | 新课堂标题；传空字符串会返回 400 |
| `course` | string/null | 否 | 新课程名称；传 `null` 或空字符串表示清空课程名称 |

响应体：更新后的 `LectureSession`。录制中的课堂会广播 `session.updated`。

### GET /sessions/{session_id}

读取课堂元信息。优先读取内存中的课堂；如果后端重启导致内存丢失，会回退
读取本地历史文件中的 `metadata.json`。

响应状态码：`200 OK`

响应体：`LectureSession`

错误：

| 状态码 | 场景 |
| --- | --- |
| `404` | session 不存在，且本地历史文件中也没有对应元信息 |

### GET /sessions

读取已保存的历史课堂列表。仅返回已经结束并写入 `data/sessions/{session_id}`
的课堂；正在录制但尚未保存的课堂不会出现在列表中。

响应状态码：`200 OK`

响应体：

```json
{
  "sessions": [
    {
      "session": {
        "session_id": "lec_20260605_010203_ab12cd34",
        "title": "通信原理第8讲：傅里叶变换",
        "course": "通信原理",
        "teacher": "张老师",
        "start_time": "2026-06-05T01:02:03.000000+00:00",
        "end_time": "2026-06-05T02:30:00.000000+00:00",
        "status": "ended",
        "language": "zh-CN",
        "created_by": "student",
        "device_id": "dk2500_001"
      },
      "event_count": 12,
      "storage_path": "data/sessions/lec_20260605_010203_ab12cd34"
    }
  ]
}
```

### GET /sessions/recording

读取当前后端内存中仍处于 `recording` 状态的课堂，按开始时间倒序返回。

用途：

- 本地音频/WhisperLive 联调脚本自动接入前端已经开始的课堂。
- 前端接入脚本自动创建或正在录制的测试课堂。
- 避免每次测试都手动复制 `session_id`。

响应状态码：`200 OK`

响应体：

```json
[
  {
    "session_id": "lec_20260618_034336_c171e7e5",
    "title": "本地音频测试课堂",
    "course": null,
    "teacher": null,
    "start_time": "2026-06-18T03:43:36.000000+00:00",
    "end_time": null,
    "status": "recording",
    "language": "zh-CN",
    "created_by": "student",
    "device_id": null
  }
]
```

### GET /sessions/{session_id}/history

读取一节已保存课堂的完整历史内容，用于历史回放、课后技能和总结页面。

响应状态码：`200 OK`

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `session` | `LectureSession` | 课堂元信息 |
| `transcript_markdown` | string | `transcript.md` 的完整内容 |
| `structured_notes_markdown` | string/null | `structured_notes.md` 的完整内容；旧课堂可能为空 |
| `timeline` | `TimelineItem[]` | `timeline.json` 的时间线条目 |
| `knowledge_graph` | `KnowledgeTree` | `knowledge_graph.json` 的图谱快照 |
| `storage_path` | string | 本地历史课堂目录 |
| `post_class_artifacts` | object | `summary.md`、`todos.json`、`quiz.json`、Agent artifact 和消息记录 |

错误：

| 状态码 | 场景 |
| --- | --- |
| `404` | 本地历史课堂不存在或缺少必要文件 |

### DELETE /sessions/{session_id}/history

删除一节已保存课堂的本地历史目录。只影响磁盘历史数据，不会把已经结束的
内存课堂恢复或重开。

响应：

```json
{
  "status": "deleted",
  "session_id": "lec_20260618_034336_c171e7e5"
}
```

### POST /sessions/{session_id}/end

结束课堂。该接口是幂等的，重复结束同一节课不会产生重复事件语义。

处理流程：

1. 读取课堂上下文。
2. 读取知识图谱。
3. 结束前运行一次内部 LLM 知识抽取；失败只进入 warning/error，不阻塞保存。
4. 将 session 状态改为 `ended`。
5. 保存本地文件，包括 `structured_notes.md`（如果录制中收到过结构化笔记）。
6. 生成并保存课后产物 `summary.md`、`todos.json`。
7. 如果启用 LlamaIndex，构建单节课 RAG 索引。
8. 通过 WebSocket 广播 `session.ended`，其中包含保存路径、课后产物路径、
   RAG 索引状态和知识抽取结果摘要。

响应状态码：`200 OK`

响应体：结束后的 `LectureSession`

错误：

| 状态码 | 场景 |
| --- | --- |
| `404` | session、context 或 knowledge graph 不存在 |

## 4. Agent 接口

### POST /agent/chat

对当前录制中课堂或已保存历史课堂进行问答、总结、待办提取和自测题生成。

请求：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "prompt": "采样定理为什么重要？",
  "mode": "auto",
  "answer_mode": "grounded"
}
```

字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `session_id` | string | 是 | 课堂 ID，可以是录制中课堂或历史课堂 |
| `prompt` | string | 是 | 用户自然语言输入 |
| `mode` | string | 否 | `auto` / `qa` / `summary` / `todos` / `quiz`，默认 `auto` |
| `answer_mode` | string | 否 | 只对 QA 生效。`strict` 只依据课堂资料；`grounded` 允许模型补充通用解释 |

响应：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "intent": "qa",
  "answer": "根据课堂内容：...\n补充解释：...",
  "artifacts": [],
  "source_refs": [
    {
      "type": "segment",
      "id": "seg_001",
      "ts": 1.0,
      "text": "采样定理说明..."
    }
  ],
  "warnings": [
    "回答包含模型通用知识补充；课堂依据见来源引用。"
  ]
}
```

说明：

- `strict` 是默认答疑模式，适合复习、笔记和考试场景。
- `strict` 有课堂来源且配置 LLM 时，会让模型把来源整理成自然回答；提示词
  禁止使用来源外信息。未配置或失败时回退为检索摘要。
- `grounded` 仍要求先找到课堂来源；没有课堂依据时不会退化成开放域问答。
- `summary` / `todos` / `quiz` 会忽略 `answer_mode`，继续由各自技能控制是否使用 LLM。

### POST /agent/search

跨课堂搜索已保存历史课堂。

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
- `hits`：命中来源，包含 `session_id`、课堂标题、课程、分数和 `source_ref`。
- `warnings`：坏历史目录跳过、LlamaIndex 回退等非致命提示。

全局索引可手动重建：

```bash
scripts/dev.sh rebuild-global-index
scripts/dev.sh rebuild-global-index --llamaindex
```

不带 `--llamaindex` 时只重建可审计的 `documents.json` 快照；带参数时会同时
尝试重建 `data/indexes/global/llama_index/`。

### POST /agent/review

基于跨课堂检索来源做课后复习问答。请求体与 `/agent/search` 相同，返回
同样的 `GlobalSearchResponse`。区别是：如果已配置 LLM，后端会把命中的
历史课堂来源整理成自然复习回答；未配置或失败时回退为搜索摘要，并在
`warnings` 中说明。

```json
{
  "query": "复习采样定理",
  "course": "通信原理",
  "limit": 8
}
```

### GET /agent/courses

按课程聚合已保存历史课堂，供课后复习入口使用。

响应：

```json
{
  "courses": [
    {
      "course": "通信原理",
      "session_count": 3,
      "latest_session_id": "lec_20260618_034336_c171e7e5",
      "latest_title": "通信原理第8讲",
      "latest_start_time": "2026-06-18T03:43:36+08:00",
      "node_count": 18,
      "edge_count": 12
    }
  ],
  "warnings": []
}
```

### GET /agent/courses/{course}/knowledge-tree

合并同一课程下多节历史课堂的知识图谱，按节点 label 和边关系去重。该接口
返回的是课后复习用的合并快照，不会修改原始课堂历史文件。

响应核心字段：

- `course`：课程名。
- `session_count`：参与合并的历史课堂数量。
- `knowledge_graph`：合并后的 `KnowledgeTree`。
- `warnings`：损坏历史目录等非致命提示。

### POST /agent/knowledge-tree/update-from-notes

用结构化 Markdown 课堂笔记更新录制中课堂的知识图谱。

这是 WhisperLive/Qwen 本地笔记链路对接云端知识树 Agent 的入口：

```text
WhisperLive 字幕草稿 -> 本地 Qwen structured_notes.md
-> POST /agent/knowledge-tree/update-from-notes
-> 云端 LLM 生成 KnowledgeExtraction
-> 复用 knowledge.extraction 事件管线更新图谱和前端
-> final 快照可同时返回 session_title/course 并广播 session.updated
```

请求：

```json
{
  "session_id": "lec_20260618_034336_c171e7e5",
  "snapshot_id": "notes_000003_streaming",
  "sequence": 3,
  "markdown": "# 课堂笔记\n\n## 课堂要点\n- 傅里叶变换用于频域分析。",
  "markdown_hash": "optional_hash",
  "source_segments": [
    {
      "segment_id": "seg_001",
      "start_ts": 1.0,
      "end_ts": 4.2,
      "text": "傅里叶变换可以把时域信号转换到频域。"
    }
  ],
  "recent_source_segments": [
    {
      "segment_id": "seg_001",
      "start_ts": 1.0,
      "end_ts": 4.2,
      "text": "傅里叶变换可以把时域信号转换到频域。"
    }
  ],
  "update_status": "streaming"
}
```

字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `session_id` | string | 是 | 必须是录制中课堂 |
| `snapshot_id` | string | 是 | 本次笔记快照 ID |
| `sequence` | number | 否 | 快照序号，用于日志和排查乱序 |
| `markdown` | string | 是 | 当前完整结构化课堂笔记 |
| `markdown_hash` | string/null | 否 | 去重 hash；为空时后端按 Markdown 文本计算 |
| `source_segments` | object[] | 否 | 生成笔记时用到的全量字幕来源 |
| `recent_source_segments` | object[] | 否 | 本次增量优先依据的近期字幕；为空时回退到 `source_segments` |
| `update_status` | string | 否 | `streaming` / `final` |

说明：

- `streaming` 快照主要用于增量图谱更新。
- `final` 快照可同时让云端 notes-agent 根据课堂内容生成短标题和课程名。
- 本地 Qwen 不再润色或替换前端实时字幕；前端字幕显示 WhisperLive/ASR 原始
  `transcript.segment`。

响应：

```json
{
  "status": "applied",
  "session_id": "lec_20260618_034336_c171e7e5",
  "snapshot_id": "notes_000003_streaming",
  "markdown_hash": "computed_or_supplied_hash",
  "extraction_id": "ext_notes_lec_xxx_notes_000003_streaming_abcd1234",
  "graph_patch_operations": 4,
  "warnings": []
}
```

`status` 含义：

| status | 说明 |
| --- | --- |
| `applied` | 生成了有效抽取，并产生图谱增量 |
| `skipped` | 内容重复、没有新增知识或没有图谱操作 |
| `failed` | 云端 LLM 调用或 schema 校验失败 |

成功产生图谱增量时，后端还会广播标准 `event.received` WebSocket 消息，
`event_type` 为 `knowledge.extraction`，前端继续按现有 `graph_patch`
逻辑更新图谱。

## 5. 实时事件接口

### POST /events

接收一条课堂实时事件。外部模块主要发送 ASR 和 OCR/VLM 输入；知识抽取由
EDU-Mate 项目内部完成，`knowledge.extraction` 主要作为内部事件、mock
数据和调试格式使用。

统一请求信封 `RealtimeEvent`：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "event_type": "transcript.segment",
  "payload": {}
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `session_id` | string | 是 | 所属课堂 ID |
| `event_type` | string | 是 | 当前支持三种事件类型 |
| `payload` | object | 否 | 具体事件内容 |

支持的 `event_type`：

```text
transcript.segment
image.capture
knowledge.extraction
```

对外部联调方来说，必须发送的是 `transcript.segment` 和 `image.capture`。
`knowledge.extraction` 不要求外部算法组发送。

响应状态码：`202 Accepted`

响应体：

```json
{
  "status": "accepted",
  "session_id": "lec_20260605_010203_ab12cd34",
  "event_type": "transcript.segment",
  "event_count": 1
}
```

错误：

| 状态码 | 场景 |
| --- | --- |
| `400` | payload 无法解析，或 event_type 不支持 |
| `404` | session、context 或 knowledge graph 不存在 |
| `409` | session 已结束，不再接收实时事件 |

## 6. 事件 Payload

### 6.1 transcript.segment

ASR 模块发送的实时字幕片段。

示例：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "event_type": "transcript.segment",
  "payload": {
    "segment_id": "seg_001",
    "session_id": "lec_20260605_010203_ab12cd34",
    "start_ts": 1.0,
    "end_ts": 4.2,
    "text": "傅里叶变换可以把时域信号转换到频域进行分析。",
    "speaker": "teacher",
    "confidence": 0.95,
    "is_final": true,
    "source": "whisper"
  }
}
```

payload 字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `segment_id` | string | 否 | 字幕片段 ID，缺省时后端补齐 |
| `session_id` | string | 否 | 所属课堂 ID，缺省时后端用外层 session_id |
| `start_ts` | number | 否 | 开始时间，单位秒 |
| `end_ts` | number | 否 | 结束时间，单位秒 |
| `text` | string | 否 | 字幕文本 |
| `speaker` | string/null | 否 | 说话人，默认 `"teacher"` |
| `confidence` | number/null | 否 | ASR 置信度，0 到 1 |
| `is_final` | boolean | 否 | 是否最终结果，默认 `true` |
| `source` | string/null | 否 | 来源模块，例如 `"whisper"` |
| `created_at` | string | 否 | 创建时间，缺省时后端补齐 |

### 6.2 image.capture

摄像头、屏幕截图、OCR 或 VLM 模块发送的视觉事件。

示例：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "event_type": "image.capture",
  "payload": {
    "image_id": "img_001",
    "session_id": "lec_20260605_010203_ab12cd34",
    "capture_ts": 10.5,
    "image_path": "local://sessions/lec_xxx/images/img_001.jpg",
    "source": "camera",
    "image_type": "slide",
    "status": "processed",
    "ocr_text": "X(f)=∫x(t)e^{-j2πft}dt",
    "caption": "课件展示傅里叶变换公式。"
  }
}
```

payload 字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `image_id` | string | 否 | 图片 ID，缺省时后端补齐 |
| `session_id` | string | 否 | 所属课堂 ID |
| `capture_ts` | number | 否 | 捕获时间，单位秒 |
| `upload_time` | string | 否 | 上传时间，缺省时后端补齐 |
| `image_path` | string | 否 | 图片路径，缺省时后端生成 local 路径 |
| `source` | string/null | 否 | 来源，例如 `camera`、`screen_share` |
| `image_type` | string/null | 否 | 图片类型，例如 `slide`、`whiteboard` |
| `status` | string | 否 | 处理状态，默认 `processed` |
| `ocr_text` | string/null | 否 | OCR 文本 |
| `caption` | string/null | 否 | VLM 图片描述 |

### 6.2.1 图片上传与读取

如果前端需要显示真实图片，硬件/相机模块可以先上传原始图片 bytes：

```text
PUT /sessions/{session_id}/images/{image_id}
Content-Type: image/jpeg | image/png | image/webp
```

请求体是图片二进制内容，不使用 multipart。响应：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "image_id": "img_001",
  "image_path": "local://sessions/lec_20260605_010203_ab12cd34/images/img_001.jpg"
}
```

随后 `image.capture.payload.image_path` 应使用这个 `image_path`。前端或调试工具
可以读取：

```text
GET /sessions/{session_id}/images/{image_id}
```

后端只服务 `data/sessions/{session_id}/images/` 下的文件，不会直接暴露任意
本机绝对路径。

当前图像处理链路：

1. 相机/硬件/OCR/VLM 模块可先上传原始图片 bytes，得到受控的 `local://`
   `image_path`。
2. 模块发送 `image.capture`，携带 `image_path`、`capture_ts`、`ocr_text` 和/或
   `caption`。
3. 后端把视觉事件写入 `ClassroomContext.visuals` 和 timeline，并通过
   WebSocket 推给前端视觉/OCR 区。
4. 内部实时抽取或课后抽取可读取最近的 OCR/caption，与字幕一起生成
   `knowledge.extraction`；生成的节点/边会通过 `source_visual_ids` 关联图片。
5. Agent/RAG 检索会把视觉来源作为短 source ref 返回；前端展示 OCR/caption
   摘录，不会直接展开任意本机路径。

当前项目还不负责相机采集、OCR 或 VLM 推理本身；这些能力作为外部模块通过
`PUT /sessions/{session_id}/images/{image_id}` 和 `image.capture` 接入。

### 6.3 knowledge.extraction

EDU-Mate 内部知识抽取模块生成的一次实体/关系抽取结果。外部模块正常联调
时不需要发送该事件；它保留为内部管线、mock sender 和后端调试使用。

示例：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "event_type": "knowledge.extraction",
  "payload": {
    "extraction_id": "ext_001",
    "session_id": "lec_20260605_010203_ab12cd34",
    "source_segment_ids": ["seg_001"],
    "source_visual_ids": ["img_001"],
    "timestamp_range": [1.0, 10.5],
    "entities": [
      {
        "entity_id": "node_fourier_transform",
        "name": "傅里叶变换",
        "type": "concept",
        "description": "将信号从时域表示转换为频域表示的数学工具"
      },
      {
        "entity_id": "node_frequency_domain",
        "name": "频域",
        "type": "concept",
        "description": "从频率成分角度描述信号的表示方式"
      }
    ],
    "relations": [
      {
        "source": "傅里叶变换",
        "target": "频域",
        "relation": "maps_to"
      }
    ],
    "importance": 0.92
  }
}
```

payload 字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `extraction_id` | string | 否 | 抽取 ID，缺省时上下文层会补齐 |
| `session_id` | string | 否 | 所属课堂 ID，图谱层需要它 |
| `source_segment_ids` | string[] | 否 | 来源字幕片段 ID |
| `source_visual_ids` | string[] | 否 | 来源图片 ID |
| `timestamp_range` | [number, number]/null | 否 | 来源时间范围，单位秒 |
| `entities` | object[] | 否 | 实体列表 |
| `relations` | object[] | 否 | 关系列表 |
| `importance` | number/null | 否 | 重要度，0 到 1 |

`entities` 字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `entity_id` | string/null | 否 | 实体 ID |
| `name` | string | 是 | 实体名称，用于图谱去重 |
| `type` | string | 否 | 类型，默认 `concept` |
| `description` | string/null | 否 | 实体说明 |

`relations` 字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `source` | string | 是 | 起点实体名称 |
| `target` | string | 是 | 终点实体名称 |
| `relation` | string | 是 | 关系类型 |

注意：知识图谱节点按实体 `name` 规范化后去重。若 relation 引用了
entities 中没有出现的实体，后端会自动创建占位节点。

## 7. WebSocket

### WS /ws/{session_id}

前端订阅某节课堂的实时更新。

连接要求：

- `session_id` 必须存在于当前后端内存中。
- 如果 session 不存在，后端会用 WebSocket code `1008` 关闭连接。
- 当前 WebSocket 只用于后端推送，客户端发来的消息会被忽略。

连接成功后，后端立即推送：

```json
{
  "type": "ws.connected",
  "session_id": "lec_20260605_010203_ab12cd34",
  "data": {
    "message": "connected"
  },
  "created_at": "2026-06-05T01:02:03.000000+00:00"
}
```

所有 WebSocket 消息都使用统一信封：

```json
{
  "type": "event.received",
  "session_id": "lec_20260605_010203_ab12cd34",
  "data": {},
  "created_at": "2026-06-05T01:02:03.000000+00:00"
}
```

### session.started

调用 `POST /sessions/start` 后广播。

```json
{
  "type": "session.started",
  "session_id": "lec_20260605_010203_ab12cd34",
  "data": {
    "session": {
      "session_id": "lec_20260605_010203_ab12cd34",
      "title": "通信原理第8讲：傅里叶变换",
      "status": "recording"
    }
  },
  "created_at": "2026-06-05T01:02:03.000000+00:00"
}
```

通常创建课堂时还没有前端订阅者，因此前端不应依赖一定能收到这条消息。

### event.received

调用 `POST /events` 成功后广播。

```json
{
  "type": "event.received",
  "session_id": "lec_20260605_010203_ab12cd34",
  "data": {
    "event_type": "knowledge.extraction",
    "payload": {},
    "event_count": 3,
    "context_update": {
      "session_id": "lec_20260605_010203_ab12cd34",
      "event_type": "knowledge.extraction",
      "timeline_item": {
        "item_id": "ext_001",
        "session_id": "lec_20260605_010203_ab12cd34",
        "type": "knowledge",
        "ts": 1.0,
        "title": "知识点：傅里叶变换、频域",
        "data": {}
      },
      "transcript_count": 2,
      "visual_count": 1,
      "knowledge_extraction_count": 1
    },
    "graph_patch": {
      "session_id": "lec_20260605_010203_ab12cd34",
      "from_version": 0,
      "to_version": 1,
      "operations": [
        {
          "op": "add_node",
          "node": {
            "node_id": "node_fourier_transform",
            "label": "傅里叶变换",
            "type": "concept",
            "summary": "将信号从时域表示转换为频域表示的数学工具",
            "level": 0,
            "importance": 0.92,
            "source_refs": [
              {
                "type": "segment",
                "id": "seg_001",
                "ts": 1.0
              }
            ]
          },
          "edge": null,
          "data": {}
        }
      ]
    }
  },
  "created_at": "2026-06-05T01:02:03.000000+00:00"
}
```

说明：

- `context_update.timeline_item` 可写入前端本地状态；当前主界面不再单独显示事件面板，
  但 timeline 仍用于历史保存和后续定位。
- `graph_patch` 只有 `knowledge.extraction` 事件会产生；字幕和图片事件通常为 `null`。
- 前端应按 `graph_patch.operations` 顺序应用图谱变更。
- 字幕或图片事件如果触发内部批量抽取，`data.knowledge_extraction` 会包含
  本次抽取摘要；真正的图谱变更仍会随后以独立的 `knowledge.extraction`
  `event.received` 消息广播。

`data.knowledge_extraction` 示例：

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "provider": "llm",
  "extraction_count": 1,
  "processed_source_ids": ["seg_001", "seg_002", "seg_003"],
  "errors": [],
  "applied": [
    {
      "extraction_id": "ext_lec_xxx_seg_001_seg_002_seg_003",
      "graph_patch_operations": 3
    }
  ]
}
```

知识抽取使用 LLM-backed extractor，复用后端 LLM 环境变量：

```text
LLM_PROVIDER
LLM_API_KEY
LLM_MODEL
LLM_BASE_URL
LLM_TIMEOUT_SECONDS
LLM_MAX_RETRIES
```

如果 LLM 未配置、调用失败或返回内容无法校验为 `KnowledgeExtraction`，
后端会在 `knowledge_extraction.errors` 中返回错误信息，不会自动回退规则版，
也不会把无效抽取写入图谱。

### session.ended

调用 `POST /sessions/{session_id}/end` 后广播。

```json
{
  "type": "session.ended",
  "session_id": "lec_20260605_010203_ab12cd34",
  "data": {
    "session": {
      "session_id": "lec_20260605_010203_ab12cd34",
      "status": "ended"
    },
    "storage": {
      "session_dir": "data/sessions/lec_20260605_010203_ab12cd34",
      "files": {
        "metadata": "data/sessions/lec_20260605_010203_ab12cd34/metadata.json",
        "transcript": "data/sessions/lec_20260605_010203_ab12cd34/transcript.md",
        "structured_notes": "data/sessions/lec_20260605_010203_ab12cd34/structured_notes.md",
        "timeline": "data/sessions/lec_20260605_010203_ab12cd34/timeline.json",
        "knowledge_graph": "data/sessions/lec_20260605_010203_ab12cd34/knowledge_graph.json"
      },
      "post_class_files": {
        "summary": "data/sessions/lec_20260605_010203_ab12cd34/summary.md",
        "todos": "data/sessions/lec_20260605_010203_ab12cd34/todos.json"
      },
      "rag_index": {
        "enabled": false,
        "status": "skipped"
      },
      "knowledge_extraction": {
        "session_id": "lec_20260605_010203_ab12cd34",
        "provider": "llm",
        "extraction_count": 1,
        "processed_source_ids": ["seg_001", "seg_002"],
        "errors": []
      }
    }
  },
  "created_at": "2026-06-05T01:02:03.000000+00:00"
}
```

## 8. 知识图谱数据

完整知识图谱 `KnowledgeTree` 会在结束课堂时保存为
`knowledge_graph.json`。

```json
{
  "session_id": "lec_20260605_010203_ab12cd34",
  "version": 1,
  "root_nodes": ["node_fourier_transform"],
  "nodes": [
    {
      "node_id": "node_fourier_transform",
      "label": "傅里叶变换",
      "type": "concept",
      "summary": "将信号从时域表示转换为频域表示的数学工具",
      "level": 0,
      "importance": 0.92,
      "source_refs": [
        {
          "type": "segment",
          "id": "seg_001",
          "ts": 1.0
        }
      ]
    }
  ],
  "edges": [
    {
      "edge_id": "edge_node_fourier_transform_maps_to_node_frequency_domain",
      "source": "node_fourier_transform",
      "target": "node_frequency_domain",
      "relation": "maps_to",
      "source_refs": [
        {
          "type": "segment",
          "id": "seg_001",
          "ts": 1.0
        }
      ]
    }
  ],
  "updated_at": "2026-06-05T01:02:03.000000+00:00"
}
```

前端实时展示时优先消费 WebSocket 的 `graph_patch`；课后/历史展示时读取
完整 `knowledge_graph.json`。

## 9. 本地保存文件

结束课堂后，后端写入：

```text
data/sessions/{session_id}/metadata.json
data/sessions/{session_id}/transcript.md
data/sessions/{session_id}/structured_notes.md
data/sessions/{session_id}/timeline.json
data/sessions/{session_id}/knowledge_graph.json
data/sessions/{session_id}/summary.md
data/sessions/{session_id}/todos.json
data/sessions/{session_id}/quiz.json
data/sessions/{session_id}/agent_messages.json
data/sessions/{session_id}/agent_artifacts.json
```

文件说明：

| 文件 | 内容 |
| --- | --- |
| `metadata.json` | `LectureSession` |
| `transcript.md` | 人可读 Markdown 字幕 |
| `structured_notes.md` | WhisperLive/Qwen 链路实时维护的结构化课堂笔记，可能不存在 |
| `timeline.json` | `TimelineItem[]` |
| `knowledge_graph.json` | `KnowledgeTree` |
| `summary.md` | 课后总结，结束课堂时自动生成 |
| `todos.json` | 课后待办候选，结束课堂时自动生成 |
| `quiz.json` | 用户主动通过 Agent 生成自测题后保存 |
| `agent_messages.json` | 历史 Agent 对话 |
| `agent_artifacts.json` | Agent 生成的结构化产物快照 |

## 10. Mock Sender

mock sender 用于在真实 ASR/OCR/VLM 和内部知识抽取模块未完全接入时，
自动向后端喂一组中文课堂模拟数据。它不会创建课堂；课堂开始必须先从
前端页面手动发起。

先启动后端：

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

先在前端点击开始课堂，复制页面上的 `session_id`，然后运行：

```bash
.venv/bin/python backend/scripts/mock_sender.py --session-id REPLACE_WITH_SESSION_ID --no-end
```

快速发送：

```bash
.venv/bin/python backend/scripts/mock_sender.py --session-id REPLACE_WITH_SESSION_ID --delay 0 --no-end
```

发送完并触发结束课堂：

```bash
.venv/bin/python backend/scripts/mock_sender.py --session-id REPLACE_WITH_SESSION_ID
```

指定后端地址：

```bash
.venv/bin/python backend/scripts/mock_sender.py --base-url http://127.0.0.1:8000 --session-id REPLACE_WITH_SESSION_ID --no-end
```

mock sender 当前会模拟：

1. 使用已有课堂 session。
2. 发送多条 `transcript.segment`。
3. 发送 `image.capture`，包含 OCR 文本和 VLM 描述。
4. 发送多条模拟的内部 `knowledge.extraction`，驱动知识图谱增量更新。
5. 默认结束课堂并保存本地文件；加 `--no-end` 时保留 recording 状态。

## 11. 本地音频与 WhisperLive 联调脚本

### audio-stream

`audio-stream` 是 OpenVINO Whisper/Qwen 本地测试链路，适合不启动
WhisperLive 服务时快速验证：

```bash
scripts/dev.sh audio-stream --max-audio-seconds 120 --whisper-device GPU --qwen-device CPU
```

默认会尝试自动接入 `GET /sessions/recording` 返回的最新录制课堂；如果没有
可用课堂，会自动调用 `POST /sessions/start` 创建测试课堂。也可以显式指定：

```bash
scripts/dev.sh audio-stream --session-id lec_xxx --max-audio-seconds 120
```

### whisperlive-md

`whisperlive-md` 是当前主要的本地课堂笔记联调链路：

```bash
scripts/dev.sh whisperlive-server --port 9090
scripts/dev.sh whisperlive-md --max-audio-seconds 300 --update-every-seconds 30
```

启用云端知识图谱更新：

```bash
scripts/dev.sh whisperlive-md \
  --enable-cloud-graph \
  --max-audio-seconds 300 \
  --update-every-seconds 30 \
  --graph-update-every-seconds 60
```

行为：

1. WhisperLive 生成字幕草稿。
2. 本地 Qwen 定期根据字幕草稿维护结构化 Markdown 课堂笔记。
3. 如果绑定了 session，Markdown 保存到
   `data/sessions/{session_id}/structured_notes.md`。
4. 启用 `--enable-cloud-graph` 后，脚本定期调用
   `POST /agent/knowledge-tree/update-from-notes`。
5. 后端 notes-agent 生成 `knowledge.extraction`，前端通过标准 `graph_patch`
   更新知识图谱。
6. final 快照如果返回 `session_title` / `course`，后端会更新课堂元信息并
   广播 `session.updated`。

## 12. 前端接入建议

实时课堂页面建议流程：

1. 调用 `POST /sessions/start` 创建课堂。
2. 用返回的 `session_id` 连接 `WS /ws/{session_id}`。
3. 收到 `ws.connected` 后展示连接成功状态。
4. 收到 `event.received` 后：
   - 把 `context_update.timeline_item` 写入本地状态；当前主界面不再单独显示事件面板，
     但 timeline 仍用于历史保存和后续定位。
   - 如果 `event_type` 是 `transcript.segment`，更新字幕区。
   - 如果 `event_type` 是 `image.capture`，更新图片/OCR 区。
   - 如果 `graph_patch` 不为 `null`，应用知识图谱增量更新。
5. 调用 `POST /sessions/{session_id}/end` 结束课堂。
6. 收到 `session.ended` 后停止实时写入，展示保存路径或进入课后页面。

注意：当前 WebSocket 连接后不会补发历史快照。因此前端应在创建课堂后尽快
连接 WebSocket，再开始发送或接收实时事件。
