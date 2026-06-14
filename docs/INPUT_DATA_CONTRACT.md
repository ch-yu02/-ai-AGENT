# EDU-Mate Input Data Contract

本文档规定 EDU-Mate / Lecture-Link 与其他模块联调时的**实际输入数据格式**。
适用对象：

- ASR / 语音识别开发者
- OCR / VLM / 图片理解开发者
- 硬件采集与上传开发者
- 前端联调开发者
- 后端 Agent / RAG 开发者

本文档只规定“输入到后端的数据”。HTTP 路由、WebSocket 推送和历史读取接口
详见 `docs/API_SCHEMA.md`。

## 1. 当前版本

```text
contract_version: 0.1.0
status: MVP integration contract
last_updated: 2026-06-13
```

当前外部模块只需要向后端发送两类实时输入：

```text
transcript.segment
image.capture
```

知识抽取由 EDU-Mate 项目内部完成。`knowledge.extraction` 仍是后端内部事件
和 mock/debug 数据格式，但不再作为外部团队必须发送的输入。

所有实时输入都通过同一个 HTTP 入口进入后端：

```text
POST /events
```

统一外层信封：

```json
{
  "session_id": "lec_xxx",
  "event_type": "transcript.segment",
  "payload": {}
}
```

## 2. 集成原则

### 2.1 课堂必须先由前端创建

其他模块不要自己创建课堂。课堂开始由前端手动发起：

```text
POST /sessions/start
```

前端拿到 `session_id` 后，再把它提供给 ASR、OCR/VLM 或 mock sender。

其他模块发送事件时必须带同一个 `session_id`。

### 2.2 只向 recording 状态课堂写入

后端只接受 `status = recording` 的课堂事件。

如果课堂已结束：

```text
POST /events -> 409
```

如果课堂不存在：

```text
POST /events -> 404
```

### 2.3 时间戳统一使用课堂相对时间

课堂内容时间用相对秒数，不用系统绝对时间：

```text
start_ts: 1.25
end_ts: 4.80
capture_ts: 12.50
timestamp_range: [1.25, 4.80]
```

含义：

```text
0.0 = 当前课堂开始时刻
```

绝对时间字段只用于记录创建/上传时间，例如：

```text
created_at
upload_time
```

这些字段使用 ISO-8601 字符串。

### 2.4 字段命名统一使用 snake_case

正确：

```text
session_id
start_ts
source_segment_ids
```

不要使用：

```text
sessionId
startTime
sourceSegmentIds
```

### 2.5 所有文本使用 UTF-8

中文文本必须按 UTF-8 编码发送。

HTTP header：

```http
Content-Type: application/json
```

### 2.6 ID 应稳定且可追溯

推荐 ID 格式：

```text
seg_001
img_001
node_fourier_transform
```

同一个实体、片段、图片在同一课堂内不要重复换 ID。

如果某模块无法生成 ID，后端会补齐部分 ID，但联调时建议由上游显式提供，
方便问题追踪和 source_refs 溯源。

## 3. 统一事件信封 RealtimeEvent

所有模块发送到后端的请求体必须是：

```json
{
  "session_id": "lec_20260613_010203_ab12cd34",
  "event_type": "transcript.segment",
  "payload": {}
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `session_id` | string | 是 | 课堂 ID，由前端开始课堂后获得 |
| `event_type` | string | 是 | 事件类型 |
| `payload` | object | 是 | 对应事件的数据体 |
| `created_at` | string | 否 | 事件到达或创建时间，后端可自动补齐 |

外部模块支持的 `event_type`：

| event_type | 来源模块 | 用途 |
| --- | --- | --- |
| `transcript.segment` | ASR | 实时字幕、转写文本 |
| `image.capture` | 摄像头 / OCR / VLM | 图片、OCR 文本、图像描述 |

内部事件：

| event_type | 产生方 | 用途 |
| --- | --- | --- |
| `knowledge.extraction` | EDU-Mate 内部知识抽取模块 | 实体、关系、重要度、图谱更新 |

响应成功：

```json
{
  "status": "accepted",
  "session_id": "lec_20260613_010203_ab12cd34",
  "event_type": "transcript.segment",
  "event_count": 1
}
```

## 4. ASR 输入：transcript.segment

### 4.1 用途

ASR 模块每识别出一段稳定文本，就发送一条 `transcript.segment`。

后端会把它写入：

```text
ClassroomContext.transcript
ClassroomContext.timeline
```

前端会展示到：

```text
实时字幕区
课堂时间线
```

### 4.2 最小可用 payload

```json
{
  "segment_id": "seg_001",
  "session_id": "lec_20260613_010203_ab12cd34",
  "start_ts": 1.0,
  "end_ts": 4.2,
  "text": "傅里叶变换可以把时域信号转换到频域。"
}
```

### 4.3 推荐完整 payload

```json
{
  "segment_id": "seg_001",
  "session_id": "lec_20260613_010203_ab12cd34",
  "start_ts": 1.0,
  "end_ts": 4.2,
  "text": "傅里叶变换可以把时域信号转换到频域。",
  "speaker": "teacher",
  "confidence": 0.95,
  "is_final": true,
  "source": "whisper",
  "created_at": "2026-06-13T09:30:12+08:00"
}
```

### 4.4 字段说明

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `segment_id` | string | 推荐 | 同一课堂内唯一 | 字幕片段 ID |
| `session_id` | string | 推荐 | 应与外层一致 | 课堂 ID |
| `start_ts` | number | 推荐 | `>= 0` | 片段开始秒数 |
| `end_ts` | number | 推荐 | `>= start_ts` | 片段结束秒数 |
| `text` | string | 是 | 非空字符串 | ASR 文本 |
| `speaker` | string/null | 否 | 推荐 `teacher` / `student` / `unknown` | 说话人 |
| `confidence` | number/null | 否 | `0 <= confidence <= 1` | 识别置信度 |
| `is_final` | boolean | 否 | 默认 `true` | 是否最终识别结果 |
| `source` | string/null | 否 | 如 `whisper` / `ali_asr` / `mock_asr` | 来源模块 |
| `created_at` | string | 否 | ISO-8601 | 生成时间 |

### 4.5 ASR 发送频率建议

推荐：

```text
每 2 到 8 秒发送一个 final segment
```

不推荐：

```text
每个字或每个 token 都发一次
```

如果 ASR 有中间结果，可以发送：

```json
{
  "is_final": false
}
```

但当前前端 MVP 更适合消费 final segment。中间结果的覆盖更新策略后续再扩展。

### 4.6 curl 示例

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "lec_20260613_010203_ab12cd34",
    "event_type": "transcript.segment",
    "payload": {
      "segment_id": "seg_001",
      "session_id": "lec_20260613_010203_ab12cd34",
      "start_ts": 1.0,
      "end_ts": 4.2,
      "text": "傅里叶变换可以把时域信号转换到频域。",
      "speaker": "teacher",
      "confidence": 0.95,
      "is_final": true,
      "source": "whisper"
    }
  }'
```

## 5. 图像/OCR/VLM 输入：image.capture

### 5.1 用途

视觉模块在捕获到课堂画面、课件截图、白板图像或完成 OCR/VLM 处理后，
发送一条 `image.capture`。

后端会把它写入：

```text
ClassroomContext.visuals
ClassroomContext.timeline
```

前端会展示到：

```text
图片 / OCR / VLM 面板
课堂时间线
```

### 5.2 当前图片传输约定

后端支持两种图片传输方式：

1. 推荐：先上传图片 bytes，再把返回的 `image_path` 放入 `image.capture`。
2. 调试：只发送图片路径和 OCR/VLM 处理结果。

图片上传：

```text
PUT /sessions/{session_id}/images/{image_id}
Content-Type: image/jpeg | image/png | image/webp
```

请求体是图片二进制内容。响应中的 `image_path` 可直接用于后续
`image.capture.payload.image_path`。

推荐路径格式：

```text
local://sessions/{session_id}/images/{image_id}.jpg
```

或者硬件模块本地路径：

```text
/absolute/path/to/image.jpg
```

前端或调试工具可读取：

```text
GET /sessions/{session_id}/images/{image_id}
```

后端只服务课堂目录下的图片文件，不直接暴露任意本机绝对路径。

### 5.3 最小可用 payload

```json
{
  "image_id": "img_001",
  "session_id": "lec_20260613_010203_ab12cd34",
  "capture_ts": 10.5,
  "image_path": "local://sessions/lec_20260613_010203_ab12cd34/images/img_001.jpg"
}
```

### 5.4 推荐完整 payload

```json
{
  "image_id": "img_001",
  "session_id": "lec_20260613_010203_ab12cd34",
  "capture_ts": 10.5,
  "upload_time": "2026-06-13T09:30:20+08:00",
  "image_path": "local://sessions/lec_20260613_010203_ab12cd34/images/img_001.jpg",
  "source": "camera",
  "image_type": "slide",
  "status": "processed",
  "ocr_text": "X(f)=∫x(t)e^{-j2πft}dt",
  "caption": "课件展示傅里叶变换公式，以及时域到频域的转换箭头。"
}
```

### 5.5 字段说明

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `image_id` | string | 推荐 | 同一课堂内唯一 | 图像 ID |
| `session_id` | string | 推荐 | 应与外层一致 | 课堂 ID |
| `capture_ts` | number | 推荐 | `>= 0` | 捕获时刻 |
| `upload_time` | string | 否 | ISO-8601 | 上传/处理完成时间 |
| `image_path` | string | 是 | 非空字符串 | 图片路径 |
| `source` | string/null | 否 | `camera` / `screen_share` / `phone_upload` / `mock_camera` | 来源 |
| `image_type` | string/null | 否 | `slide` / `whiteboard` / `experiment` / `note` / `unknown` | 内容类型 |
| `status` | string | 否 | `processed` / `processing` / `failed` | 处理状态 |
| `ocr_text` | string/null | 否 | 可为空 | OCR 提取文本 |
| `caption` | string/null | 否 | 可为空 | VLM 图像描述 |

### 5.6 status 约定

```text
processed  OCR/VLM 已完成，ocr_text 或 caption 可用
processing 已捕获图片，但 OCR/VLM 仍在处理
failed     图片处理失败
```

若 `status = failed`，建议仍发送：

```json
{
  "image_id": "img_001",
  "capture_ts": 10.5,
  "image_path": "...",
  "status": "failed",
  "caption": "OCR failed: image too blurry"
}
```

### 5.7 curl 示例

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "lec_20260613_010203_ab12cd34",
    "event_type": "image.capture",
    "payload": {
      "image_id": "img_001",
      "session_id": "lec_20260613_010203_ab12cd34",
      "capture_ts": 10.5,
      "image_path": "local://sessions/lec_20260613_010203_ab12cd34/images/img_001.jpg",
      "source": "camera",
      "image_type": "slide",
      "status": "processed",
      "ocr_text": "X(f)=∫x(t)e^{-j2πft}dt",
      "caption": "课件展示傅里叶变换公式。"
    }
  }'
```

## 6. 内部知识抽取输出：knowledge.extraction

### 6.1 用途

知识抽取由 EDU-Mate 项目内部完成。内部知识抽取模块从 ASR 文本和
OCR/VLM 视觉结果中提取实体与关系后，生成 `knowledge.extraction`。

外部算法组、硬件组不需要发送该事件。该格式主要用于：

- 后端内部知识抽取模块与 `ContextManager` / `KnowledgeGraphManager` 对接。
- mock sender 模拟知识图谱增长。
- 单元测试和调试。

后端会把它写入：

```text
ClassroomContext.knowledge_extractions
KnowledgeGraphManager.KnowledgeTree
ClassroomContext.timeline
```

前端会展示到：

```text
知识图谱面板
课堂时间线
```

### 6.2 最小可用 payload

```json
{
  "extraction_id": "ext_001",
  "session_id": "lec_20260613_010203_ab12cd34",
  "entities": [
    {
      "name": "傅里叶变换"
    },
    {
      "name": "频域"
    }
  ],
  "relations": [
    {
      "source": "傅里叶变换",
      "target": "频域",
      "relation": "maps_to"
    }
  ]
}
```

### 6.3 推荐完整 payload

```json
{
  "extraction_id": "ext_001",
  "session_id": "lec_20260613_010203_ab12cd34",
  "source_segment_ids": ["seg_001", "seg_002"],
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
```

### 6.4 顶层字段说明

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `extraction_id` | string | 推荐 | 同一课堂内唯一 | 抽取结果 ID |
| `session_id` | string | 推荐 | 应与外层一致 | 课堂 ID |
| `source_segment_ids` | string[] | 否 | 引用已有 `segment_id` | 来源字幕 |
| `source_visual_ids` | string[] | 否 | 引用已有 `image_id` | 来源图片 |
| `timestamp_range` | [number, number]/null | 否 | `[start, end]` | 抽取依据时间段 |
| `entities` | object[] | 是 | 可为空数组，但不推荐 | 实体列表 |
| `relations` | object[] | 否 | 默认空数组 | 关系列表 |
| `importance` | number/null | 否 | `0 <= importance <= 1` | 重要度 |

### 6.5 entities 字段

```json
{
  "entity_id": "node_fourier_transform",
  "name": "傅里叶变换",
  "type": "concept",
  "description": "将信号从时域表示转换为频域表示的数学工具"
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `entity_id` | string/null | 否 | 推荐稳定 ID | 实体 ID |
| `name` | string | 是 | 非空 | 实体名称，后端按它去重 |
| `type` | string | 否 | 默认 `concept` | 实体类型 |
| `description` | string/null | 否 | 可为空 | 实体说明 |

推荐 `type`：

```text
concept
formula
method
definition
theorem
term
person
task
```

### 6.6 relations 字段

```json
{
  "source": "傅里叶变换",
  "target": "频域",
  "relation": "maps_to"
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `source` | string | 是 | 推荐使用实体 name | 起点实体 |
| `target` | string | 是 | 推荐使用实体 name | 终点实体 |
| `relation` | string | 是 | snake_case | 关系类型 |

推荐 `relation`：

```text
maps_to
belongs_to
part_of
prerequisite_of
causes
derives_from
example_of
contrasts_with
input_domain
output_domain
represents
extracts
```

注意：

- `source` 和 `target` 当前使用实体名称，不使用 entity_id。
- 如果关系引用的实体不在 `entities` 中，后端会创建占位节点。
- 实体去重按 `name.strip().lower()` 进行。

### 6.7 内部知识抽取触发时机建议

推荐：

```text
每 1 到 3 个 transcript.segment 后触发一次内部 knowledge.extraction
```

或：

```text
每个稳定知识点块发送一次
```

不推荐：

```text
每个字、每个 token、每个过渡词都发知识抽取
```

### 6.8 调试 curl 示例

正常联调不要求外部模块调用此示例。仅在调试知识图谱管线、mock 数据或后端
内部知识抽取尚未接好时使用。

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "lec_20260613_010203_ab12cd34",
    "event_type": "knowledge.extraction",
    "payload": {
      "extraction_id": "ext_001",
      "session_id": "lec_20260613_010203_ab12cd34",
      "source_segment_ids": ["seg_001"],
      "timestamp_range": [1.0, 4.2],
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
          "type": "concept"
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
  }'
```

## 7. 多模块推荐发送顺序

一段典型课堂数据流：

```text
1. 前端开始课堂，获得 session_id
2. ASR 发送 transcript.segment(seg_001)
3. ASR 发送 transcript.segment(seg_002)
4. OCR/VLM 发送 image.capture(img_001)
5. EDU-Mate 内部知识抽取模块根据 seg_001/seg_002/img_001 生成 knowledge.extraction(ext_001)
6. KnowledgeGraphManager 根据内部 knowledge.extraction 更新知识图谱
7. 重复 2-6
8. 前端结束课堂
```

示例顺序：

```json
[
  "transcript.segment: seg_001",
  "transcript.segment: seg_002",
  "image.capture: img_001",
  "internal knowledge.extraction: ext_001"
]
```

知识抽取可以滞后于 ASR/OCR，但这是 EDU-Mate 后端内部流程。外部模块只需
保证 ASR/OCR 输入携带稳定 ID 和时间戳。

## 8. 硬件组对接约定

### 8.1 后端地址

默认本机开发：

```text
http://127.0.0.1:8000
```

局域网联调时，后端应以 `0.0.0.0` 启动：

```bash
BACKEND_HOST=0.0.0.0 FRONTEND_HOST=0.0.0.0 scripts/dev.sh dev
```

其他设备访问：

```text
http://{backend_lan_ip}:8000
```

### 8.2 图片路径

MVP 阶段只约定路径，不约定上传协议。

硬件组需要确认：

```text
图片由谁保存？
保存在哪台设备？
后端能否读取该路径？
前端是否需要直接展示原图？
```

若后端无法读取硬件本地路径，应新增图片上传接口或共享目录。

### 8.3 设备 ID

开始课堂时可以传：

```json
{
  "device_id": "dk2500_001"
}
```

实时事件 payload 中如需扩展设备来源，可先使用：

```json
{
  "source": "camera_dk2500"
}
```

后续如需更严格设备管理，再新增统一 `device_id` 字段。

## 9. 错误处理约定

### 9.1 HTTP 状态码

| 状态码 | 含义 | 处理建议 |
| --- | --- | --- |
| `202` | 事件已接受 | 上游可释放缓存 |
| `400` | payload 格式错误 | 检查字段类型、event_type |
| `404` | session/context/graph 不存在 | 确认 session_id 是否正确 |
| `409` | session 已结束 | 停止发送事件 |

### 9.2 上游重试建议

可重试：

```text
网络超时
连接失败
HTTP 5xx
```

不建议重试：

```text
400
404
409
```

如果需要重试，保持同一个外部事件 ID：

```text
segment_id / image_id 不变
```

这样后续可以支持幂等去重。

## 10. 兼容与扩展规则

### 10.1 新字段

payload 可以增加新字段，但必须满足：

```text
不破坏现有字段含义
不改变必填字段类型
新增字段使用 snake_case
```

### 10.2 新事件类型

新增事件类型前必须更新：

```text
backend/app/models/events.py
ContextManager
KnowledgeGraphManager 如需处理
docs/API_SCHEMA.md
docs/INPUT_DATA_CONTRACT.md
mock_sender 如需模拟
前端 store 如需展示
```

候选未来事件：

```text
student.question
teacher.action
slide.change
audio.marker
agent.result
```

### 10.3 强类型迁移

当前 `payload` 在 `RealtimeEvent` 中仍是通用 object。后续如接口稳定，可以改为：

```text
TranscriptEvent
ImageCaptureEvent
KnowledgeExtractionEvent
```

但在 MVP 联调阶段先保持灵活，降低算法组和硬件组接入成本。

## 11. 联调检查清单

ASR 组：

- [ ] 能拿到前端创建的 `session_id`
- [ ] 发送 `transcript.segment`
- [ ] `text` 为 UTF-8
- [ ] `start_ts` / `end_ts` 是课堂相对秒数
- [ ] 前端字幕区可看到内容

OCR/VLM 组：

- [ ] 发送 `image.capture`
- [ ] `image_path` 可追踪
- [ ] `ocr_text` 或 `caption` 至少有一个有用字段
- [ ] 前端图片/OCR 区可看到内容

EDU-Mate 知识抽取模块：

- [ ] 从 `ClassroomContext.transcript` 和 `ClassroomContext.visuals` 读取输入
- [ ] 内部生成 `knowledge.extraction`
- [ ] `source_segment_ids` 能对应 ASR 片段
- [ ] `source_visual_ids` 能对应视觉事件
- [ ] `entities[].name` 非空
- [ ] `relations[].source/target` 使用实体名称
- [ ] 前端知识图谱区出现节点和关系

硬件组：

- [ ] 确认后端可被局域网访问
- [ ] 确认图片保存路径
- [ ] 确认摄像头/麦克风采集归属
- [ ] 确认离线时是否继续缓存数据

前端组：

- [ ] 前端先创建课堂
- [ ] 页面显示 `session_id`
- [ ] WebSocket 已连接
- [ ] 能展示 ASR、OCR/VLM 和内部知识抽取产生的图谱更新
- [ ] 结束课堂后仍保留展示结果

## 12. 最小端到端样例

1. 前端开始课堂，得到：

```text
lec_20260613_010203_ab12cd34
```

2. 发送 ASR：

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "lec_20260613_010203_ab12cd34",
    "event_type": "transcript.segment",
    "payload": {
      "segment_id": "seg_001",
      "session_id": "lec_20260613_010203_ab12cd34",
      "start_ts": 1.0,
      "end_ts": 4.2,
      "text": "傅里叶变换可以把时域信号转换到频域。"
    }
  }'
```

3. 发送 OCR/VLM：

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "lec_20260613_010203_ab12cd34",
    "event_type": "image.capture",
    "payload": {
      "image_id": "img_001",
      "session_id": "lec_20260613_010203_ab12cd34",
      "capture_ts": 5.0,
      "image_path": "local://sessions/lec_20260613_010203_ab12cd34/images/img_001.jpg",
      "ocr_text": "X(f)=∫x(t)e^{-j2πft}dt",
      "caption": "课件展示傅里叶变换公式。"
    }
  }'
```

4. EDU-Mate 内部知识抽取模块生成知识抽取。

在内部模块尚未实现时，可以临时使用以下调试请求模拟内部结果：

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "lec_20260613_010203_ab12cd34",
    "event_type": "knowledge.extraction",
    "payload": {
      "extraction_id": "ext_001",
      "session_id": "lec_20260613_010203_ab12cd34",
      "source_segment_ids": ["seg_001"],
      "source_visual_ids": ["img_001"],
      "timestamp_range": [1.0, 5.0],
      "entities": [
        {"entity_id": "node_fourier_transform", "name": "傅里叶变换", "type": "concept"},
        {"entity_id": "node_frequency_domain", "name": "频域", "type": "concept"}
      ],
      "relations": [
        {"source": "傅里叶变换", "target": "频域", "relation": "maps_to"}
      ],
      "importance": 0.92
    }
  }'
```

5. 前端应显示：

```text
字幕：傅里叶变换可以把时域信号转换到频域。
OCR：X(f)=∫x(t)e^{-j2πft}dt
知识图谱：傅里叶变换 -> 频域
时间线：3 条记录
```
