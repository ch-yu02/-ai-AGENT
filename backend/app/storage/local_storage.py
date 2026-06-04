"""本地课堂数据存储模块。

LocalStorage 负责把一次课堂结束时的内存状态保存到磁盘。MVP 阶段的
保存目录遵循任务清单中的结构：

  data/sessions/{session_id}/metadata.json
  data/sessions/{session_id}/transcript.md
  data/sessions/{session_id}/timeline.json
  data/sessions/{session_id}/knowledge_graph.json

职责边界
--------
- 负责：创建目录、序列化 Pydantic 模型、写入课堂产物文件。
- 不负责：判断 session 是否可结束、处理实时事件、生成知识图谱。

为什么结束课堂时统一写？
----------------------
MVP 阶段先保证“演示主链路”稳定：课堂中全部数据留在内存，结束时一次性
落盘。这样逻辑简单、易测试。后续若担心断电丢数据，可以扩展为事件级
增量写入或定时快照。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from backend.app.models import ClassroomContext, KnowledgeTree, LectureSession


@dataclass(frozen=True)
class StorageWriteResult:
    """一次课堂保存操作的结果。

    session_dir: 本次课堂数据目录
    files:       写出的文件名到绝对/相对路径的映射，便于 API 日志和测试断言
    """

    session_dir: Path
    files: dict[str, Path]


class LocalStorage:
    """Write classroom session artifacts to the local filesystem."""

    def __init__(self, base_dir: Path | str = Path("data/sessions")) -> None:
        # base_dir 默认是项目根目录下的 data/sessions。测试时可传临时目录，
        # 避免污染真实 demo 数据。
        self.base_dir = Path(base_dir)

    # ── 对外入口 ─────────────────────────────────────────────

    def save_session(
        self,
        session: LectureSession,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> StorageWriteResult:
        """Persist all MVP classroom artifacts for one ended session.

        调用时机：POST /sessions/{session_id}/end 成功后。

        写入内容：
          - metadata.json：课堂元信息
          - transcript.md：人可读的 Markdown 字幕记录
          - timeline.json：前端可回放的统一时间线
          - knowledge_graph.json：完整知识图谱快照
        """
        session_dir = self.session_dir(session.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        files = {
            "metadata": session_dir / "metadata.json",
            "transcript": session_dir / "transcript.md",
            "timeline": session_dir / "timeline.json",
            "knowledge_graph": session_dir / "knowledge_graph.json",
        }

        self._write_json(files["metadata"], session.model_dump())
        self._write_text(files["transcript"], self._render_transcript_markdown(context))
        self._write_json(
            files["timeline"],
            [item.model_dump() for item in context.timeline],
        )
        self._write_json(files["knowledge_graph"], knowledge_graph.model_dump())

        return StorageWriteResult(session_dir=session_dir, files=files)

    def session_dir(self, session_id: str) -> Path:
        """Return the filesystem directory for a session."""
        return self.base_dir / session_id

    def session_exists(self, session_id: str) -> bool:
        """Return whether a persisted session directory exists."""
        return self.session_dir(session_id).exists()

    def read_metadata(self, session_id: str) -> dict:
        """Read persisted metadata.json for history features.

        后续 GET /sessions 在内存 miss 时可调用此方法回退读取历史课堂。
        """
        return self._read_json(self.session_dir(session_id) / "metadata.json")

    # ── 文件格式处理 ─────────────────────────────────────────

    def _render_transcript_markdown(self, context: ClassroomContext) -> str:
        """Render transcript segments into a readable Markdown file.

        Markdown 比纯 JSON 更适合学生课后直接打开阅读。每条字幕带课堂内
        起止时间，方便和 timeline / 图片回溯对齐。
        """
        lines = [
            f"# Transcript - {context.session_id}",
            "",
        ]

        if not context.transcript:
            lines.append("_No transcript segments recorded._")
            lines.append("")
            return "\n".join(lines)

        for segment in context.transcript:
            speaker = segment.speaker or "unknown"
            lines.append(
                f"- [{segment.start_ts:.2f}s - {segment.end_ts:.2f}s] "
                f"**{speaker}**: {segment.text}"
            )

        lines.append("")
        return "\n".join(lines)

    def _write_json(self, path: Path, data: object) -> None:
        """Write JSON with UTF-8 and stable pretty formatting."""
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_json(self, path: Path) -> dict:
        """Read one JSON file as a dictionary."""
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_text(self, path: Path, content: str) -> None:
        """Write UTF-8 text content."""
        path.write_text(content, encoding="utf-8")


local_storage = LocalStorage()
"""Default storage instance used by API routes."""
