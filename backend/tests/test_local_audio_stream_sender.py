import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.app.core import ContextManager, KnowledgeGraphManager
from backend.app.models import RealtimeEvent
from backend.scripts.local_audio_stream_sender import (
    AudioChunk,
    OpenVINOQwenExtractor,
    StreamConfig,
    StreamStats,
    TranscriptRecord,
    TranscriptCommitter,
    allocate_sentence_ranges,
    build_transcript_polish_prompt,
    build_transcript_polish_repair_prompt,
    chunk_time_ranges,
    filter_grounded_polished_sentences,
    is_grounded_polished_sentence,
    normalize_extraction_payload,
    normalize_polished_sentences,
    parse_json_object,
    resolve_backend_session_id,
    run_audio_stream,
    segment_id_for_chunk,
    sliding_chunk_time_ranges,
    strip_committed_overlap,
    transcript_compare_key,
)


class FakeTranscriber:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)

    def transcribe(self, audio: Any) -> str:
        return self.texts.pop(0)


class FakeExtractor:
    def extract(
        self,
        *,
        session_id: str,
        segments: list[TranscriptRecord],
        batch_index: int,
        max_new_tokens: int,
    ) -> dict[str, Any] | None:
        return normalize_extraction_payload(
            {
                "entities": [
                    {
                        "name": "傅里叶变换",
                        "type": "concept",
                        "description": "将信号从时域转换到频域",
                    },
                    {"name": "频域"},
                ],
                "relations": [
                    {
                        "source": "傅里叶变换",
                        "target": "频域",
                        "relation": "maps_to",
                    }
                ],
                "source_segment_ids": [segment.segment_id for segment in segments],
                "importance": 0.9,
            },
            session_id=session_id,
            segments=segments,
            extraction_id=f"ext_fake_{batch_index}",
        )


class BlockingExtractor(FakeExtractor):
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release

    def extract(
        self,
        *,
        session_id: str,
        segments: list[TranscriptRecord],
        batch_index: int,
        max_new_tokens: int,
    ) -> dict[str, Any] | None:
        self.started.set()
        self.release.wait(timeout=3)
        return super().extract(
            session_id=session_id,
            segments=segments,
            batch_index=batch_index,
            max_new_tokens=max_new_tokens,
        )


class FakePolisher:
    def __init__(self, outputs: list[list[str] | None]) -> None:
        self.outputs = list(outputs)
        self.previous_contexts: list[list[str]] = []

    def polish(
        self,
        *,
        raw_text: str,
        previous_context: list[str],
        max_new_tokens: int,
    ) -> list[str] | None:
        self.previous_contexts.append(list(previous_context))
        return self.outputs.pop(0)


class RepairingQwenExtractor(OpenVINOQwenExtractor):
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def _generate(self, prompt: str, *, max_new_tokens: int) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


class LocalAudioStreamSenderTest(unittest.TestCase):
    def test_resolve_backend_session_id_uses_existing_recording_session(self) -> None:
        with patch(
            "backend.scripts.local_audio_stream_sender.get_json",
            return_value=[{"session_id": "lec_existing"}],
        ):
            session_id = resolve_backend_session_id(
                requested_session_id="auto",
                base_url="http://127.0.0.1:8000",
                timeout=1.0,
            )

        self.assertEqual(session_id, "lec_existing")

    def test_resolve_backend_session_id_creates_session_when_none_recording(self) -> None:
        with patch(
            "backend.scripts.local_audio_stream_sender.get_json",
            return_value=[],
        ), patch(
            "backend.scripts.local_audio_stream_sender.post_json",
            return_value={"session_id": "lec_created"},
        ) as post_json_mock:
            session_id = resolve_backend_session_id(
                requested_session_id="",
                base_url="http://127.0.0.1:8000",
                timeout=1.0,
            )

        self.assertEqual(session_id, "lec_created")
        self.assertEqual(post_json_mock.call_args.args[1], "/sessions/start")

    def test_chunk_ranges_and_segment_ids_are_stable(self) -> None:
        ranges = chunk_time_ranges(total_samples=37, chunk_samples=15, sample_rate=10)

        self.assertEqual(
            ranges,
            [
                (1, 0.0, 1.5, 15),
                (2, 1.5, 3.0, 15),
                (3, 3.0, 3.7, 7),
            ],
        )
        self.assertEqual(segment_id_for_chunk(7), "seg_local_whisper_0007")

    def test_sliding_chunk_ranges_include_overlap(self) -> None:
        ranges = sliding_chunk_time_ranges(
            total_samples=100,
            chunk_samples=40,
            overlap_samples=10,
            sample_rate=10,
        )

        self.assertEqual(
            ranges,
            [
                (1, 0.0, 4.0, 40),
                (2, 3.0, 7.0, 40),
                (3, 6.0, 10.0, 40),
            ],
        )

    def test_transcript_committer_strips_overlap_on_flush(self) -> None:
        committed_key = transcript_compare_key("傅里叶变换可以转换信号")
        self.assertEqual(
            strip_committed_overlap("转换信号频域分析", committed_key),
            "频域分析",
        )

        committer = TranscriptCommitter(stable_rounds=2, stable_tail_chars=0)
        first = AudioChunk(index=1, start_ts=0.0, end_ts=4.0, audio=None)
        second = AudioChunk(index=2, start_ts=3.0, end_ts=7.0, audio=None)

        self.assertEqual(
            committer.push(chunk=first, text="傅里叶变换可以转换信号"),
            [],
        )
        stable = committer.push(chunk=second, text="转换信号频域分析")
        self.assertEqual([item.text for item in stable], ["傅里叶变换可以转换信号"])
        self.assertEqual([item.text for item in committer.flush()], ["频域分析"])

    def test_parse_json_object_accepts_code_fence_and_surrounding_text(self) -> None:
        fenced = '```json\n{"entities": [], "relations": []}\n```'
        surrounded = '说明文字 {"entities": [{"name": "采样定理"}], "relations": []} 结束'

        self.assertEqual(parse_json_object(fenced)["entities"], [])
        self.assertEqual(parse_json_object(surrounded)["entities"][0]["name"], "采样定理")

    def test_transcript_polish_helpers_split_and_timestamp_sentences(self) -> None:
        sentences = normalize_polished_sentences({"sentences": ["wrong"]})
        self.assertEqual(sentences, [])

        sentences = normalize_polished_sentences(
            ["同学们好，欢迎上课。", "傅里叶变换可以转换信号。", ""]
        )
        self.assertEqual(len(sentences), 2)
        ranges = allocate_sentence_ranges(
            chunk_start=10.0,
            chunk_end=20.0,
            texts=sentences,
        )

        self.assertEqual(ranges[0][0], 10.0)
        self.assertEqual(ranges[-1][1], 20.0)
        self.assertLess(ranges[0][1], ranges[1][1])
        self.assertIn(
            "Whisper 原始转写",
            build_transcript_polish_prompt(
                raw_text="同学们好欢迎上课",
                previous_context=["上一句。"],
            ),
        )

    def test_transcript_polish_grounding_rejects_hallucinated_sentences(self) -> None:
        raw_text = "同学们好今天讲傅里叶变换可以转换信号"

        self.assertTrue(
            is_grounded_polished_sentence(
                sentence="同学们好，今天讲傅里叶变换。",
                raw_text=raw_text,
            )
        )
        self.assertFalse(
            is_grounded_polished_sentence(
                sentence="下面我们来看一个具体的课堂例子。",
                raw_text=raw_text,
            )
        )
        self.assertEqual(
            filter_grounded_polished_sentences(
                raw_text=raw_text,
                sentences=[
                    "同学们好，今天讲傅里叶变换。",
                    "下面我们来看一个具体的课堂例子。",
                ],
                previous_context=[],
            ),
            ["同学们好，今天讲傅里叶变换。"],
        )

    def test_qwen_extractor_repairs_invalid_json_once(self) -> None:
        extractor = RepairingQwenExtractor(
            [
                "不是 JSON",
                '```json\n{"entities":[{"name":"采样定理"}],"relations":[],"importance":0.8}\n```',
            ]
        )
        segments = [
            TranscriptRecord(
                segment_id="seg_local_whisper_0001",
                start_ts=0.0,
                end_ts=15.0,
                text="采样定理说明采样频率需要满足条件。",
            )
        ]

        payload = extractor.extract(
            session_id="lec_audio_test",
            segments=segments,
            batch_index=1,
            max_new_tokens=200,
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["entities"][0]["name"], "采样定理")
        self.assertEqual(payload["source_segment_ids"], ["seg_local_whisper_0001"])
        self.assertEqual(payload["timestamp_range"], [0.0, 15.0])
        self.assertEqual(len(extractor.prompts), 2)

    def test_qwen_transcript_polish_repairs_to_sentence_schema(self) -> None:
        extractor = RepairingQwenExtractor(
            [
                "同学们好，今天讲傅里叶变换。",
                '{"sentences":["同学们好，今天讲傅里叶变换。"]}',
            ]
        )

        sentences = extractor.polish(
            raw_text="同学们好今天讲傅里叶变换",
            previous_context=[],
            max_new_tokens=120,
        )

        self.assertEqual(sentences, ["同学们好，今天讲傅里叶变换。"])
        self.assertEqual(len(extractor.prompts), 2)
        self.assertIn("sentences", extractor.prompts[1])
        self.assertNotIn("entities", extractor.prompts[1])
        self.assertIn("sentences", build_transcript_polish_repair_prompt("坏输出"))

    def test_run_audio_stream_sends_transcripts_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "sample.wav"
            media_path.write_bytes(b"placeholder")
            sent: list[tuple[str, dict[str, Any]]] = []

            def fake_send_event(**kwargs):  # type: ignore[no-untyped-def]
                sent.append((kwargs["event_type"], kwargs["payload"]))
                return {"status": "accepted"}

            config = StreamConfig(
                session_id="lec_audio_test",
                base_url="http://127.0.0.1:8000",
                input_path=media_path,
                whisper_model=Path("/unused/whisper"),
                qwen_model=Path("/unused/qwen"),
                whisper_device="NPU",
                qwen_device="GPU",
                chunk_seconds=15.0,
                max_audio_seconds=120.0,
                delay=0.0,
                extract_every=2,
                qwen_tokens=200,
                task="transcribe",
                language="",
                http_timeout=1.0,
                end_session=False,
                final_extraction=True,
                polish_transcript=False,
                polish_tokens=100,
                overlap_seconds=0.0,
                stable_rounds=1,
                stable_tail_chars=0,
                async_extraction=False,
                extraction_queue_size=8,
            )
            chunks = [
                AudioChunk(index=1, start_ts=0.0, end_ts=15.0, audio=None),
                AudioChunk(index=2, start_ts=15.0, end_ts=30.0, audio=None),
            ]

            stats = run_audio_stream(
                config,
                chunks=chunks,
                transcriber=FakeTranscriber(["第一段讲傅里叶变换。", "第二段讲频域。"]),
                extractor=FakeExtractor(),
                send_event_func=fake_send_event,
                sleep_func=lambda _: None,
            )

        self.assertEqual(stats.transcript_count, 2)
        self.assertEqual(stats.extraction_count, 1)
        self.assertEqual([item[0] for item in sent], [
            "transcript.segment",
            "transcript.segment",
            "knowledge.extraction",
        ])
        self.assertEqual(sent[0][1]["segment_id"], "seg_local_whisper_0001")
        self.assertEqual(sent[2][1]["source_segment_ids"], [
            "seg_local_whisper_0001",
            "seg_local_whisper_0002",
        ])

    def test_async_extraction_does_not_block_following_transcripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "sample.wav"
            media_path.write_bytes(b"placeholder")
            sent: list[tuple[str, dict[str, Any]]] = []
            sent_lock = threading.Lock()
            extraction_started = threading.Event()
            release_extraction = threading.Event()
            two_transcripts_sent = threading.Event()

            def fake_send_event(**kwargs):  # type: ignore[no-untyped-def]
                with sent_lock:
                    sent.append((kwargs["event_type"], kwargs["payload"]))
                    transcript_count = sum(
                        1 for event_type, _ in sent if event_type == "transcript.segment"
                    )
                    if transcript_count >= 2:
                        two_transcripts_sent.set()
                return {"status": "accepted"}

            config = StreamConfig(
                session_id="lec_audio_test",
                base_url="http://127.0.0.1:8000",
                input_path=media_path,
                whisper_model=Path("/unused/whisper"),
                qwen_model=Path("/unused/qwen"),
                whisper_device="NPU",
                qwen_device="GPU",
                chunk_seconds=4.0,
                max_audio_seconds=120.0,
                delay=0.0,
                extract_every=1,
                qwen_tokens=200,
                task="transcribe",
                language="",
                http_timeout=1.0,
                end_session=False,
                final_extraction=False,
                polish_transcript=False,
                polish_tokens=100,
                overlap_seconds=1.0,
                stable_rounds=1,
                stable_tail_chars=0,
                async_extraction=True,
                extraction_queue_size=8,
            )
            result: list[StreamStats] = []

            def run() -> None:
                result.append(
                    run_audio_stream(
                        config,
                        chunks=[
                            AudioChunk(index=1, start_ts=0.0, end_ts=4.0, audio=None),
                            AudioChunk(index=2, start_ts=3.0, end_ts=7.0, audio=None),
                        ],
                        transcriber=FakeTranscriber(["第一段讲傅里叶变换", "第二段讲频域"]),
                        extractor=BlockingExtractor(
                            started=extraction_started,
                            release=release_extraction,
                        ),
                        send_event_func=fake_send_event,
                        sleep_func=lambda _: None,
                    )
                )

            thread = threading.Thread(target=run)
            thread.start()

            try:
                self.assertTrue(extraction_started.wait(timeout=1.0))
                self.assertTrue(two_transcripts_sent.wait(timeout=1.0))
            finally:
                release_extraction.set()
                thread.join(timeout=2.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0].transcript_count, 2)
        self.assertEqual(result[0].extraction_count, 2)
        self.assertEqual([item[0] for item in sent[:2]], [
            "transcript.segment",
            "transcript.segment",
        ])

    def test_run_audio_stream_uses_polished_sentences_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "sample.wav"
            media_path.write_bytes(b"placeholder")
            sent: list[tuple[str, dict[str, Any]]] = []

            def fake_send_event(**kwargs):  # type: ignore[no-untyped-def]
                sent.append((kwargs["event_type"], kwargs["payload"]))
                return {"status": "accepted"}

            config = StreamConfig(
                session_id="lec_audio_test",
                base_url="http://127.0.0.1:8000",
                input_path=media_path,
                whisper_model=Path("/unused/whisper"),
                qwen_model=Path("/unused/qwen"),
                whisper_device="NPU",
                qwen_device="GPU",
                chunk_seconds=20.0,
                max_audio_seconds=120.0,
                delay=0.0,
                extract_every=2,
                qwen_tokens=200,
                task="transcribe",
                language="",
                http_timeout=1.0,
                end_session=False,
                final_extraction=False,
                polish_transcript=True,
                polish_tokens=100,
                overlap_seconds=0.0,
                stable_rounds=1,
                stable_tail_chars=0,
                async_extraction=False,
                extraction_queue_size=8,
            )
            chunks = [
                AudioChunk(index=1, start_ts=0.0, end_ts=20.0, audio=None),
            ]

            stats = run_audio_stream(
                config,
                chunks=chunks,
                transcriber=FakeTranscriber(["同学们好今天讲傅里叶变换可以转换信号"]),
                extractor=FakeExtractor(),
                polisher=FakePolisher([
                    ["同学们好，今天讲傅里叶变换。", "傅里叶变换可以转换信号。"]
                ]),
                send_event_func=fake_send_event,
                sleep_func=lambda _: None,
            )

        self.assertEqual(stats.transcript_count, 2)
        self.assertEqual([item[0] for item in sent], [
            "transcript.segment",
            "transcript.segment",
            "knowledge.extraction",
        ])
        self.assertEqual(sent[0][1]["segment_id"], "seg_local_whisper_0001_01")
        self.assertEqual(sent[1][1]["segment_id"], "seg_local_whisper_0001_02")
        self.assertEqual(sent[0][1]["text"], "同学们好，今天讲傅里叶变换。")
        self.assertEqual(sent[1][1]["end_ts"], 20.0)

    def test_run_audio_stream_falls_back_when_polish_hallucinates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "sample.wav"
            media_path.write_bytes(b"placeholder")
            sent: list[tuple[str, dict[str, Any]]] = []

            def fake_send_event(**kwargs):  # type: ignore[no-untyped-def]
                sent.append((kwargs["event_type"], kwargs["payload"]))
                return {"status": "accepted"}

            config = StreamConfig(
                session_id="lec_audio_test",
                base_url="http://127.0.0.1:8000",
                input_path=media_path,
                whisper_model=Path("/unused/whisper"),
                qwen_model=Path("/unused/qwen"),
                whisper_device="NPU",
                qwen_device="GPU",
                chunk_seconds=20.0,
                max_audio_seconds=120.0,
                delay=0.0,
                extract_every=2,
                qwen_tokens=200,
                task="transcribe",
                language="",
                http_timeout=1.0,
                end_session=False,
                final_extraction=False,
                polish_transcript=True,
                polish_tokens=100,
                overlap_seconds=0.0,
                stable_rounds=1,
                stable_tail_chars=0,
                async_extraction=False,
                extraction_queue_size=8,
            )

            stats = run_audio_stream(
                config,
                chunks=[AudioChunk(index=1, start_ts=0.0, end_ts=20.0, audio=None)],
                transcriber=FakeTranscriber(["傅里叶变换可以转换信号"]),
                extractor=FakeExtractor(),
                polisher=FakePolisher([["下面我们来看一个具体的课堂例子。"]]),
                send_event_func=fake_send_event,
                sleep_func=lambda _: None,
            )

        self.assertEqual(stats.transcript_count, 1)
        self.assertEqual(sent[0][0], "transcript.segment")
        self.assertEqual(sent[0][1]["text"], "傅里叶变换可以转换信号")

    def test_run_audio_stream_skips_recent_duplicate_transcripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "sample.wav"
            media_path.write_bytes(b"placeholder")
            sent: list[tuple[str, dict[str, Any]]] = []

            def fake_send_event(**kwargs):  # type: ignore[no-untyped-def]
                sent.append((kwargs["event_type"], kwargs["payload"]))
                return {"status": "accepted"}

            config = StreamConfig(
                session_id="lec_audio_test",
                base_url="http://127.0.0.1:8000",
                input_path=media_path,
                whisper_model=Path("/unused/whisper"),
                qwen_model=Path("/unused/qwen"),
                whisper_device="NPU",
                qwen_device="GPU",
                chunk_seconds=20.0,
                max_audio_seconds=120.0,
                delay=0.0,
                extract_every=2,
                qwen_tokens=200,
                task="transcribe",
                language="",
                http_timeout=1.0,
                end_session=False,
                final_extraction=False,
                polish_transcript=True,
                polish_tokens=100,
                overlap_seconds=0.0,
                stable_rounds=1,
                stable_tail_chars=0,
                async_extraction=False,
                extraction_queue_size=8,
            )

            stats = run_audio_stream(
                config,
                chunks=[
                    AudioChunk(index=1, start_ts=0.0, end_ts=20.0, audio=None),
                    AudioChunk(index=2, start_ts=20.0, end_ts=40.0, audio=None),
                ],
                transcriber=FakeTranscriber([
                    "傅里叶变换可以转换信号",
                    "傅里叶变换可以转换信号",
                ]),
                extractor=FakeExtractor(),
                polisher=FakePolisher([
                    ["傅里叶变换可以转换信号。"],
                    ["傅里叶变换可以转换信号。"],
                ]),
                send_event_func=fake_send_event,
                sleep_func=lambda _: None,
            )

        self.assertEqual(stats.transcript_count, 1)
        self.assertEqual([item[0] for item in sent], ["transcript.segment"])
        self.assertEqual(sent[0][1]["text"], "傅里叶变换可以转换信号。")

    def test_generated_extraction_updates_existing_graph_pipeline(self) -> None:
        session_id = "lec_audio_graph"
        context_manager = ContextManager()
        graph_manager = KnowledgeGraphManager()
        context_manager.start_session(session_id)
        graph_manager.start_session(session_id)

        segments = [
            TranscriptRecord(
                segment_id="seg_local_whisper_0001",
                start_ts=0.0,
                end_ts=15.0,
                text="傅里叶变换可以把时域信号转换到频域。",
            ),
            TranscriptRecord(
                segment_id="seg_local_whisper_0002",
                start_ts=15.0,
                end_ts=30.0,
                text="频域用于观察信号中的频率成分。",
            ),
        ]
        for segment in segments:
            context_manager.handle_event(
                RealtimeEvent(
                    session_id=session_id,
                    event_type="transcript.segment",
                    payload={
                        "segment_id": segment.segment_id,
                        "start_ts": segment.start_ts,
                        "end_ts": segment.end_ts,
                        "text": segment.text,
                    },
                )
            )

        payload = FakeExtractor().extract(
            session_id=session_id,
            segments=segments,
            batch_index=1,
            max_new_tokens=200,
        )
        assert payload is not None
        event = RealtimeEvent(
            session_id=session_id,
            event_type="knowledge.extraction",
            payload=payload,
        )
        context_manager.handle_event(event)
        patch = graph_manager.handle_event(event)

        self.assertIsNotNone(patch)
        assert patch is not None
        self.assertIn("add_node", [operation.op for operation in patch.operations])
        self.assertIn("add_edge", [operation.op for operation in patch.operations])
        self.assertEqual(len(graph_manager.get_graph(session_id).edges), 1)


if __name__ == "__main__":
    unittest.main()
