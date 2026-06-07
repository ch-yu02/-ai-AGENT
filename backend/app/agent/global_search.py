"""跨课堂历史搜索服务。

Phase 7 的目标是让用户能问“之前哪节课讲过某个知识点”。第一版先做确定性
本地搜索：遍历已保存历史课堂，把每节课转换成 RAG 文档，再用与当前
``QueryService`` 类似的词法评分选出跨 session 命中。

为什么先做本地搜索：
- 不依赖全局向量库或 LlamaIndex 持久化索引，测试稳定。
- 可以复用已有 ``LocalStorage``、``build_session_documents`` 和课堂模型。
- API 契约先稳定下来，后续把内部实现替换为全局 LlamaIndex 索引时，前端不用改。
"""

import re
from dataclasses import dataclass

from backend.app.models import (
    ClassroomContext,
    ImageCapture,
    KnowledgeExtraction,
    KnowledgeTree,
    TimelineItem,
    TranscriptSegment,
)
from backend.app.rag import RagDocument, build_session_documents
from backend.app.storage import LocalStorage

from .schemas import (
    GlobalSearchHit,
    GlobalSearchRequest,
    GlobalSearchResponse,
    GlobalSearchSourceRef,
)


@dataclass(frozen=True)
class _ScoredDocument:
    """内部排序用的文档命中。"""

    score: int
    session_id: str
    title: str
    course: str | None
    document: RagDocument


class GlobalSearchService:
    """在所有已保存历史课堂中搜索课堂资料。"""

    def __init__(self, storage: LocalStorage) -> None:
        self.storage = storage

    def search(self, request: GlobalSearchRequest) -> GlobalSearchResponse:
        """执行跨课堂搜索。

        步骤：
        1. 读取历史课堂摘要列表。
        2. 按可选 course 过滤。
        3. 逐节读取完整历史课堂并转换为 RAG 文档。
        4. 对所有文档按关键词命中得分排序。
        5. 返回带 session 信息的命中列表。

        历史目录损坏时不会让整个搜索失败；损坏 session 会被跳过，并放入
        warnings。这样一个坏历史目录不会拖垮全局搜索。
        """
        query = request.query.strip()
        if not query:
            return GlobalSearchResponse(
                query=request.query,
                answer="请输入要搜索的课堂内容。",
                hits=[],
                warnings=["搜索词不能为空。"],
            )

        summaries = self.storage.list_sessions()
        if request.course:
            expected_course = request.course.strip().lower()
            summaries = [
                summary
                for summary in summaries
                if (summary.session.course or "").lower() == expected_course
            ]

        if not summaries:
            return GlobalSearchResponse(
                query=query,
                answer="没有可搜索的历史课堂。",
                hits=[],
                warnings=["请先结束并保存至少一节课堂。"],
            )

        keywords = self._keywords(query)
        scored: list[_ScoredDocument] = []
        warnings: list[str] = []

        for summary in summaries:
            session_id = summary.session.session_id
            try:
                detail = self.storage.read_session(session_id)
            except (FileNotFoundError, ValueError) as exc:
                warnings.append(f"跳过损坏的历史课堂 {session_id}：{exc}")
                continue

            context = self._context_from_history(session_id, detail.timeline)
            documents = build_session_documents(context, detail.knowledge_graph)
            for document in documents:
                score = self._score(document.text, keywords)
                if score <= 0:
                    continue
                scored.append(
                    _ScoredDocument(
                        score=score,
                        session_id=session_id,
                        title=detail.session.title,
                        course=detail.session.course,
                        document=document,
                    )
                )

        ranked = sorted(scored, key=lambda item: item.score, reverse=True)
        hits = [self._hit(item) for item in ranked[: request.limit]]
        if not hits:
            warnings.append("没有在历史课堂中找到足够依据。")
            return GlobalSearchResponse(
                query=query,
                answer="没有在历史课堂中找到足够依据回答这个问题。",
                hits=[],
                warnings=warnings,
            )

        answer = "我在这些历史课堂中找到了相关内容：\n" + "\n".join(
            f"- {hit.course or '未命名课程'} / {hit.title}: {hit.source_ref.text}"
            for hit in hits[:5]
        )
        return GlobalSearchResponse(
            query=query,
            answer=answer,
            hits=hits,
            warnings=warnings,
        )

    def _context_from_history(
        self,
        session_id: str,
        timeline: list[TimelineItem],
    ) -> ClassroomContext:
        """从历史 timeline 还原 RAG 文档构建所需的 ClassroomContext。

        这和单课堂 Agent 的历史回放逻辑保持一致：历史详情文件中已有完整
        timeline 和 knowledge_graph，但 ``build_session_documents`` 需要按类型
        分组的 transcript / visuals / knowledge_extractions，因此这里做一次轻量
        还原。
        """
        context = ClassroomContext(session_id=session_id, timeline=timeline)
        for item in timeline:
            if item.type == "transcript":
                segment = self._safe_transcript_segment(item.data)
                if segment is not None:
                    context.transcript.append(segment)
            elif item.type == "visual":
                visual = self._safe_image_capture(item.data)
                if visual is not None:
                    context.visuals.append(visual)
            elif item.type == "knowledge":
                extraction = self._safe_knowledge_extraction(item.data)
                if extraction is not None:
                    context.knowledge_extractions.append(extraction)
        return context

    def _safe_transcript_segment(self, data: object) -> TranscriptSegment | None:
        """安全还原字幕片段；坏数据跳过，避免一个坏条目影响全局搜索。"""
        try:
            return TranscriptSegment.model_validate(data)
        except (TypeError, ValueError):
            return None

    def _safe_image_capture(self, data: object) -> ImageCapture | None:
        """安全还原视觉事件；坏数据跳过，避免全局搜索整体失败。"""
        try:
            return ImageCapture.model_validate(data)
        except (TypeError, ValueError):
            return None

    def _safe_knowledge_extraction(self, data: object) -> KnowledgeExtraction | None:
        """安全还原知识抽取事件；坏数据跳过。"""
        try:
            return KnowledgeExtraction.model_validate(data)
        except (TypeError, ValueError):
            return None

    def _hit(self, item: _ScoredDocument) -> GlobalSearchHit:
        """把内部命中文档转换成 API 响应模型。"""
        metadata = item.document.metadata
        ts = metadata.get("ts")
        return GlobalSearchHit(
            session_id=item.session_id,
            title=item.title,
            course=item.course,
            score=item.score,
            source_ref=GlobalSearchSourceRef(
                type=str(metadata.get("type", "timeline")),
                id=str(metadata.get("source_id", "unknown")),
                ts=ts if isinstance(ts, int | float) else None,
                text=item.document.text,
            ),
        )

    def _keywords(self, query: str) -> list[str]:
        """从查询中提取中英文关键词。

        这里和 ``QueryService`` 保持同样的轻量策略，不引入分词依赖。后续全局
        LlamaIndex 索引接入后，这个函数可以只作为 fallback 使用。
        """
        normalized = query.lower()
        stop_phrases = (
            "哪节课",
            "哪一节",
            "之前",
            "讲过",
            "提到",
            "总结",
            "找出",
            "所有",
            "什么",
            "课堂",
        )
        for phrase in stop_phrases:
            normalized = normalized.replace(phrase, " ")

        tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", normalized)
        keywords = [token for token in tokens if token.strip()]
        for token in list(keywords):
            if re.fullmatch(r"[\u4e00-\u9fff]{4,}", token):
                keywords.extend(
                    token[index : index + 4] for index in range(0, len(token) - 3)
                )
        if not keywords:
            keywords = [query]
        return list(dict.fromkeys(keywords))

    def _score(self, text: str, keywords: list[str]) -> int:
        """按命中关键词长度计算相关性分数。"""
        normalized = text.lower()
        return sum(len(keyword) for keyword in keywords if keyword in normalized)


__all__ = ["GlobalSearchService"]
