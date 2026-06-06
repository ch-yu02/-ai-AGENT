# EDU-Mate API Schema

本文档描述当前后端 MVP 的接口契约，供前端、算法模块、硬件采集模块和
mock sender 联调使用。

当前后端职责：

1. 创建课堂 session。
2. 接收实时事件：字幕、图片/OCR/VLM、知识抽取。
3. 更新课堂上下文和知识图谱。
4. 通过 WebSocket 推送增量更新。
5. 结束课堂并保存本地文件。

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

### GET /sessions/{session_id}/history

读取一节已保存课堂的完整历史内容，用于历史回放、课后技能和总结页面。

响应状态码：`200 OK`

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `session` | `LectureSession` | 课堂元信息 |
| `transcript_markdown` | string | `transcript.md` 的完整内容 |
| `timeline` | `TimelineItem[]` | `timeline.json` 的时间线条目 |
| `knowledge_graph` | `KnowledgeTree` | `knowledge_graph.json` 的图谱快照 |
| `storage_path` | string | 本地历史课堂目录 |

错误：

| 状态码 | 场景 |
| --- | --- |
| `404` | 本地历史课堂不存在或缺少必要文件 |

### POST /sessions/{session_id}/end

结束课堂。该接口是幂等的，重复结束同一节课不会产生重复事件语义。

处理流程：

1. 读取课堂上下文。
2. 读取知识图谱。
3. 将 session 状态改为 `ended`。
4. 保存本地文件。
5. 通过 WebSocket 广播 `session.ended`。

响应状态码：`200 OK`

响应体：结束后的 `LectureSession`

错误：

| 状态码 | 场景 |
| --- | --- |
| `404` | session、context 或 knowledge graph 不存在 |

## 4. 实时事件接口

### POST /events

接收一条课堂实时事件。所有 ASR、OCR/VLM、SLM 知识抽取结果都走这个入口。

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

## 5. 事件 Payload

### 5.1 transcript.segment

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

### 5.2 image.capture

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

### 5.3 knowledge.extraction

SLM 或知识抽取模块发送的一次实体/关系抽取结果。

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

## 6. WebSocket

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
                "type": "event",
                "id": "ext_001",
                "ts": null
              },
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

- `context_update.timeline_item` 可直接追加到前端时间线。
- `graph_patch` 只有 `knowledge.extraction` 事件会产生；字幕和图片事件通常为 `null`。
- 前端应按 `graph_patch.operations` 顺序应用图谱变更。

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
        "timeline": "data/sessions/lec_20260605_010203_ab12cd34/timeline.json",
        "knowledge_graph": "data/sessions/lec_20260605_010203_ab12cd34/knowledge_graph.json"
      }
    }
  },
  "created_at": "2026-06-05T01:02:03.000000+00:00"
}
```

## 7. 知识图谱数据

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
          "type": "event",
          "id": "ext_001",
          "ts": null
        },
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

## 8. 本地保存文件

结束课堂后，后端写入：

```text
data/sessions/{session_id}/metadata.json
data/sessions/{session_id}/transcript.md
data/sessions/{session_id}/timeline.json
data/sessions/{session_id}/knowledge_graph.json
```

文件说明：

| 文件 | 内容 |
| --- | --- |
| `metadata.json` | `LectureSession` |
| `transcript.md` | 人可读 Markdown 字幕 |
| `timeline.json` | `TimelineItem[]` |
| `knowledge_graph.json` | `KnowledgeTree` |

当前未实现历史读取 API。后续建议新增：

```text
GET /history
GET /history/{session_id}
```

## 9. Mock Sender

mock sender 用于在真实 ASR/OCR/SLM 未接入时，自动向后端喂一组中文课堂
模拟数据。

先启动后端：

```bash
.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

默认运行：

```bash
.venv/bin/python backend/scripts/mock_sender.py
```

快速发送：

```bash
.venv/bin/python backend/scripts/mock_sender.py --delay 0
```

发送完但不结束课堂：

```bash
.venv/bin/python backend/scripts/mock_sender.py --no-end
```

指定后端地址：

```bash
.venv/bin/python backend/scripts/mock_sender.py --base-url http://127.0.0.1:8000
```

mock sender 当前会模拟：

1. 创建课堂。
2. 发送多条 `transcript.segment`。
3. 发送 `image.capture`，包含 OCR 文本和 VLM 描述。
4. 发送多条 `knowledge.extraction`，驱动知识图谱增量更新。
5. 默认结束课堂并保存本地文件。

## 10. 前端接入建议

实时课堂页面建议流程：

1. 调用 `POST /sessions/start` 创建课堂。
2. 用返回的 `session_id` 连接 `WS /ws/{session_id}`。
3. 收到 `ws.connected` 后展示连接成功状态。
4. 收到 `event.received` 后：
   - 把 `context_update.timeline_item` 追加到时间线。
   - 如果 `event_type` 是 `transcript.segment`，更新字幕区。
   - 如果 `event_type` 是 `image.capture`，更新图片/OCR 区。
   - 如果 `graph_patch` 不为 `null`，应用知识图谱增量更新。
5. 调用 `POST /sessions/{session_id}/end` 结束课堂。
6. 收到 `session.ended` 后停止实时写入，展示保存路径或进入课后页面。

注意：当前 WebSocket 连接后不会补发历史快照。因此前端应在创建课堂后尽快
连接 WebSocket，再开始发送或接收实时事件。
