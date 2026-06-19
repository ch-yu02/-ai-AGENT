"""跨课堂历史搜索服务。

Phase 7 的目标是让用户能问“之前哪节课讲过某个知识点”。第一版先做确定性
本地搜索：遍历已保存历史课堂，把每节课转换成 RAG 文档，再用与当前
``QueryService`` 类似的词法评分选出跨 session 命中。

为什么先做本地搜索：
- 不依赖全局向量库或 LlamaIndex 持久化索引，测试稳定。
- 可以复用已有 ``LocalStorage``、``build_session_documents`` 和课堂模型。
- API 契约先稳定下来，后续把内部实现替换为全局 LlamaIndex 索引时，前端不用改。
"""

import os
import re
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from backend.app import prompts
from backend.app.llm import CloudLLMError
from backend.app.models import (
    ClassroomContext,
    ImageCapture,
    KnowledgeExtraction,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeTree,
    TimelineItem,
    TranscriptSegment,
    utc_now_iso,
)
from backend.app.rag import (
    GlobalIndexHit,
    GlobalLlamaIndexService,
    RagDocument,
    build_session_documents,
)
from backend.app.rag.query_service import compact_source_ref_text
from backend.app.skills.llm_support import (
    JsonLLMClient,
    build_default_llm_client,
    require_string,
)
from backend.app.storage import LocalStorage

from .schemas import (
    CourseKnowledgeTreeResponse,
    CourseListResponse,
    CourseSummary,
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


@dataclass(frozen=True)
class _GlobalDocumentSnapshot:
    """Cached cross-classroom documents for global search."""

    fingerprint: str
    records: list[dict]
    documents: list[RagDocument]
    owners: list[dict]


class GlobalSearchService:
    """在所有已保存历史课堂中搜索课堂资料。"""

    def __init__(
        self,
        storage: LocalStorage,
        global_index_service: GlobalLlamaIndexService | None = None,
        llm_client: JsonLLMClient | None = None,
    ) -> None:
        self.storage = storage
        self._global_index_service = global_index_service
        self._llm_client = llm_client
        self._documents_cache: _GlobalDocumentSnapshot | None = None

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
        filtered_summaries = self._filter_summaries(summaries, request)

        if not filtered_summaries:
            return GlobalSearchResponse(
                query=query,
                answer="没有可搜索的历史课堂。",
                hits=[],
                warnings=["请先结束并保存至少一节课堂。"],
            )

        warnings: list[str] = []
        snapshot = self._global_document_snapshot(summaries, warnings)
        allowed_session_ids = {
            summary.session.session_id for summary in filtered_summaries
        }
        global_index_documents, global_rag_documents, document_owners = (
            self._filter_snapshot(snapshot, allowed_session_ids)
        )

        keywords = self._keywords(query)
        scored: list[_ScoredDocument] = []
        for document, owner in zip(global_rag_documents, document_owners, strict=False):
            score = self._score(document.text, keywords)
            if score <= 0:
                continue
            scored.append(
                _ScoredDocument(
                    score=score,
                    session_id=owner["session_id"],
                    title=owner["title"],
                    course=owner["course"],
                    document=document,
                )
            )

        vector_response = self._search_global_index(
            query=query,
            records=global_index_documents,
            documents=global_rag_documents,
            limit=request.limit,
            warnings=warnings,
        )
        if vector_response is not None:
            return vector_response

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

    def review(self, request: GlobalSearchRequest) -> GlobalSearchResponse:
        """Answer a post-class review question from cross-classroom sources."""
        response = self.search(request)
        if not response.hits:
            return response

        client = self._client_or_none()
        if client is None:
            response.warnings.append("未配置 LLM，复习问答已返回跨课堂检索摘要。")
            return response

        try:
            payload = client.complete_json(
                system_prompt=prompts.history_review_qa_system_prompt(),
                user_prompt=prompts.history_review_qa_user_prompt(
                    student_prompt=request.query,
                    hits=[
                        {
                            "session_id": hit.session_id,
                            "title": hit.title,
                            "course": hit.course,
                            "type": hit.source_ref.type,
                            "id": hit.source_ref.id,
                            "ts": hit.source_ref.ts,
                            "text": hit.source_ref.text,
                        }
                        for hit in response.hits[: request.limit]
                    ],
                ),
                temperature=0.1,
            )
            response.answer = require_string(payload, "answer")
        except (CloudLLMError, KeyError, TypeError, ValueError) as exc:
            response.warnings.append(f"复习问答模型生成失败，已退回检索摘要：{exc}")
        return response

    def list_courses(self) -> CourseListResponse:
        """Aggregate saved classroom history by course."""
        warnings: list[str] = []
        summaries = self.storage.list_sessions()
        grouped: dict[str, dict[str, Any]] = {}

        for summary in summaries:
            course = _course_name(summary.session.course)
            bucket = grouped.setdefault(
                course,
                {
                    "course": course,
                    "sessions": [],
                    "node_keys": set(),
                    "edge_keys": set(),
                },
            )
            bucket["sessions"].append(summary.session)
            try:
                detail = self.storage.read_session(summary.session.session_id)
            except (FileNotFoundError, ValueError) as exc:
                warnings.append(f"跳过损坏的历史课堂 {summary.session.session_id}：{exc}")
                continue
            bucket["node_keys"].update(
                _normalize_label(node.label) for node in detail.knowledge_graph.nodes
            )
            bucket["edge_keys"].update(
                _edge_key(detail.knowledge_graph, edge)
                for edge in detail.knowledge_graph.edges
            )

        courses: list[CourseSummary] = []
        for bucket in grouped.values():
            sessions = sorted(
                bucket["sessions"],
                key=lambda session: session.start_time,
                reverse=True,
            )
            latest = sessions[0] if sessions else None
            courses.append(
                CourseSummary(
                    course=bucket["course"],
                    session_count=len(sessions),
                    latest_session_id=latest.session_id if latest else None,
                    latest_title=latest.title if latest else None,
                    latest_start_time=latest.start_time if latest else None,
                    node_count=len(bucket["node_keys"]),
                    edge_count=len(bucket["edge_keys"]),
                )
            )

        return CourseListResponse(
            courses=sorted(
                courses,
                key=lambda item: item.latest_start_time or "",
                reverse=True,
            ),
            warnings=warnings,
        )

    def merged_course_tree(self, course: str) -> CourseKnowledgeTreeResponse:
        """Merge saved knowledge graphs for one course into a lightweight tree."""
        expected = _course_name(course)
        warnings: list[str] = []
        summaries = [
            summary
            for summary in self.storage.list_sessions()
            if _course_name(summary.session.course) == expected
        ]
        merged = KnowledgeTree(session_id=f"course_{_safe_slug(expected)}")
        node_by_key: dict[str, KnowledgeNode] = {}
        edge_keys: set[tuple[str, str, str]] = set()

        for summary in summaries:
            try:
                detail = self.storage.read_session(summary.session.session_id)
            except (FileNotFoundError, ValueError) as exc:
                warnings.append(f"跳过损坏的历史课堂 {summary.session.session_id}：{exc}")
                continue
            source_node_map: dict[str, str] = {}
            for node in detail.knowledge_graph.nodes:
                key = _normalize_label(node.label)
                existing = node_by_key.get(key)
                if existing is None:
                    copied = node.model_copy(deep=True)
                    copied.node_id = f"course_node_{_safe_slug(node.label)}"
                    merged.nodes.append(copied)
                    node_by_key[key] = copied
                    existing = copied
                else:
                    _merge_node(existing, node)
                source_node_map[node.node_id] = existing.node_id

            for edge in detail.knowledge_graph.edges:
                source = source_node_map.get(edge.source)
                target = source_node_map.get(edge.target)
                if source is None or target is None or source == target:
                    continue
                key = (source, target, edge.relation)
                if key in edge_keys:
                    continue
                edge_keys.add(key)
                copied_edge = edge.model_copy(deep=True)
                copied_edge.edge_id = (
                    f"course_edge_{_safe_slug(source + '_' + edge.relation + '_' + target)}"
                )
                copied_edge.source = source
                copied_edge.target = target
                merged.edges.append(copied_edge)

        _recompute_course_tree_roots(merged)
        if merged.nodes or merged.edges:
            merged.version = 1
            merged.updated_at = utc_now_iso()
        return CourseKnowledgeTreeResponse(
            course=expected,
            session_count=len(summaries),
            knowledge_graph=merged,
            warnings=warnings,
        )

    def rebuild_global_index(self, *, build_llamaindex: bool = False) -> dict[str, object]:
        """Rebuild the auditable global index snapshot and optional vector index.

        This method backs the CLI command. It always writes
        ``data/indexes/global/documents.json`` so lexical/global search has a
        fresh source-of-truth snapshot. When ``build_llamaindex`` is true, it
        also forces a persisted LlamaIndex rebuild and returns the manifest.
        Broken history sessions are skipped and reported as warnings, matching
        the search path's tolerance.
        """
        warnings: list[str] = []
        summaries = self.storage.list_sessions()
        snapshot = self._global_document_snapshot(
            summaries,
            warnings,
            force=True,
            persist=False,
        )
        records = snapshot.records
        documents = snapshot.documents
        documents_path = self.storage.save_global_search_index(records)
        result: dict[str, object] = {
            "document_count": len(records),
            "documents_path": str(documents_path),
            "warnings": warnings,
            "llamaindex": {
                "enabled": build_llamaindex,
                "status": "skipped",
            },
        }

        if build_llamaindex:
            service = self._global_index_service or GlobalLlamaIndexService(
                index_root=self.storage.global_index_dir(),
            )
            try:
                manifest = service.rebuild(records=records, documents=documents)
            except Exception as exc:  # noqa: BLE001 - CLI reports optional failure.
                result["llamaindex"] = {
                    "enabled": True,
                    "status": "failed",
                    "warning": str(exc),
                }
            else:
                result["llamaindex"] = {
                    "enabled": True,
                    "status": "persisted",
                    "manifest": manifest,
                }

        return result

    def _filter_summaries(
        self,
        summaries,
        request: GlobalSearchRequest,
    ) -> list:
        """Apply request filters to history summaries."""
        filtered = list(summaries)
        if request.course:
            expected_course = request.course.strip().lower()
            filtered = [
                summary
                for summary in filtered
                if (summary.session.course or "").lower() == expected_course
            ]
        if request.date_from or request.date_to:
            filtered = [
                summary
                for summary in filtered
                if self._is_in_date_range(
                    summary.session.start_time,
                    request.date_from,
                    request.date_to,
                )
            ]
        return filtered

    def _global_document_snapshot(
        self,
        summaries,
        warnings: list[str],
        *,
        force: bool = False,
        persist: bool = True,
    ) -> _GlobalDocumentSnapshot:
        """Return cached global documents, rebuilding only when history changed."""
        fingerprint = self._history_fingerprint(summaries)
        if (
            not force
            and self._documents_cache is not None
            and self._documents_cache.fingerprint == fingerprint
        ):
            return self._documents_cache

        records, documents, owners = self._build_global_documents(summaries, warnings)
        snapshot = _GlobalDocumentSnapshot(
            fingerprint=fingerprint,
            records=records,
            documents=documents,
            owners=owners,
        )
        if persist:
            self.storage.save_global_search_index(records)
        self._documents_cache = snapshot
        return snapshot

    def _filter_snapshot(
        self,
        snapshot: _GlobalDocumentSnapshot,
        allowed_session_ids: set[str],
    ) -> tuple[list[dict], list[RagDocument], list[dict]]:
        """Filter cached global documents to a request's session subset."""
        records: list[dict] = []
        documents: list[RagDocument] = []
        owners: list[dict] = []
        for record, document, owner in zip(
            snapshot.records,
            snapshot.documents,
            snapshot.owners,
            strict=False,
        ):
            if owner["session_id"] not in allowed_session_ids:
                continue
            records.append(record)
            documents.append(document)
            owners.append(owner)
        return records, documents, owners

    def _history_fingerprint(self, summaries) -> str:
        """Create a cheap fingerprint for saved sessions and search inputs."""
        entries: list[dict[str, object]] = []
        for summary in sorted(
            summaries,
            key=lambda item: item.session.session_id,
        ):
            session_id = summary.session.session_id
            session_dir = self.storage.session_dir(session_id)
            entries.append(
                {
                    "session": summary.session.model_dump(mode="json"),
                    "event_count": summary.event_count,
                    "files": {
                        name: self._file_signature(session_dir / filename)
                        for name, filename in {
                            "metadata": "metadata.json",
                            "timeline": "timeline.json",
                            "knowledge_graph": "knowledge_graph.json",
                            "structured_notes": "structured_notes.md",
                        }.items()
                    },
                }
            )
        encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _file_signature(self, path) -> dict[str, object]:
        """Return size/mtime data for cache invalidation."""
        try:
            stat = path.stat()
        except OSError:
            return {"exists": False}
        return {
            "exists": True,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    def _build_global_documents(
        self,
        summaries,
        warnings: list[str],
    ) -> tuple[list[dict], list[RagDocument], list[dict]]:
        """Read saved sessions and produce global-search documents.

        The returned ``records`` are written to ``documents.json`` for auditing.
        The returned ``RagDocument`` objects are used by lexical scoring and
        optional LlamaIndex. ``owners`` mirrors the RAG document list so search
        can recover session title/course without reparsing metadata.
        """
        records: list[dict] = []
        documents: list[RagDocument] = []
        owners: list[dict] = []

        for summary in summaries:
            session_id = summary.session.session_id
            try:
                detail = self.storage.read_session(session_id)
            except (FileNotFoundError, ValueError) as exc:
                warnings.append(f"跳过损坏的历史课堂 {session_id}：{exc}")
                continue

            context = self._context_from_history(session_id, detail.timeline)
            session_documents = [
                self._enrich_global_document(
                    session_id=session_id,
                    title=detail.session.title,
                    course=detail.session.course,
                    document=document,
                )
                for document in build_session_documents(
                    context,
                    detail.knowledge_graph,
                    structured_notes_markdown=detail.structured_notes_markdown,
                )
            ]
            for document in session_documents:
                documents.append(document)
                owners.append(
                    {
                        "session_id": session_id,
                        "title": detail.session.title,
                        "course": detail.session.course,
                    }
                )
                records.append(
                    self._global_index_record(
                        session_id=session_id,
                        title=detail.session.title,
                        course=detail.session.course,
                        document=document,
                    )
                )
        return records, documents, owners

    def _search_global_index(
        self,
        *,
        query: str,
        records: list[dict],
        documents: list[RagDocument],
        limit: int,
        warnings: list[str],
    ) -> GlobalSearchResponse | None:
        """按需使用全局 LlamaIndex 索引查询。

        只有 ``GLOBAL_SEARCH_BACKEND=llamaindex`` 时才会进入该路径。失败或无命中
        都返回 None，让调用方继续使用稳定的词法搜索。这样可选依赖、真实
        embedding provider 或本地模型配置不完整时，不会影响默认功能。
        """
        backend = os.getenv("GLOBAL_SEARCH_BACKEND", "lexical").strip().lower()
        if backend != "llamaindex":
            return None

        try:
            service = self._global_index_service or GlobalLlamaIndexService(
                index_root=self.storage.global_index_dir(),
            )
            index_hits = service.search(
                query=query,
                records=records,
                documents=documents,
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001 - 可选依赖失败必须回退词法搜索。
            warnings.append(f"全局 LlamaIndex 索引不可用，已回退词法搜索：{exc}")
            return None

        if not index_hits:
            warnings.append("全局 LlamaIndex 索引未返回命中，已回退词法搜索。")
            return None

        hits = [self._hit_from_global_index(item) for item in index_hits[:limit]]
        answer = "我在全局向量索引中找到了相关历史课堂内容：\n" + "\n".join(
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
                text=compact_source_ref_text(
                    item.document.text,
                    metadata=metadata,
                ),
            ),
        )

    def _hit_from_global_index(self, item: GlobalIndexHit) -> GlobalSearchHit:
        """把全局向量索引命中转换为 API 响应模型。"""
        return GlobalSearchHit(
            session_id=item.session_id,
            title=item.title,
            course=item.course,
            score=item.score,
            source_ref=GlobalSearchSourceRef(
                type=item.source_type,
                id=item.source_id,
                ts=item.ts,
                text=compact_source_ref_text(item.text),
            ),
        )

    def _client_or_none(self) -> JsonLLMClient | None:
        if self._llm_client is not None:
            return self._llm_client
        return build_default_llm_client()

    def _enrich_global_document(
        self,
        *,
        session_id: str,
        title: str,
        course: str | None,
        document: RagDocument,
    ) -> RagDocument:
        """给 RAG 文档补充跨课堂搜索需要的课堂元信息。

        单节课 RAG 文档只需要知道来源对象；全局索引还必须能从命中直接恢复
        ``session_id``、课堂标题和课程名。因此这里在进入全局索引前补充 metadata，
        不改变 ``build_session_documents`` 的通用职责。
        """
        metadata = {
            **document.metadata,
            "session_id": session_id,
            "title": title,
            "course": course,
        }
        return document.model_copy(update={"metadata": metadata})

    def _global_index_record(
        self,
        *,
        session_id: str,
        title: str,
        course: str | None,
        document: RagDocument,
    ) -> dict:
        """把一条 RAG 文档保存为全局索引快照记录。"""
        return {
            "session_id": session_id,
            "title": title,
            "course": course,
            "text": document.text,
            "metadata": document.metadata,
        }

    def _is_in_date_range(
        self,
        start_time: str,
        date_from: str | None,
        date_to: str | None,
    ) -> bool:
        """按 YYYY-MM-DD 字符串过滤课堂开始日期。

        LectureSession.start_time 是 ISO 字符串，前 10 位就是日期。这里不做时区
        转换，保证和后端保存的本地时间表示一致。
        """
        session_date = start_time[:10]
        if date_from and session_date < date_from:
            return False
        if date_to and session_date > date_to:
            return False
        return True

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


def _course_name(course: str | None) -> str:
    value = (course or "").strip()
    return value or "未命名课程"


def _normalize_label(label: str) -> str:
    return re.sub(r"[\s\-_（）()《》“”'\"，,。:：]+", "", label.strip().lower())


def _safe_slug(value: str) -> str:
    return (
        re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", value.strip()).strip("_")
        or "unknown"
    )


def _edge_key(graph: KnowledgeTree, edge: KnowledgeEdge) -> tuple[str, str, str]:
    nodes = {node.node_id: node for node in graph.nodes}
    source = nodes.get(edge.source)
    target = nodes.get(edge.target)
    return (
        _normalize_label(source.label if source else edge.source),
        _normalize_label(target.label if target else edge.target),
        edge.relation,
    )


def _merge_node(target: KnowledgeNode, source: KnowledgeNode) -> None:
    if source.summary and source.summary != target.summary:
        target.summary = source.summary if not target.summary else target.summary
    if source.importance is not None:
        target.importance = max(target.importance or 0.0, source.importance)
    existing_refs = {(ref.type, ref.id, ref.ts) for ref in target.source_refs}
    for ref in source.source_refs:
        key = (ref.type, ref.id, ref.ts)
        if key in existing_refs:
            continue
        target.source_refs.append(ref)
        existing_refs.add(key)
    target.source_refs = target.source_refs[-3:]


def _recompute_course_tree_roots(graph: KnowledgeTree) -> None:
    targets = {edge.target for edge in graph.edges}
    graph.root_nodes = [
        node.node_id for node in graph.nodes if node.node_id not in targets
    ]
    for node in graph.nodes:
        node.level = 0 if node.node_id in graph.root_nodes else 1


__all__ = ["GlobalSearchService"]
