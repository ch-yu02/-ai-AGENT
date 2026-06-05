"""课堂模拟事件发送器。

这个脚本用于在真实 ASR、OCR/VLM、SLM 模块尚未接入时，假装这些模块
已经在持续产生数据。它会按顺序调用后端 HTTP API：

1. 创建一节课堂 session。
2. 按时间间隔发送模拟字幕、图片和知识抽取事件。
3. 默认自动结束课堂，触发本地保存。

运行前请先启动后端：

    .venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

然后运行：

    .venv/bin/python backend/scripts/mock_sender.py

如果要配合前端页面联调，先在前端点击“开始课堂”，复制页面上的
session_id，然后运行：

    .venv/bin/python backend/scripts/mock_sender.py --session-id lec_xxx --no-end
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class MockEvent:
    """一条待发送的模拟事件。

    event_type 对应后端 RealtimeEvent.event_type，payload 则模拟算法组
    或硬件采集模块产生的数据。
    """

    event_type: str
    payload: dict[str, Any]


def post_json(base_url: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """向后端发送 JSON POST 请求并返回 JSON 响应。

    这里使用 Python 标准库，避免为了一个演示脚本额外安装 requests。
    """

    url = base_url.rstrip("/") + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"请求失败：POST {url} -> {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接后端：{url}，请确认服务已启动。") from exc

    return json.loads(raw) if raw else {}


def build_mock_events(session_id: str) -> list[MockEvent]:
    """构造一组适合前端演示的中文课堂事件。

    事件刻意覆盖三类输入：
    - transcript.segment：实时字幕滚动
    - image.capture：时间线中的图片/OCR/VLM 结果
    - knowledge.extraction：知识图谱增量更新
    """

    return [
        MockEvent(
            event_type="transcript.segment",
            payload={
                "segment_id": "seg_001",
                "session_id": session_id,
                "start_ts": 1.0,
                "end_ts": 4.2,
                "text": "同学们好，今天我们继续学习通信原理中的傅里叶变换。",
                "speaker": "teacher",
                "confidence": 0.95,
                "is_final": True,
                "source": "mock_asr",
            },
        ),
        MockEvent(
            event_type="transcript.segment",
            payload={
                "segment_id": "seg_002",
                "session_id": session_id,
                "start_ts": 5.0,
                "end_ts": 9.6,
                "text": "傅里叶变换可以把时域信号转换到频域，帮助我们观察频率成分。",
                "speaker": "teacher",
                "confidence": 0.94,
                "is_final": True,
                "source": "mock_asr",
                "importance": 0.9,
            },
        ),
        MockEvent(
            event_type="knowledge.extraction",
            payload={
                "extraction_id": "ext_001",
                "session_id": session_id,
                "source_segment_ids": ["seg_001", "seg_002"],
                "timestamp_range": [1.0, 9.6],
                "entities": [
                    {
                        "entity_id": "node_fourier_transform",
                        "name": "傅里叶变换",
                        "type": "concept",
                        "description": "将信号从时域表示转换为频域表示的数学工具",
                    },
                    {
                        "entity_id": "node_time_domain",
                        "name": "时域",
                        "type": "concept",
                        "description": "从时间变化角度描述信号的表示方式",
                    },
                    {
                        "entity_id": "node_frequency_domain",
                        "name": "频域",
                        "type": "concept",
                        "description": "从频率成分角度描述信号的表示方式",
                    },
                ],
                "relations": [
                    {
                        "source": "傅里叶变换",
                        "target": "时域",
                        "relation": "input_domain",
                    },
                    {
                        "source": "傅里叶变换",
                        "target": "频域",
                        "relation": "output_domain",
                    },
                ],
                "importance": 0.92,
            },
        ),
        MockEvent(
            event_type="image.capture",
            payload={
                "image_id": "img_001",
                "session_id": session_id,
                "capture_ts": 10.5,
                "image_path": f"local://sessions/{session_id}/images/img_001.jpg",
                "source": "mock_camera",
                "image_type": "slide",
                "status": "processed",
                "ocr_text": "X(f)=∫x(t)e^{-j2πft}dt",
                "caption": "课件展示傅里叶变换公式，以及时域到频域的转换箭头。",
            },
        ),
        MockEvent(
            event_type="transcript.segment",
            payload={
                "segment_id": "seg_003",
                "session_id": session_id,
                "start_ts": 11.0,
                "end_ts": 16.8,
                "text": "屏幕上的公式说明，每一个连续信号都可以分解成不同频率的正弦波叠加。",
                "speaker": "teacher",
                "confidence": 0.93,
                "is_final": True,
                "source": "mock_asr",
            },
        ),
        MockEvent(
            event_type="knowledge.extraction",
            payload={
                "extraction_id": "ext_002",
                "session_id": session_id,
                "source_segment_ids": ["seg_003"],
                "source_visual_ids": ["img_001"],
                "timestamp_range": [10.5, 16.8],
                "entities": [
                    {
                        "entity_id": "node_signal",
                        "name": "信号",
                        "type": "concept",
                        "description": "携带信息并随时间或空间变化的物理量",
                    },
                    {
                        "entity_id": "node_sine_wave",
                        "name": "正弦波",
                        "type": "concept",
                        "description": "频域分析中的基本组成成分",
                    },
                    {
                        "entity_id": "node_frequency_component",
                        "name": "频率成分",
                        "type": "concept",
                        "description": "信号中不同频率对应的组成部分",
                    },
                ],
                "relations": [
                    {
                        "source": "信号",
                        "target": "正弦波",
                        "relation": "decomposed_into",
                    },
                    {
                        "source": "正弦波",
                        "target": "频率成分",
                        "relation": "represents",
                    },
                    {
                        "source": "傅里叶变换",
                        "target": "频率成分",
                        "relation": "extracts",
                    },
                ],
                "importance": 0.88,
            },
        ),
        MockEvent(
            event_type="transcript.segment",
            payload={
                "segment_id": "seg_004",
                "session_id": session_id,
                "start_ts": 18.0,
                "end_ts": 23.4,
                "text": "课后请大家完成教材第六章习题三，并预习采样定理。",
                "speaker": "teacher",
                "confidence": 0.96,
                "is_final": True,
                "source": "mock_asr",
                "importance": 0.85,
            },
        ),
        MockEvent(
            event_type="knowledge.extraction",
            payload={
                "extraction_id": "ext_003",
                "session_id": session_id,
                "source_segment_ids": ["seg_004"],
                "timestamp_range": [18.0, 23.4],
                "entities": [
                    {
                        "entity_id": "node_sampling_theorem",
                        "name": "采样定理",
                        "type": "concept",
                        "description": "描述连续信号可由离散采样点恢复的条件",
                    }
                ],
                "relations": [
                    {
                        "source": "采样定理",
                        "target": "通信原理",
                        "relation": "belongs_to",
                    }
                ],
                "importance": 0.8,
            },
        ),
    ]


def start_session(base_url: str) -> dict[str, Any]:
    """创建一节模拟课堂，返回后端生成的 session 对象。"""

    return post_json(
        base_url,
        "/sessions/start",
        {
            "title": "通信原理第8讲：傅里叶变换",
            "course": "通信原理",
            "teacher": "张老师",
            "language": "zh-CN",
            "created_by": "mock_sender",
            "device_id": "mock_device_001",
        },
    )


def send_event(base_url: str, session_id: str, event: MockEvent) -> dict[str, Any]:
    """把一条 MockEvent 包装成 RealtimeEvent 后发送给后端。"""

    return post_json(
        base_url,
        "/events",
        {
            "session_id": session_id,
            "event_type": event.event_type,
            "payload": event.payload,
        },
    )


def end_session(base_url: str, session_id: str) -> dict[str, Any]:
    """结束模拟课堂，让后端保存 metadata/transcript/timeline/graph 文件。"""

    return post_json(base_url, f"/sessions/{session_id}/end", {})


def run_mock_sender(
    base_url: str,
    delay: float,
    should_end: bool,
    session_id: str | None = None,
) -> str:
    """执行完整的模拟课堂数据流，返回本次写入的 session_id。

    默认行为保持原样：脚本自己创建一节课堂，然后往这节课堂发送 mock
    事件。前端联调时可以传入 ``session_id``，脚本会跳过创建课堂，直接
    往前端当前订阅的 session 写事件。
    """

    if session_id is None:
        session = start_session(base_url)
        session_id = session["session_id"]
        print(f"已创建模拟课堂：{session_id}")
    else:
        print(f"使用已有课堂：{session_id}")

    events = build_mock_events(session_id)
    for index, event in enumerate(events, start=1):
        # 逐条发送可以更接近真实课堂的“数据流”效果，前端能看到字幕和图谱增长。
        response = send_event(base_url, session_id, event)
        print(
            f"[{index:02d}/{len(events):02d}] 已发送 {event.event_type}，"
            f"后端累计事件数：{response.get('event_count')}"
        )
        if delay > 0 and index < len(events):
            time.sleep(delay)

    if should_end:
        ended = end_session(base_url, session_id)
        print(f"已结束模拟课堂：{ended['session_id']}，状态：{ended['status']}")
    else:
        print("已按 --no-end 要求保留课堂录制状态，可继续手动发送事件。")

    return session_id


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(
        description="向 EDU-Mate 后端发送一组模拟课堂事件。"
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"后端地址，默认 {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="每条事件之间的等待秒数，设为 0 可快速发送。默认 1.0",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="使用已有课堂 session_id；适合前端先开始课堂并订阅 WebSocket 后联调。",
    )
    parser.add_argument(
        "--no-end",
        action="store_true",
        help="发送完事件后不结束课堂，方便继续调试 WebSocket 或手动追加事件。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        session_id = run_mock_sender(
            base_url=args.base_url,
            delay=max(args.delay, 0.0),
            should_end=not args.no_end,
            session_id=args.session_id,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"模拟数据发送完成。session_id={session_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
