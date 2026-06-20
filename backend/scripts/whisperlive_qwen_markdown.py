"""Transcribe audio with WhisperLive, organize notes with local Qwen, and write Markdown.

This script is intentionally offline after model downloads:

1. Connect to a local WhisperLive OpenVINO server.
2. Stream a local audio file as 16 kHz mono float32 frames.
3. Collect completed WhisperLive transcript segments.
4. Ask local OpenVINO Qwen on CPU to periodically turn accumulated subtitles
   into classroom notes.
5. Keep updating one Markdown file. With ``--session-id`` it is saved as
   ``data/sessions/{session_id}/structured_notes.md``; without a session it
   falls back to ``data/whisperlive_markdown`` for offline smoke tests.

When ``--post-transcript`` or ``--enable-cloud-graph`` is enabled, the script
also syncs raw WhisperLive transcript events and Markdown snapshots to the
backend. Cloud graph extraction and final session naming are handled by the
backend, not by local Qwen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app import prompts as prompt_templates
from backend.scripts.local_audio_stream_sender import (
    DEFAULT_OPENVINO_ROOT,
    DEFAULT_QWEN_MODEL,
    MEDIA_EXTENSIONS,
    SAMPLE_RATE,
    parse_json_object,
    post_json,
    resolve_backend_session_id,
    result_text,
    send_event,
    sequence_coverage,
    transcript_compare_key,
)


DEFAULT_WHISPERLIVE_HOST = "127.0.0.1"
DEFAULT_WHISPERLIVE_PORT = 9090
DEFAULT_WHISPERLIVE_MODEL = os.getenv(
    "WHISPERLIVE_MODEL",
    "OpenVINO/whisper-large-v3-turbo-fp16-ov",
)
DEFAULT_INPUT = DEFAULT_OPENVINO_ROOT / "test_video"
DEFAULT_OUTPUT_DIR = Path("data/whisperlive_markdown")
DEFAULT_SESSIONS_DIR = Path("data/sessions")
DEFAULT_MARKDOWN_TITLE = "WhisperLive 本地课堂笔记"
ENGLISH_MARKDOWN_TITLE = "WhisperLive Local Classroom Notes"


@dataclass(frozen=True)
class WhisperLiveSegment:
    """One transcript segment received from WhisperLive."""

    start: float
    end: float
    text: str
    completed: bool


@dataclass(frozen=True)
class MarkdownResult:
    """Normalized Qwen markdown payload."""

    summary: list[str]
    sections: list[tuple[str, list[str]]]
    keywords: list[str]


@dataclass(frozen=True)
class BackendSyncTask:
    """One asynchronous backend sync task."""

    kind: str
    payload: dict[str, Any]


def log(message: str) -> None:
    """Print one timestamped log line."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def markdown_result_counts(result: MarkdownResult) -> dict[str, int]:
    """Return compact counts for Qwen Markdown diagnostics."""
    return {
        "summary": len(result.summary),
        "sections": len(result.sections),
        "bullets": sum(len(bullets) for _, bullets in result.sections),
        "keywords": len(result.keywords),
    }


def format_markdown_result_counts(result: MarkdownResult) -> str:
    """Format MarkdownResult counts as one log-friendly string."""
    counts = markdown_result_counts(result)
    return (
        f"summary={counts['summary']} sections={counts['sections']} "
        f"bullets={counts['bullets']} keywords={counts['keywords']}"
    )


def whisperlive_segment_id(segment: WhisperLiveSegment) -> str:
    """Create a stable transcript.segment ID for a WhisperLive segment."""
    start = int(round(segment.start * 1000))
    end = int(round(segment.end * 1000))
    digest = hashlib.sha1(  # noqa: S324 - stable local id, not security.
        f"{segment.start:.3f}|{segment.end:.3f}|{segment.text}".encode("utf-8")
    ).hexdigest()[:8]
    return f"seg_whisperlive_{start}_{end}_{digest}"


def transcript_payload(segment: WhisperLiveSegment) -> dict[str, Any]:
    """Convert one WhisperLive segment to the existing transcript.segment payload."""
    return {
        "segment_id": whisperlive_segment_id(segment),
        "start_ts": segment.start,
        "end_ts": segment.end,
        "text": segment.text,
        "speaker": "teacher",
        "confidence": None,
        "is_final": bool(segment.completed),
        "source": "whisperlive_openvino",
        "skip_realtime_extraction": True,
    }


def source_segment_payloads(segments: list[WhisperLiveSegment]) -> list[dict[str, Any]]:
    """Build source segment objects for notes-driven graph extraction."""
    return [
        {
            "segment_id": whisperlive_segment_id(segment),
            "start_ts": segment.start,
            "end_ts": segment.end,
            "text": segment.text,
        }
        for segment in segments
        if segment.text.strip()
    ]


class BackendSyncer:
    """Asynchronously sync WhisperLive transcripts and Markdown notes to EDU-Mate."""

    def __init__(
        self,
        *,
        base_url: str,
        session_id: str,
        http_timeout: float,
        post_transcript: bool,
        enable_cloud_graph: bool,
        graph_update_every_seconds: float,
    ) -> None:
        self.base_url = base_url
        self.session_id = session_id
        self.http_timeout = http_timeout
        self.post_transcript = post_transcript
        self.enable_cloud_graph = enable_cloud_graph
        self.graph_update_every_seconds = graph_update_every_seconds
        self._transcript_queue: queue.Queue[BackendSyncTask | None] = queue.Queue()
        self._notes_queue: queue.Queue[BackendSyncTask | None] = queue.Queue()
        self._transcript_thread: threading.Thread | None = None
        self._notes_thread: threading.Thread | None = None
        self._posted_transcript_ids: set[str] = set()
        self._posted_markdown_hashes: set[str] = set()
        self._last_graph_update_at = 0.0
        self.transcript_post_count = 0
        self.notes_post_count = 0

    @property
    def enabled(self) -> bool:
        """Return true when any backend sync behavior is enabled."""
        return bool(
            self.session_id
            and (
                self.post_transcript
                or self.enable_cloud_graph
            )
        )

    def start(self) -> None:
        """Start the worker thread when backend sync is enabled."""
        if not self.enabled:
            return
        if self.post_transcript and self._transcript_thread is None:
            self._transcript_thread = threading.Thread(
                target=self._run_queue,
                args=("transcript", self._transcript_queue),
                daemon=True,
            )
            self._transcript_thread.start()
        if self.enable_cloud_graph and self._notes_thread is None:
            self._notes_thread = threading.Thread(
                target=self._run_queue,
                args=("notes", self._notes_queue),
                daemon=True,
            )
            self._notes_thread.start()

    def stop(self) -> None:
        """Drain queued sync tasks and stop the worker."""
        if self._transcript_thread is not None:
            self._transcript_queue.join()
            self._transcript_queue.put(None)
            self._transcript_thread.join(timeout=10.0)
            self._transcript_thread = None
        if self._notes_thread is not None:
            self._notes_queue.join()
            self._notes_queue.put(None)
            self._notes_thread.join(timeout=10.0)
            self._notes_thread = None

    def enqueue_transcript(self, segment: WhisperLiveSegment) -> None:
        """Queue a final transcript segment for ``POST /events``."""
        if not self.enabled or not self.post_transcript or not segment.completed:
            return
        payload = transcript_payload(segment)
        segment_id = str(payload["segment_id"])
        if segment_id in self._posted_transcript_ids:
            return
        self._posted_transcript_ids.add(segment_id)
        self._transcript_queue.put(BackendSyncTask(kind="transcript", payload=payload))

    def enqueue_notes_update(
        self,
        markdown: str,
        segments: list[WhisperLiveSegment],
        update_status: str,
        sequence: int,
        output_path: Path,
        recent_segments: list[WhisperLiveSegment] | None = None,
    ) -> None:
        """Queue one Markdown notes snapshot for cloud graph extraction."""
        if not self.enabled or not self.enable_cloud_graph:
            return
        markdown_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        if markdown_hash in self._posted_markdown_hashes:
            log(f"Skip duplicate notes snapshot hash={markdown_hash[:10]}")
            return

        now = time.monotonic()
        should_throttle = (
            update_status != "final"
            and self.graph_update_every_seconds > 0
            and self._last_graph_update_at > 0
            and now - self._last_graph_update_at < self.graph_update_every_seconds
        )
        if should_throttle:
            wait_left = self.graph_update_every_seconds - (now - self._last_graph_update_at)
            log(
                "Throttle notes graph update "
                f"seq={sequence} status={update_status}; "
                f"wait_left={max(0.0, wait_left):.1f}s"
            )
            return

        self._posted_markdown_hashes.add(markdown_hash)
        self._last_graph_update_at = now
        snapshot_id = f"notes_{sequence:06d}_{update_status}"
        focused_segments = recent_segments or segments
        log(
            "Queue notes graph update "
            f"{snapshot_id}: markdown_chars={len(markdown)} "
            f"source_segments={len(segments)} recent_segments={len(focused_segments)}"
        )
        self._notes_queue.put(
            BackendSyncTask(
                kind="notes",
                payload={
                    "session_id": self.session_id,
                    "snapshot_id": snapshot_id,
                    "sequence": sequence,
                    "markdown": markdown,
                    "markdown_hash": markdown_hash,
                    "source_segments": source_segment_payloads(segments),
                    "recent_source_segments": source_segment_payloads(focused_segments),
                    "update_status": update_status,
                    "output_path": str(output_path),
                },
            )
        )

    def _run_queue(
        self,
        worker_name: str,
        task_queue: queue.Queue[BackendSyncTask | None],
    ) -> None:
        while True:
            task = task_queue.get()
            try:
                if task is None:
                    return
                if task.kind == "transcript":
                    self._post_transcript(task.payload)
                elif task.kind == "notes":
                    self._post_notes(task.payload)
            except Exception as exc:  # noqa: BLE001
                log(f"Backend sync {worker_name} failed: {exc}")
                if task and task.kind == "notes":
                    self._posted_markdown_hashes.discard(str(task.payload.get("markdown_hash", "")))
                if task and task.kind == "transcript":
                    self._posted_transcript_ids.discard(str(task.payload.get("segment_id", "")))
            finally:
                task_queue.task_done()

    def _post_transcript(self, payload: dict[str, Any]) -> None:
        send_event(
            base_url=self.base_url,
            session_id=self.session_id,
            event_type="transcript.segment",
            payload=payload,
            timeout=self.http_timeout,
        )
        self.transcript_post_count += 1

    def _post_notes(self, payload: dict[str, Any]) -> None:
        started_at = time.monotonic()
        response = post_json(
            self.base_url,
            "/agent/knowledge-tree/update-from-notes",
            {key: value for key, value in payload.items() if key != "output_path"},
            timeout=self.http_timeout,
        )
        elapsed = time.monotonic() - started_at
        self.notes_post_count += 1
        warnings = response.get("warnings") or []
        log(
            "POST notes snapshot "
            f"{payload['snapshot_id']} from {payload['output_path']} -> "
            f"{response.get('status')} ops={response.get('graph_patch_operations', 0)} "
            f"metadata_updated={response.get('session_metadata_updated', False)} "
            f"elapsed={elapsed:.2f}s warnings={warnings}"
        )


def find_media(path: Path) -> Path:
    """Resolve a media file from a direct file path or directory."""
    expanded = path.expanduser()
    if expanded.is_file():
        return expanded
    if not expanded.exists():
        raise FileNotFoundError(f"Input path does not exist: {expanded}")
    candidates = sorted(
        item
        for item in expanded.rglob("*")
        if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS
    )
    if not candidates:
        raise FileNotFoundError(f"No media file found under: {expanded}")
    return candidates[0]


def iter_audio_packets(
    input_path: Path,
    *,
    packet_seconds: float,
    max_audio_seconds: float,
    sample_rate: int = SAMPLE_RATE,
) -> Iterable[bytes]:
    """Decode media with ffmpeg and yield float32 mono audio packets."""
    if packet_seconds <= 0:
        raise ValueError("packet_seconds must be positive")

    import numpy as np  # noqa: PLC0415

    packet_samples = max(1, int(packet_seconds * sample_rate))
    packet_bytes = packet_samples * 4
    max_samples = (
        int(max_audio_seconds * sample_rate)
        if max_audio_seconds and max_audio_seconds > 0
        else None
    )
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "pipe:1",
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    emitted_samples = 0
    stopped_early = False
    try:
        while True:
            if max_samples is not None:
                remaining_samples = max_samples - emitted_samples
                if remaining_samples <= 0:
                    stopped_early = True
                    break
                read_bytes = min(packet_bytes, remaining_samples * 4)
            else:
                read_bytes = packet_bytes

            raw = process.stdout.read(read_bytes)
            if not raw:
                break
            audio = np.frombuffer(raw, dtype=np.float32).copy()
            if audio.size == 0:
                break
            np.nan_to_num(audio, copy=False)
            np.clip(audio, -1.0, 1.0, out=audio)
            emitted_samples += int(audio.size)
            yield audio.tobytes()
    finally:
        if stopped_early and process.poll() is None:
            process.terminate()
        if process.stdout:
            process.stdout.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()

    if return_code != 0 and not stopped_early:
        raise RuntimeError(f"ffmpeg failed for {input_path}: {stderr.strip()}")


class WhisperLiveFileClient:
    """Minimal file client for WhisperLive's websocket protocol."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        model: str,
        language: str,
        use_vad: bool,
        send_last_n_segments: int,
        no_speech_thresh: float,
        same_output_threshold: int,
        connect_timeout: float,
        on_completed_segment: Callable[[WhisperLiveSegment], None] | None = None,
        on_partial_segment: Callable[[WhisperLiveSegment], None] | None = None,
    ) -> None:
        try:
            import websocket  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "websocket-client is missing. Run: scripts/dev.sh install-whisperlive"
            ) from exc

        self.websocket_module = websocket
        self.url = f"ws://{host}:{port}"
        self.uid = str(uuid.uuid4())
        self.model = model
        self.language = language
        self.use_vad = use_vad
        self.send_last_n_segments = send_last_n_segments
        self.no_speech_thresh = no_speech_thresh
        self.same_output_threshold = same_output_threshold
        self.connect_timeout = connect_timeout
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.segments: list[WhisperLiveSegment] = []
        self._segments_lock = threading.Lock()
        self._seen_completed: set[tuple[str, str, str]] = set()
        self._receiver_error: Exception | None = None
        self._receiver_stop = threading.Event()
        self.on_completed_segment = on_completed_segment
        self.on_partial_segment = on_partial_segment

    def transcribe_file(
        self,
        input_path: Path,
        *,
        packet_seconds: float,
        max_audio_seconds: float,
        send_realtime: bool,
        tail_wait: float,
    ) -> list[WhisperLiveSegment]:
        """Stream one local file and return collected transcript segments."""
        ws = self.websocket_module.create_connection(self.url, timeout=self.connect_timeout)
        receiver = threading.Thread(target=self._receive_loop, args=(ws,), daemon=True)
        receiver.start()
        try:
            self._send_options(ws)
            self._wait_for_ready()
            sent_packets = 0
            start = time.time()
            for packet in iter_audio_packets(
                input_path,
                packet_seconds=packet_seconds,
                max_audio_seconds=max_audio_seconds,
            ):
                ws.send_binary(packet)
                sent_packets += 1
                if send_realtime:
                    time.sleep(packet_seconds)
            log(f"Sent {sent_packets} audio packet(s) in {time.time() - start:.2f}s")
            self._wait_for_tail(tail_wait)
            ws.send_binary(b"END_OF_AUDIO")
            time.sleep(0.5)
            return self._final_segments()
        finally:
            self._receiver_stop.set()
            try:
                ws.close()
            except Exception:
                pass
            receiver.join(timeout=2.0)

    def _send_options(self, ws: Any) -> None:
        ws.send(
            json.dumps(
                {
                    "uid": self.uid,
                    "language": self.language,
                    "task": "transcribe",
                    "model": self.model,
                    "use_vad": self.use_vad,
                    "send_last_n_segments": self.send_last_n_segments,
                    "no_speech_thresh": self.no_speech_thresh,
                    "clip_audio": False,
                    "same_output_threshold": self.same_output_threshold,
                    "enable_translation": False,
                    "target_language": "zh",
                    "hotwords": None,
                    "enable_diarization": False,
                    "max_speakers": 1,
                    "word_timestamps": False,
                },
                ensure_ascii=False,
            )
        )

    def _receive_loop(self, ws: Any) -> None:
        while not self._receiver_stop.is_set():
            try:
                raw = ws.recv()
            except Exception as exc:  # noqa: BLE001
                self._receiver_error = exc
                return
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("uid") != self.uid:
                continue
            self.messages.put(message)
            for segment in parse_whisperlive_segments(message):
                self._remember_segment(segment)

    def _remember_segment(self, segment: WhisperLiveSegment) -> None:
        completed_to_notify: WhisperLiveSegment | None = None
        partial_to_notify: WhisperLiveSegment | None = None
        with self._segments_lock:
            if segment.completed:
                key = (f"{segment.start:.3f}", f"{segment.end:.3f}", segment.text)
                if key in self._seen_completed:
                    return
                self._seen_completed.add(key)
                self.segments.append(segment)
                completed_to_notify = segment
            elif not self.segments or self.segments[-1].completed:
                self.segments.append(segment)
                partial_to_notify = segment
            else:
                self.segments[-1] = segment
                partial_to_notify = segment

        if completed_to_notify is not None and self.on_completed_segment is not None:
            self.on_completed_segment(completed_to_notify)
        if partial_to_notify is not None and self.on_partial_segment is not None:
            self.on_partial_segment(partial_to_notify)

    def _wait_for_ready(self) -> None:
        deadline = time.time() + self.connect_timeout
        while time.time() < deadline:
            try:
                message = self.messages.get(timeout=0.2)
            except queue.Empty:
                if self._receiver_error:
                    raise RuntimeError(f"WhisperLive receiver failed: {self._receiver_error}")
                continue
            if message.get("status") == "ERROR":
                raise RuntimeError(f"WhisperLive error: {message.get('message')}")
            if message.get("message") == "SERVER_READY":
                log(f"WhisperLive ready with backend {message.get('backend')}")
                return
        raise TimeoutError("Timed out waiting for WhisperLive SERVER_READY")

    def _wait_for_tail(self, tail_wait: float) -> None:
        deadline = time.time() + max(0.0, tail_wait)
        while time.time() < deadline:
            time.sleep(0.1)
            if self._receiver_error:
                break

    def _final_segments(self) -> list[WhisperLiveSegment]:
        return self.snapshot_segments(completed_only=False)

    def snapshot_segments(self, *, completed_only: bool = True) -> list[WhisperLiveSegment]:
        """Return a stable copy of collected transcript segments."""
        with self._segments_lock:
            return normalize_collected_segments(
                self.segments,
                completed_only=completed_only,
            )


def parse_whisperlive_segments(message: dict[str, Any]) -> list[WhisperLiveSegment]:
    """Extract normalized segments from one WhisperLive websocket message."""
    raw_segments = message.get("segments")
    if not isinstance(raw_segments, list):
        return []
    segments: list[WhisperLiveSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
        except (TypeError, ValueError):
            start = 0.0
            end = 0.0
        segments.append(
            WhisperLiveSegment(
                start=start,
                end=end,
                text=text,
                completed=bool(item.get("completed", False)),
            )
        )
    return segments


def overlap_seconds(left: WhisperLiveSegment, right: WhisperLiveSegment) -> float:
    """Return timestamp overlap between two transcript segments."""
    return max(0.0, min(left.end, right.end) - max(left.start, right.start))


def is_subsumed_partial(
    segment: WhisperLiveSegment,
    completed_segments: list[WhisperLiveSegment],
    *,
    threshold: float = 0.65,
) -> bool:
    """Return true when a partial segment is mostly covered by completed output."""
    if segment.completed:
        return False
    duration = max(0.01, segment.end - segment.start)
    return any(
        overlap_seconds(segment, completed) / duration >= threshold
        for completed in completed_segments
    )


def normalize_collected_segments(
    segments: list[WhisperLiveSegment],
    *,
    completed_only: bool,
) -> list[WhisperLiveSegment]:
    """Deduplicate and normalize collected WhisperLive segments."""
    clean: list[WhisperLiveSegment] = []
    completed_segments = [segment for segment in segments if segment.completed]
    seen_text_ranges: set[tuple[float, float, str]] = set()
    for segment in segments:
        if completed_only and not segment.completed:
            continue
        text = segment.text.strip()
        if not text:
            continue
        if is_subsumed_partial(segment, completed_segments):
            continue
        key = (round(segment.start, 2), round(segment.end, 2), text)
        if key in seen_text_ranges:
            continue
        seen_text_ranges.add(key)
        clean.append(
            WhisperLiveSegment(
                start=segment.start,
                end=segment.end,
                text=text,
                completed=segment.completed,
            )
        )
    return sorted(clean, key=lambda item: (item.start, item.end, item.completed))


class QwenMarkdownPolisher:
    """Local OpenVINO Qwen markdown generator."""

    def __init__(self, *, model_path: Path, device: str) -> None:
        import openvino_genai as ov_genai  # noqa: PLC0415

        log(f"Loading Qwen markdown model: {model_path} on {device}")
        self.pipe = ov_genai.LLMPipeline(str(model_path), device)

    def generate(
        self,
        segments: list[WhisperLiveSegment],
        *,
        max_new_tokens: int,
        domain_terms: list[str],
    ) -> MarkdownResult:
        """Generate structured Markdown data from transcript segments."""
        prompt = build_markdown_prompt(segments, domain_terms=domain_terms)
        raw = result_text(
            self.pipe.generate(prompt, max_new_tokens=max_new_tokens, do_sample=False)
        )
        try:
            payload = parse_json_object(raw)
        except ValueError:
            raw = result_text(
                self.pipe.generate(
                    build_markdown_repair_prompt(raw),
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                )
            )
            try:
                payload = parse_json_object(raw)
            except ValueError as exc:
                log(f"Qwen markdown JSON parse failed after repair: {exc}; using fallback")
                return fallback_markdown_result(segments)
        result = normalize_markdown_result(payload, segments)
        log(f"Qwen markdown raw counts: {format_markdown_result_counts(result)}")
        grounded = enforce_markdown_grounding(
            result,
            segments=segments,
            domain_terms=domain_terms,
        )
        log(f"Qwen markdown grounded counts: {format_markdown_result_counts(grounded)}")
        return grounded


def build_markdown_prompt(
    segments: list[WhisperLiveSegment],
    *,
    domain_terms: list[str],
) -> str:
    """Build a strict JSON prompt for Qwen markdown cleanup."""
    return prompt_templates.qwen_markdown_notes_prompt(
        segments=[
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            }
            for segment in segments
        ],
        domain_terms=domain_terms,
    )


def build_markdown_repair_prompt(raw_text: str) -> str:
    """Ask Qwen to repair malformed markdown JSON."""
    return prompt_templates.qwen_markdown_notes_repair_prompt(raw_text)


def normalize_markdown_result(
    payload: dict[str, Any],
    segments: list[WhisperLiveSegment],
) -> MarkdownResult:
    """Normalize Qwen JSON into MarkdownResult."""
    summary = clean_list(payload.get("summary"))
    keywords = clean_list(payload.get("keywords"))

    sections: list[tuple[str, list[str]]] = []
    raw_sections = payload.get("sections")
    if isinstance(raw_sections, list):
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            heading = clean_scalar(item.get("heading"))
            bullets = clean_list(item.get("bullets"))
            if heading and bullets:
                sections.append((heading, bullets))

    if not sections and summary:
        sections.append(("课堂要点", summary))
    return MarkdownResult(
        summary=summary,
        sections=sections,
        keywords=keywords,
    )


def fallback_markdown_result(segments: list[WhisperLiveSegment]) -> MarkdownResult:
    """Build a minimal MarkdownResult when Qwen returns malformed JSON."""
    return MarkdownResult(
        summary=[],
        sections=[],
        keywords=[],
    )


def combined_transcript_key(segments: list[WhisperLiveSegment]) -> str:
    """Return normalized transcript text used for grounding note items."""
    return transcript_compare_key("".join(segment.text for segment in segments))


def matched_character_count(candidate: str, source: str) -> int:
    """Return aligned character count between candidate and source."""
    matcher = SequenceMatcher(None, candidate, source, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks())


def is_grounded_note_item(
    text: str,
    *,
    transcript_key: str,
    domain_terms: list[str],
    min_coverage: float = 0.72,
) -> bool:
    """Return true when a note item is supported by the transcript."""
    item_key = transcript_compare_key(text)
    if not item_key or not transcript_key:
        return False
    if item_key in transcript_key:
        return True
    if len(item_key) <= 3:
        return False

    domain_keys = [transcript_compare_key(term) for term in domain_terms]
    for term_key in domain_keys:
        if term_key and term_key in item_key:
            item_key = item_key.replace(term_key, "")
    if not item_key:
        return True

    matched = matched_character_count(item_key, transcript_key)
    unmatched = len(item_key) - matched
    max_unmatched = max(3, int(len(item_key) * 0.15))
    return (
        sequence_coverage(item_key, transcript_key) >= min_coverage
        and unmatched <= max_unmatched
    )


def filter_grounded_list(
    values: list[str],
    *,
    transcript_key: str,
    domain_terms: list[str],
) -> list[str]:
    """Keep only note items grounded in transcript text."""
    return [
        item
        for item in values
        if is_grounded_note_item(
            item,
            transcript_key=transcript_key,
            domain_terms=domain_terms,
        )
    ]


def enforce_markdown_grounding(
    result: MarkdownResult,
    *,
    segments: list[WhisperLiveSegment],
    domain_terms: list[str],
) -> MarkdownResult:
    """Drop Qwen note content that is not supported by the transcript."""
    transcript_key = combined_transcript_key(segments)

    summary = filter_grounded_list(
        result.summary,
        transcript_key=transcript_key,
        domain_terms=domain_terms,
    )
    keywords = filter_grounded_list(
        result.keywords,
        transcript_key=transcript_key,
        domain_terms=domain_terms,
    )

    sections: list[tuple[str, list[str]]] = []
    for heading, bullets in result.sections:
        grounded_bullets = filter_grounded_list(
            bullets,
            transcript_key=transcript_key,
            domain_terms=domain_terms,
        )
        if grounded_bullets:
            sections.append((heading, grounded_bullets))

    if result.summary and not summary:
        log("Dropped ungrounded Qwen summary items")
    if result.sections and not sections:
        log("Dropped ungrounded Qwen section bullets")

    return MarkdownResult(
        summary=summary,
        sections=sections,
        keywords=keywords,
    )


def render_markdown(
    result: MarkdownResult,
    *,
    source_file: Path,
    whisper_model: str,
    segments: list[WhisperLiveSegment],
    update_status: str = "final",
) -> str:
    """Render a Markdown document."""
    labels = markdown_labels(result, segments)
    lines = [
        f"# {labels['title']}",
        "",
        f"- {labels['generated_at']}：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- {labels['update_status']}：{update_status}",
        f"- {labels['audio_file']}：`{source_file}`",
        f"- {labels['whisper_model']}：`{whisper_model}`",
        f"- {labels['segment_count']}：{len(segments)}",
        "",
    ]
    if result.summary:
        lines.extend([f"## {labels['summary']}", ""])
        lines.extend(f"- {item}" for item in result.summary)
        lines.append("")
    if result.keywords:
        keyword_joiner = "、" if labels["language"] == "zh" else ", "
        lines.extend([f"## {labels['keywords']}", "", keyword_joiner.join(result.keywords), ""])
    for heading, bullets in result.sections:
        lines.extend([f"## {heading}", ""])
        lines.extend(f"- {item}" for item in bullets)
        lines.append("")
    lines.extend([f"## {labels['subtitles']}", ""])
    for segment in segments:
        status = "final" if segment.completed else "partial"
        lines.append(f"- `{segment.start:.2f}-{segment.end:.2f}` ({status}) {segment.text}")
    lines.append("")
    return "\n".join(lines)


def markdown_labels(
    result: MarkdownResult,
    segments: list[WhisperLiveSegment],
) -> dict[str, str]:
    """Return Markdown chrome labels matching the main lecture language."""
    sample = "\n".join(
        [
            *result.summary,
            *result.keywords,
            *(bullet for _, bullets in result.sections for bullet in bullets),
            *(segment.text for segment in segments),
        ]
    )
    if main_text_language(sample) == "en":
        return {
            "language": "en",
            "title": ENGLISH_MARKDOWN_TITLE,
            "generated_at": "Generated at",
            "update_status": "Update status",
            "audio_file": "Audio file",
            "whisper_model": "WhisperLive model",
            "segment_count": "Subtitle segments",
            "summary": "Summary",
            "keywords": "Keywords",
            "subtitles": "WhisperLive Subtitles",
        }
    return {
        "language": "zh",
        "title": DEFAULT_MARKDOWN_TITLE,
        "generated_at": "生成时间",
        "update_status": "更新状态",
        "audio_file": "音频文件",
        "whisper_model": "WhisperLive 模型",
        "segment_count": "字幕段数",
        "summary": "摘要",
        "keywords": "关键词",
        "subtitles": "WhisperLive 字幕",
    }


def main_text_language(text: str) -> str:
    """Infer whether note chrome should use Chinese or English."""
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    return "en" if latin > 0 and cjk == 0 else "zh"


def make_markdown_output_path(
    output_dir: Path,
    input_path: Path,
    *,
    session_id: str = "",
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
) -> Path:
    """Build a stable output path for one streaming notes document."""
    if session_id.strip():
        return session_structured_notes_path(
            session_id.strip(),
            sessions_dir=sessions_dir,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", input_path.stem).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{timestamp}_{stem or 'audio'}_notes.md"


def session_structured_notes_path(session_id: str, *, sessions_dir: Path) -> Path:
    """Return the structured notes path inside one safe classroom session dir."""
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", session_id):
        raise ValueError(f"Unsafe session_id for notes output: {session_id}")

    root = sessions_dir.resolve()
    session_dir = (root / session_id).resolve()
    if not session_dir.is_relative_to(root):
        raise ValueError(f"Unsafe session_id path: {session_id}")

    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir / "structured_notes.md"


def write_markdown(
    markdown: str,
    *,
    output_dir: Path,
    input_path: Path,
    output_path: Path | None = None,
) -> Path:
    """Write markdown to disk and return the path."""
    output_path = output_path or make_markdown_output_path(output_dir, input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


class PeriodicMarkdownUpdater:
    """Periodically regenerate one Markdown notes file from transcript snapshots."""

    def __init__(
        self,
        *,
        qwen_factory: Callable[[], QwenMarkdownPolisher],
        snapshot_segments: Callable[[], list[WhisperLiveSegment]],
        output_path: Path,
        input_path: Path,
        whisper_model: str,
        domain_terms: list[str],
        max_new_tokens: int,
        update_every_seconds: float,
        min_update_segments: int,
        subtitle_update_every_seconds: float = 0.0,
        on_markdown_update: Callable[
            [
                str,
                list[WhisperLiveSegment],
                str,
                int,
                Path,
                list[WhisperLiveSegment],
            ],
            None,
        ]
        | None = None,
    ) -> None:
        self.qwen_factory = qwen_factory
        self.snapshot_segments = snapshot_segments
        self.output_path = output_path
        self.input_path = input_path
        self.whisper_model = whisper_model
        self.domain_terms = domain_terms
        self.max_new_tokens = max_new_tokens
        self.update_every_seconds = update_every_seconds
        self.min_update_segments = min_update_segments
        self.subtitle_update_every_seconds = subtitle_update_every_seconds
        self.on_markdown_update = on_markdown_update
        self._qwen: QwenMarkdownPolisher | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_fingerprint: tuple[tuple[float, float, str], ...] = ()
        self._last_subtitle_fingerprint: tuple[tuple[float, float, str], ...] = ()
        self._latest_qwen_result: MarkdownResult | None = None
        self.update_count = 0

    def start(self) -> None:
        """Start background periodic updates when enabled."""
        if self.update_every_seconds <= 0 and self.subtitle_update_every_seconds <= 0:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background updater without forcing a final write."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()

    def stop_and_flush(self, final_segments: list[WhisperLiveSegment]) -> Path | None:
        """Stop the background updater and write the final notes snapshot."""
        self.stop()
        if not final_segments:
            return None
        return self.write_update(final_segments, final=True)

    def latest_result(self) -> MarkdownResult | None:
        """Return the latest Qwen notes result, if one has been generated."""
        return self._latest_qwen_result

    def write_update(
        self,
        segments: list[WhisperLiveSegment],
        *,
        final: bool,
    ) -> Path | None:
        """Regenerate the notes file from the provided segment snapshot."""
        if not final and len(segments) < self.min_update_segments:
            return None
        fingerprint = self._fingerprint(segments)
        if not final and fingerprint == self._last_fingerprint:
            return None
        recent_segments = self._recent_segments_for_update(segments)
        self._last_fingerprint = fingerprint

        if self._qwen is None:
            self._qwen = self.qwen_factory()
        result = self._qwen.generate(
            segments,
            max_new_tokens=self.max_new_tokens,
            domain_terms=self.domain_terms,
        )
        self._latest_qwen_result = result
        markdown = render_markdown(
            result,
            source_file=self.input_path,
            whisper_model=self.whisper_model,
            segments=segments,
            update_status="final" if final else "streaming",
        )
        output_path = write_markdown(
            markdown,
            output_dir=self.output_path.parent,
            input_path=self.input_path,
            output_path=self.output_path,
        )
        self.update_count += 1
        update_status = "final" if final else "streaming"
        log(
            f"Wrote {update_status} Markdown update "
            f"#{self.update_count} from {len(segments)} segment(s): {output_path}"
        )
        if self.on_markdown_update is not None:
            self.on_markdown_update(
                markdown,
                segments,
                update_status,
                self.update_count,
                output_path,
                recent_segments,
            )
        return output_path

    def write_subtitle_snapshot(self, segments: list[WhisperLiveSegment]) -> Path | None:
        """Refresh the Markdown transcript section without invoking Qwen or the graph."""
        if not segments:
            return None
        fingerprint = self._fingerprint(segments)
        if fingerprint == self._last_subtitle_fingerprint:
            return None
        self._last_subtitle_fingerprint = fingerprint
        result = self._latest_qwen_result or fallback_markdown_result(segments)
        markdown = render_markdown(
            result,
            source_file=self.input_path,
            whisper_model=self.whisper_model,
            segments=segments,
            update_status="streaming",
        )
        output_path = write_markdown(
            markdown,
            output_dir=self.output_path.parent,
            input_path=self.input_path,
            output_path=self.output_path,
        )
        log(
            "Wrote streaming subtitle Markdown snapshot "
            f"from {len(segments)} segment(s); "
            f"qwen_notes={'ready' if self._latest_qwen_result else 'pending'}: {output_path}"
        )
        return output_path

    def _run(self) -> None:
        next_qwen_update_at = time.monotonic() + max(0.0, self.update_every_seconds)
        next_subtitle_update_at = time.monotonic()
        while not self._stop_event.wait(1.0):
            try:
                now = time.monotonic()
                segments = self.snapshot_segments()
                if (
                    self.subtitle_update_every_seconds > 0
                    and now >= next_subtitle_update_at
                ):
                    self.write_subtitle_snapshot(segments)
                    next_subtitle_update_at = now + self.subtitle_update_every_seconds

                first_qwen_update = self._last_fingerprint == ()
                qwen_due = (
                    self.update_every_seconds > 0
                    and len(segments) >= self.min_update_segments
                    and (first_qwen_update or now >= next_qwen_update_at)
                )
                if qwen_due:
                    self.write_update(segments, final=False)
                    next_qwen_update_at = time.monotonic() + self.update_every_seconds
            except Exception as exc:  # noqa: BLE001
                log(f"Markdown periodic update failed: {exc}")

    @staticmethod
    def _fingerprint(
        segments: list[WhisperLiveSegment],
    ) -> tuple[tuple[float, float, str], ...]:
        return tuple((round(item.start, 2), round(item.end, 2), item.text) for item in segments)

    def _recent_segments_for_update(
        self,
        segments: list[WhisperLiveSegment],
    ) -> list[WhisperLiveSegment]:
        """Return the new subtitle window since the previous Qwen notes update."""
        previous = set(self._last_fingerprint)
        recent = [
            segment
            for segment in segments
            if (round(segment.start, 2), round(segment.end, 2), segment.text) not in previous
        ]
        if recent:
            return recent[-max(5, self.min_update_segments) :]
        return segments[-max(5, self.min_update_segments) :]


def clean_scalar(value: object) -> str:
    """Normalize a scalar text value."""
    if value is None:
        return ""
    return str(value).strip()


def clean_list(value: object) -> list[str]:
    """Normalize a JSON array into unique non-empty strings."""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = clean_scalar(item)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def parse_domain_terms(raw_terms: str) -> list[str]:
    """Parse comma/newline separated domain terms."""
    if not raw_terms.strip():
        return []
    items = re.split(r"[,，;；\n]+", raw_terms)
    return clean_list(items)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="WhisperLive local ASR + Qwen CPU markdown smoke."
    )
    parser.add_argument("--server", default=DEFAULT_WHISPERLIVE_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_WHISPERLIVE_PORT)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Audio file or directory.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=(
            "Fallback Markdown output directory when --session-id is not provided. "
            "Session runs save to data/sessions/{session_id}/structured_notes.md."
        ),
    )
    parser.add_argument(
        "--sessions-dir",
        default=str(DEFAULT_SESSIONS_DIR),
        help="Base directory for session-scoped Markdown output.",
    )
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"))
    parser.add_argument(
        "--session-id",
        default="",
        help=(
            "Existing session_id for backend transcript/graph sync. Use 'auto' "
            "or omit it with --post-transcript/--enable-cloud-graph to attach to "
            "the newest recording session, creating one if none exists."
        ),
    )
    parser.add_argument("--whisperlive-model", default=DEFAULT_WHISPERLIVE_MODEL)
    parser.add_argument("--language", default="<|zh|>")
    parser.add_argument("--max-audio-seconds", type=float, default=120.0)
    parser.add_argument("--packet-seconds", type=float, default=0.25)
    parser.add_argument("--fast-send", action="store_true", help="Send audio faster than realtime.")
    parser.add_argument("--tail-wait", type=float, default=8.0)
    parser.add_argument("--connect-timeout", type=float, default=300.0)
    parser.add_argument("--qwen-model", default=str(DEFAULT_QWEN_MODEL))
    parser.add_argument("--qwen-device", default=os.getenv("QWEN_DEVICE", "CPU"))
    parser.add_argument("--qwen-tokens", type=int, default=900)
    parser.add_argument(
        "--update-every-seconds",
        type=float,
        default=30.0,
        help="Regenerate Qwen structured Markdown notes every N seconds. Use 0 for final-only.",
    )
    parser.add_argument(
        "--subtitle-update-every-seconds",
        type=float,
        default=5.0,
        help=(
            "Refresh Markdown transcript snapshots every N seconds without invoking "
            "Qwen or cloud graph extraction. Use 0 to disable."
        ),
    )
    parser.add_argument(
        "--min-update-segments",
        type=int,
        default=2,
        help="Minimum completed transcript segments required for a streaming Markdown update.",
    )
    parser.add_argument(
        "--post-transcript",
        action="store_true",
        help="POST completed WhisperLive transcript.segment events to the backend.",
    )
    parser.add_argument(
        "--enable-cloud-graph",
        action="store_true",
        help="POST Markdown note snapshots to the backend cloud knowledge-tree agent.",
    )
    parser.add_argument(
        "--graph-update-every-seconds",
        type=float,
        default=60.0,
        help="Minimum interval between streaming Markdown graph updates. Final updates always send.",
    )
    parser.add_argument(
        "--no-update-session-name",
        action="store_true",
        help=(
            "Deprecated compatibility flag. Session title/course are inferred "
            "by the backend cloud notes agent on final snapshots."
        ),
    )
    parser.add_argument("--http-timeout", type=float, default=30.0)
    parser.add_argument(
        "--domain-terms",
        default=os.getenv("DOMAIN_TERMS", ""),
        help="Comma separated terms Qwen may use for conservative notes correction.",
    )
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--send-last-n-segments", type=int, default=12)
    parser.add_argument("--no-speech-thresh", type=float, default=0.45)
    parser.add_argument("--same-output-threshold", type=int, default=6)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv or sys.argv[1:])
    input_path = find_media(Path(args.input))
    log(f"Input media: {input_path}")
    log(f"WhisperLive server: {args.server}:{args.port}")
    log(f"WhisperLive model: {args.whisperlive_model}")
    sync_enabled = bool(args.post_transcript or args.enable_cloud_graph)
    session_id = args.session_id.strip()
    needs_backend_session = sync_enabled
    if needs_backend_session:
        session_id = resolve_backend_session_id(
            requested_session_id=session_id or "auto",
            base_url=args.backend_url,
            timeout=args.http_timeout,
        )
    post_transcript = bool(args.post_transcript or args.enable_cloud_graph)
    syncer = BackendSyncer(
        base_url=args.backend_url,
        session_id=session_id,
        http_timeout=args.http_timeout,
        post_transcript=post_transcript,
        enable_cloud_graph=bool(args.enable_cloud_graph),
        graph_update_every_seconds=args.graph_update_every_seconds,
    )
    syncer.start()
    if syncer.enabled:
        log(
            "Backend sync enabled: "
            f"transcript={post_transcript}, cloud_graph={args.enable_cloud_graph}, "
            f"url={args.backend_url}, session={session_id}"
        )
    client = WhisperLiveFileClient(
        host=args.server,
        port=args.port,
        model=args.whisperlive_model,
        language=args.language,
        use_vad=not args.no_vad,
        send_last_n_segments=args.send_last_n_segments,
        no_speech_thresh=args.no_speech_thresh,
        same_output_threshold=args.same_output_threshold,
        connect_timeout=args.connect_timeout,
        on_completed_segment=syncer.enqueue_transcript,
    )
    output_path = make_markdown_output_path(
        Path(args.output_dir),
        input_path,
        session_id=session_id,
        sessions_dir=Path(args.sessions_dir),
    )
    domain_terms = parse_domain_terms(args.domain_terms)
    updater = PeriodicMarkdownUpdater(
        qwen_factory=lambda: QwenMarkdownPolisher(
            model_path=Path(args.qwen_model),
            device=args.qwen_device,
        ),
        snapshot_segments=lambda: client.snapshot_segments(completed_only=True),
        output_path=output_path,
        input_path=input_path,
        whisper_model=args.whisperlive_model,
        domain_terms=domain_terms,
        max_new_tokens=args.qwen_tokens,
        update_every_seconds=args.update_every_seconds,
        min_update_segments=max(1, args.min_update_segments),
        subtitle_update_every_seconds=max(0.0, args.subtitle_update_every_seconds),
        on_markdown_update=syncer.enqueue_notes_update,
    )
    log(f"Markdown output: {output_path}")
    if args.update_every_seconds > 0:
        log(
            "Qwen structured Markdown updates immediately after "
            f"{max(1, args.min_update_segments)} segment(s), then every "
            f"{args.update_every_seconds:.1f}s"
        )
    if args.subtitle_update_every_seconds > 0:
        log(
            "Subtitle Markdown snapshots every "
            f"{args.subtitle_update_every_seconds:.1f}s between Qwen notes updates"
        )

    segments: list[WhisperLiveSegment] = []
    updater.start()
    try:
        segments = client.transcribe_file(
            input_path,
            packet_seconds=args.packet_seconds,
            max_audio_seconds=args.max_audio_seconds,
            send_realtime=not args.fast_send,
            tail_wait=args.tail_wait,
        )
    except Exception:
        updater.stop()
        syncer.stop()
        raise
    if not segments:
        updater.stop()
        syncer.stop()
        raise RuntimeError("WhisperLive returned no transcript segments")

    log(f"Collected {len(segments)} transcript segment(s)")
    final_output_path = updater.stop_and_flush(segments)
    if final_output_path:
        log(f"Final Markdown ready: {final_output_path}")
    syncer.stop()
    if syncer.enabled:
        log(
            "Backend sync finished: "
            f"transcripts={syncer.transcript_post_count}, "
            f"notes={syncer.notes_post_count}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
