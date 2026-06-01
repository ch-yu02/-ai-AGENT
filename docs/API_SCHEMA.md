# 课堂会话数据 LectureSession
{
  "session_id": "lec_20260601_001",
  "title": "通信原理第8讲",
  "course": "通信原理",
  "teacher": "未知/可选",
  "start_time": "2026-06-01T09:00:00+08:00",
  "end_time": null,
  "status": "recording",
  "language": "zh-CN",
  "created_by": "student",
  "device_id": "dk2500_001"
}

# 实时语音转写片段 TranscriptSegment
{
  "segment_id": "seg_000128",
  "session_id": "lec_20260601_001",
  "start_ts": 128.40,
  "end_ts": 134.85,
  "text": "傅里叶变换可以把时域信号转换到频域进行分析。",
  "speaker": "teacher",
  "confidence": 0.92,
  "is_final": true,
  "source": "whisper",
  "created_at": "2026-06-01T09:02:14+08:00"
}

# 图像输入数据 ImageCapture
{
  "image_id": "img_000045",
  "session_id": "lec_20260601_001",
  "capture_ts": 132.10,
  "upload_time": "2026-06-01T09:02:12+08:00",
  "image_path": "local://sessions/lec_20260601_001/images/img_000045.jpg",
  "source": "phone_upload",
  "image_type": "ppt",
  "status": "processed"
}

# 结构化知识抽取结果 KnowledgeExtraction
{
  "extraction_id": "ext_000210",
  "session_id": "lec_20260601_001",
  "source_segment_ids": ["seg_000128", "seg_000129"],
  "source_visual_ids": ["vis_000045"],
  "timestamp_range": [128.40, 140.20],
  "entities": [
    {
      "entity_id": "ent_fourier_transform",
      "name": "傅里叶变换",
      "type": "concept",
      "description": "将时域信号转换到频域的数学工具"
    },
    {
      "entity_id": "ent_time_domain",
      "name": "时域",
      "type": "concept"
    },
    {
      "entity_id": "ent_frequency_domain",
      "name": "频域",
      "type": "concept"
    }
  ],
  "relations": [
    {
      "source": "傅里叶变换",
      "target": "时域",
      "relation": "input_domain"
    },
    {
      "source": "傅里叶变换",
      "target": "频域",
      "relation": "output_domain"
    }
  ],
  "importance": 0.91
}

# 动态知识树数据 KnowledgeTree
{
  "session_id": "lec_20260601_001",
  "version": 18,
  "root_nodes": ["node_signal_processing"],
  "nodes": [
    {
      "node_id": "node_fourier_transform",
      "label": "傅里叶变换",
      "type": "concept",
      "summary": "将时域信号转换为频域表示的方法",
      "level": 2,
      "importance": 0.91,
      "source_refs": [
        {
          "type": "segment",
          "id": "seg_000128",
          "ts": 128.40
        },
        {
          "type": "visual",
          "id": "vis_000045",
          "ts": 132.10
        }
      ]
    }
  ],
  "edges": [
    {
      "edge_id": "edge_001",
      "source": "node_fourier_transform",
      "target": "node_frequency_domain",
      "relation": "maps_to"
    }
  ],
  "updated_at": "2026-06-01T09:03:00+08:00"
}

# 前端增量更新数据 GraphPatch
{
  "session_id": "lec_20260601_001",
  "from_version": 17,
  "to_version": 18,
  "operations": [
    {
      "op": "add_node",
      "node": {
        "node_id": "node_fourier_transform",
        "label": "傅里叶变换",
        "type": "concept",
        "importance": 0.91
      }
    },
    {
      "op": "add_edge",
      "edge": {
        "edge_id": "edge_001",
        "source": "node_fourier_transform",
        "target": "node_frequency_domain",
        "relation": "maps_to"
      }
    }
  ]
}
