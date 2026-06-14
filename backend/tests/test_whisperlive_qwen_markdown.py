import tempfile
import unittest
from pathlib import Path

from backend.scripts.whisperlive_qwen_markdown import (
    MarkdownResult,
    PeriodicMarkdownUpdater,
    WhisperLiveSegment,
    build_markdown_prompt,
    enforce_markdown_grounding,
    fallback_markdown_result,
    make_markdown_output_path,
    is_subsumed_partial,
    normalize_collected_segments,
    normalize_markdown_result,
    parse_domain_terms,
    parse_whisperlive_segments,
    render_markdown,
)


class FakeMarkdownPolisher:
    def __init__(self) -> None:
        self.calls: list[list[WhisperLiveSegment]] = []

    def generate(
        self,
        segments: list[WhisperLiveSegment],
        *,
        max_new_tokens: int,
        domain_terms: list[str],
    ) -> MarkdownResult:
        self.calls.append(list(segments))
        return MarkdownResult(
            title="实时课堂笔记",
            summary=["记录课堂内容和重点"],
            sections=[("课堂重点", [segment.text for segment in segments])],
            keywords=domain_terms,
            clean_transcript=[segment.text for segment in segments],
        )


class WhisperLiveQwenMarkdownTest(unittest.TestCase):
    def test_parse_whisperlive_segments_filters_empty_items(self) -> None:
        segments = parse_whisperlive_segments(
            {
                "segments": [
                    {
                        "start": "1.250",
                        "end": "3.500",
                        "text": "  采样定理  ",
                        "completed": True,
                    },
                    {"start": "bad", "end": None, "text": "频域", "completed": False},
                    {"text": ""},
                    "not-a-segment",
                ]
            }
        )

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].start, 1.25)
        self.assertEqual(segments[0].end, 3.5)
        self.assertEqual(segments[0].text, "采样定理")
        self.assertTrue(segments[0].completed)
        self.assertEqual(segments[1].start, 0.0)
        self.assertFalse(segments[1].completed)

    def test_subsumed_partial_detects_completed_overlap(self) -> None:
        completed = [WhisperLiveSegment(0.0, 5.0, "完整句子", True)]

        self.assertTrue(
            is_subsumed_partial(
                WhisperLiveSegment(0.0, 3.0, "局部句子", False),
                completed,
            )
        )
        self.assertFalse(
            is_subsumed_partial(
                WhisperLiveSegment(5.1, 7.0, "新句子", False),
                completed,
            )
        )

    def test_normalize_collected_segments_can_keep_only_completed(self) -> None:
        segments = normalize_collected_segments(
            [
                WhisperLiveSegment(0.0, 2.0, "局部", False),
                WhisperLiveSegment(0.0, 2.0, "完整", True),
                WhisperLiveSegment(2.0, 3.0, "尾部", False),
            ],
            completed_only=True,
        )

        self.assertEqual([segment.text for segment in segments], ["完整"])

    def test_domain_terms_are_parsed_and_added_to_prompt(self) -> None:
        terms = parse_domain_terms("线性代数，薛定谔方程; 傅里叶变换")
        prompt = build_markdown_prompt(
            [WhisperLiveSegment(0.0, 1.0, "线形代数", True)],
            domain_terms=terms,
        )

        self.assertEqual(terms, ["线性代数", "薛定谔方程", "傅里叶变换"])
        self.assertIn("线性代数、薛定谔方程、傅里叶变换", prompt)
        self.assertIn("Few-shot", prompt)
        self.assertIn("课堂语音转录助手", prompt)
        self.assertIn("课堂内容、重点", prompt)

    def test_fallback_markdown_result_uses_segment_text(self) -> None:
        result = fallback_markdown_result(
            [WhisperLiveSegment(0.0, 1.0, "傅里叶变换", True)]
        )

        self.assertEqual(result.title, "WhisperLive 本地课堂笔记")
        self.assertEqual(result.clean_transcript, ["傅里叶变换"])

    def test_normalize_markdown_result_uses_transcript_fallbacks(self) -> None:
        source_segments = [
            WhisperLiveSegment(0.0, 1.0, "同学们好", True),
            WhisperLiveSegment(1.0, 2.0, "今天讲频域", True),
        ]
        result = normalize_markdown_result(
            {
                "title": "  课堂笔记  ",
                "summary": ["傅里叶变换", "傅里叶变换", ""],
                "sections": [{"heading": "", "bullets": ["跳过"]}],
                "keywords": ["频域", "频域"],
            },
            source_segments,
        )

        self.assertEqual(result.title, "课堂笔记")
        self.assertEqual(result.summary, ["傅里叶变换"])
        self.assertEqual(result.sections, [("课堂要点", ["傅里叶变换"])])
        self.assertEqual(result.keywords, ["频域"])
        self.assertEqual(result.clean_transcript, ["同学们好", "今天讲频域"])

    def test_enforce_markdown_grounding_drops_hallucinated_notes(self) -> None:
        segments = [
            WhisperLiveSegment(0.0, 1.0, "文化渗透指的是在中国传教", True),
            WhisperLiveSegment(1.0, 2.0, "办教会学校办报纸宣扬西方价值观", True),
        ]
        result = enforce_markdown_grounding(
            MarkdownResult(
                title="文化渗透",
                summary=["文化渗透", "民主自由人权"],
                sections=[
                    (
                        "文化渗透",
                        [
                            "在中国传教",
                            "西方的价值观包括民主、自由、人权等",
                        ],
                    )
                ],
                keywords=["文化渗透", "人权"],
                clean_transcript=[
                    "文化渗透指的是在中国传教。",
                    "文化渗透推动了民族意识觉醒。",
                ],
            ),
            segments=segments,
            domain_terms=[],
        )

        self.assertEqual(result.summary, ["文化渗透"])
        self.assertEqual(result.sections, [("文化渗透", ["在中国传教"])])
        self.assertEqual(result.keywords, ["文化渗透"])
        self.assertEqual(result.clean_transcript, ["文化渗透指的是在中国传教。"])

    def test_render_markdown_includes_polished_and_raw_transcripts(self) -> None:
        segments = [WhisperLiveSegment(0.0, 2.0, "原始字幕", True)]
        markdown = render_markdown(
            MarkdownResult(
                title="测试标题",
                summary=["摘要"],
                sections=[("小节", ["条目"])],
                keywords=["关键词"],
                clean_transcript=["润色字幕。"],
            ),
            source_file=Path("/tmp/audio.mp3"),
            whisper_model="OpenVINO/whisper-base-fp16-ov",
            segments=segments,
        )

        self.assertIn("# 测试标题", markdown)
        self.assertIn("更新状态：final", markdown)
        self.assertIn("## 润色字幕", markdown)
        self.assertIn("1. 润色字幕。", markdown)
        self.assertIn("`0.00-2.00` (final) 原始字幕", markdown)

    def test_periodic_markdown_updater_writes_same_file(self) -> None:
        fake_qwen = FakeMarkdownPolisher()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "lecture.wav"
            input_path.write_bytes(b"")
            output_path = make_markdown_output_path(Path(tmpdir), input_path)
            updater = PeriodicMarkdownUpdater(
                qwen_factory=lambda: fake_qwen,
                snapshot_segments=lambda: [],
                output_path=output_path,
                input_path=input_path,
                whisper_model="OpenVINO/whisper-large-v3-turbo-fp16-ov",
                domain_terms=["傅里叶变换"],
                max_new_tokens=128,
                update_every_seconds=0,
                min_update_segments=2,
            )

            self.assertIsNone(
                updater.write_update(
                    [WhisperLiveSegment(0.0, 1.0, "第一句", True)],
                    final=False,
                )
            )
            written = updater.write_update(
                [
                    WhisperLiveSegment(0.0, 1.0, "第一句", True),
                    WhisperLiveSegment(1.0, 2.0, "第二句", True),
                ],
                final=False,
            )
            self.assertEqual(written, output_path)
            self.assertIn("更新状态：streaming", output_path.read_text(encoding="utf-8"))

            updater.write_update(
                [WhisperLiveSegment(0.0, 1.0, "最终句", True)],
                final=True,
            )
            markdown = output_path.read_text(encoding="utf-8")
            self.assertIn("更新状态：final", markdown)
            self.assertIn("最终句", markdown)
            self.assertEqual(len(fake_qwen.calls), 2)


if __name__ == "__main__":
    unittest.main()
