"""真实 LLM provider 手动 smoke test。

该脚本不会被默认单元测试调用，适合在本地确认 DeepSeek/OpenAI/local
OpenAI-compatible 服务是否能产出技能需要的结构化 JSON。

运行方式：

```bash
scripts/dev.sh llm-smoke
```

无模型配置时脚本返回 0 并提示跳过；有配置但 provider 不可用、返回非 JSON 或
结构不符合技能要求时，技能会回退规则版，本脚本会把这种情况视为 smoke 失败。
"""

from __future__ import annotations

import sys

from backend.app.llm import CloudLLMClient, CloudLLMError, load_llm_settings
from backend.app.models import (
    ClassroomContext,
    KnowledgeNode,
    KnowledgeTree,
    SourceRef,
    TranscriptSegment,
)
from backend.app.skills import QuizMasterSkill, SummarizerSkill, TodoDetectiveSkill


def main() -> int:
    """执行一次固定课堂样例的真实 provider smoke。"""
    settings = load_llm_settings()
    if not settings.enabled:
        print("LLM smoke skipped: no LLM_API_KEY configured and provider is not local.")
        return 0

    try:
        client = CloudLLMClient(settings)
    except CloudLLMError as exc:
        print(f"LLM smoke failed: {exc}", file=sys.stderr)
        return 1

    context, graph = _fixture()
    skills = [
        ("summary", SummarizerSkill(llm_client=client)),
        ("todos", TodoDetectiveSkill(llm_client=client)),
        ("quiz", QuizMasterSkill(llm_client=client)),
    ]

    failed = False
    for name, skill in skills:
        result = skill.run("lec_llm_smoke", context, graph)
        print(f"\n[{name}]")
        print(result.answer)
        if result.artifact is not None:
            print(f"artifact={result.artifact.type}")
        if result.warnings:
            failed = True
            print("warnings:")
            for warning in result.warnings:
                print(f"- {warning}")

    if failed:
        print(
            "\nLLM smoke failed: at least one skill fell back or returned warnings.",
            file=sys.stderr,
        )
        return 1

    print("\nLLM smoke passed.")
    return 0


def _fixture() -> tuple[ClassroomContext, KnowledgeTree]:
    """构造一段小型课堂资料，覆盖总结、待办和出题所需来源。"""
    segments = [
        TranscriptSegment(
            segment_id="seg_sampling",
            session_id="lec_llm_smoke",
            start_ts=1.0,
            end_ts=6.0,
            text="采样定理说明，只要采样频率大于信号最高频率的两倍，就可以恢复原信号。",
        ),
        TranscriptSegment(
            segment_id="seg_homework",
            session_id="lec_llm_smoke",
            start_ts=20.0,
            end_ts=28.0,
            text="课后作业是完成第三章习题一到三，并复习奈奎斯特采样率。",
        ),
    ]
    context = ClassroomContext(
        session_id="lec_llm_smoke",
        transcript=segments,
    )
    graph = KnowledgeTree(
        session_id="lec_llm_smoke",
        nodes=[
            KnowledgeNode(
                node_id="node_sampling",
                label="采样定理",
                summary="描述连续信号在满足采样频率条件时可以由离散样本恢复。",
                source_refs=[
                    SourceRef(
                        type="segment",
                        id="seg_sampling",
                        ts=1.0,
                    )
                ],
            ),
            KnowledgeNode(
                node_id="node_nyquist",
                label="奈奎斯特采样率",
                summary="采样频率至少为最高频率两倍的条件。",
                source_refs=[
                    SourceRef(
                        type="segment",
                        id="seg_homework",
                        ts=20.0,
                    )
                ],
            ),
        ],
    )
    return context, graph


if __name__ == "__main__":
    raise SystemExit(main())
