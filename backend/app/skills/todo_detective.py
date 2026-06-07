"""规则版待办提取技能。

待办提取的目标是从课堂字幕中找出“作业、预习、考试、提交”等提醒。第一版
使用关键词规则，不判断真实截止时间，也不判断教师意图，所以输出统一标记为
候选项，并给出人工确认提示。
"""

from backend.app.models import ClassroomContext, KnowledgeTree

from .schemas import SkillArtifact, SkillResult, SkillSourceRef


class TodoDetectiveSkill:
    """从课堂字幕中提取疑似待办。"""

    _todo_keywords = ("作业", "待办", "预习", "复习", "考试", "提交", "完成", "下节课")

    def run(
        self,
        session_id: str,
        context: ClassroomContext,
        knowledge_graph: KnowledgeTree,
    ) -> SkillResult:
        """返回待办候选列表。

        ``knowledge_graph`` 暂时未参与规则版待办提取，但保留在入参里，是为了让
        所有技能拥有一致调用形态。后续 LLM 版本可以同时参考字幕和知识图谱，
        判断待办与哪个知识点相关。
        """
        matched = [
            segment
            for segment in context.transcript
            if any(keyword in segment.text for keyword in self._todo_keywords)
        ]

        items = [
            {
                "title": segment.text,
                "type": "candidate",
                "due_time": None,
                "source_refs": [
                    {
                        "type": "segment",
                        "id": segment.segment_id,
                        "ts": segment.start_ts,
                        "text": segment.text,
                    }
                ],
                # 固定置信度表示“关键词命中但未经过模型确认”。后续可以由
                # TodoDetectiveSkill 的 LLM 版本给出更细粒度置信度。
                "confidence": 0.6,
            }
            for segment in matched
        ]

        source_refs = [
            SkillSourceRef(
                type="segment",
                id=segment.segment_id,
                ts=segment.start_ts,
                text=segment.text,
            )
            for segment in matched[:6]
        ]

        if items:
            answer = "我找到这些疑似待办或考试相关提醒：\n" + "\n".join(
                f"- {item['title']}" for item in items
            )
            warnings = ["规则版待办提取会保留候选项，请人工确认。"]
        else:
            answer = "没有在课堂资料中找到明确的作业或待办提醒。"
            warnings = ["未匹配到作业、待办、预习、考试等关键词。"]

        return SkillResult(
            answer=answer,
            artifact=SkillArtifact(type="todos", title="待办候选", content=items),
            source_refs=source_refs,
            warnings=warnings,
        )


__all__ = ["TodoDetectiveSkill"]
