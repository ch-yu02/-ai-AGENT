"""规则版课堂总结技能。

第一版总结技能不调用 LLM，也不做复杂抽象改写。它把课堂知识节点和前几条
字幕整理成稳定提纲，优点是可测试、可追溯、无 API key 依赖。

后续接入 Cloud LLM 时，可以保留 ``SummarizerSkill.run()`` 的输入输出形态，
只替换方法内部的生成逻辑。
"""

from backend.app.models import ClassroomContext, KnowledgeTree

from .schemas import SkillArtifact, SkillResult, SkillSourceRef


class SummarizerSkill:
    """生成课堂重点总结。"""

    def run(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """根据课堂上下文和知识图谱生成总结。

        策略说明：
        - 优先列出知识图谱中的前几个知识节点，帮助用户看到概念清单。
        - 再补充前几条字幕原文，避免规则版总结过度“发挥”。
        - 来源引用主要使用字幕片段；知识节点目前缺少稳定时间戳，后续可以通过
          node.source_refs 继续映射回字幕或视觉来源。
        """
        transcript = context.transcript[:8]
        nodes = knowledge_graph.nodes[:8]
        source_refs = [
            SkillSourceRef(
                type="segment",
                id=segment.segment_id,
                ts=segment.start_ts,
                text=segment.text,
            )
            for segment in transcript[:4]
        ]

        points: list[str] = []
        if nodes:
            points.append("知识点：" + "、".join(node.label for node in nodes))
        points.extend(segment.text for segment in transcript[:5] if segment.text)

        warnings: list[str] = []
        if not points:
            warnings.append("还没有可用于总结的课堂内容。")

        answer = (
            "这节课目前可归纳为：\n"
            + "\n".join(f"- {point}" for point in points)
            if points
            else "没有找到足够的课堂内容生成总结。"
        )

        return SkillResult(
            answer=answer,
            artifact=SkillArtifact(
                type="summary",
                title="课堂总结",
                content=answer,
            ),
            source_refs=source_refs,
            warnings=warnings,
        )


__all__ = ["SummarizerSkill"]
