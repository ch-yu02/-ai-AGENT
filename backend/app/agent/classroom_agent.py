"""Local rule-based classroom Agent.

The first Agent version is intentionally small and deterministic. It reads only
classroom data already held by EDU-Mate, routes the prompt to a simple skill,
and returns answers with source references. LLM/RAG implementations can replace
the skill methods later without changing the HTTP contract.

当前文件承担的是 Phase 1 的“Agent 外壳”职责：

1. 统一读取课堂数据。
   - 正在录制的课堂优先从 ``ContextManager`` / ``KnowledgeGraphManager`` 读内存。
   - 后端重启后的历史课堂从 ``LocalStorage`` 读保存文件。
2. 调用 ``IntentRouter`` 把 prompt 分到 qa / summary / todos / quiz。
3. 用规则版 skill 生成可演示结果，并尽量返回 ``source_refs``。

重要边界：
- 这里不直接 import FastAPI，也不抛 HTTPException；HTTP 状态码映射留给
  ``backend/app/api/agent.py``。
- 这里不调用云端模型，不需要 API key。后续 LLM/RAG 只应替换 skill 内部实现，
  尽量保持 ``ClassroomAgent.chat()`` 的请求/响应契约不变。
"""

from dataclasses import dataclass

from backend.app.core import ContextManager, ContextNotFoundError
from backend.app.core import KnowledgeGraphManager, KnowledgeGraphNotFoundError
from backend.app.models import (
    ClassroomContext,
    ImageCapture,
    KnowledgeExtraction,
    KnowledgeTree,
    TimelineItem,
    TranscriptSegment,
)
from backend.app.rag import QueryService, RagSourceRef, build_session_documents
from backend.app.storage import LocalStorage

from .intent_router import IntentRouter
from .schemas import (
    AgentArtifact,
    AgentChatRequest,
    AgentChatResponse,
    AgentSourceRef,
    ResolvedAgentIntent,
)


class AgentSessionNotFoundError(Exception):
    """Raised when neither memory nor local history contains a session.

    API 层会把这个领域错误映射为 HTTP 404。这样 Agent 层保持纯业务语义，
    不依赖 FastAPI。
    """


@dataclass(frozen=True)
class ClassroomAgentData:
    """Classroom data snapshot consumed by rule-based skills.

    ``context`` 和 ``knowledge_graph`` 是所有 skill 的统一输入形态。即使数据
    来自历史文件，也会先还原成和内存课堂一致的模型，避免每个 skill 都写
    “内存/历史”两套路由。
    """

    context: ClassroomContext
    """课堂上下文：字幕、视觉内容、知识抽取和统一时间线。"""
    knowledge_graph: KnowledgeTree
    """课堂知识图谱快照。没有图谱时使用空 KnowledgeTree。"""
    data_status: str
    """数据状态，通常是 recording / ended。用于给前端附加 warning。"""


class ClassroomAgent:
    """Answer classroom prompts from in-memory or persisted classroom data.

    这个类是后端 Agent 的主入口。API 路由只需要构造 ``AgentChatRequest`` 并
    调用 ``chat()``；所有读取、路由和规则 skill 都在这里完成。
    """

    # 第一版待办提取只做关键词候选识别。它的结果会带 warning，提醒用户人工
    # 确认；Phase 4 可以替换为更强的 TodoDetectiveSkill。
    _todo_keywords = ("作业", "待办", "预习", "复习", "考试", "提交", "完成", "下节课")

    def __init__(
        self,
        context_manager: ContextManager,
        knowledge_graph_manager: KnowledgeGraphManager,
        storage: LocalStorage,
        intent_router: IntentRouter | None = None,
        query_service: QueryService | None = None,
    ) -> None:
        self.context_manager = context_manager
        self.knowledge_graph_manager = knowledge_graph_manager
        self.storage = storage
        self.intent_router = intent_router or IntentRouter()
        self.query_service = query_service or QueryService()

    def chat(self, request: AgentChatRequest) -> AgentChatResponse:
        """Route one prompt and run the matching local skill.

        调用流程：
        1. ``_load_data()`` 读取课堂资料，并统一成 ``ClassroomAgentData``。
        2. ``IntentRouter`` 解析意图，或尊重前端显式传入的 mode。
        3. 调用对应规则版 skill。
        4. 如果课堂仍在录制，补充 warning，避免用户误以为回答覆盖完整课堂。
        """
        data = self._load_data(request.session_id)
        intent = self.intent_router.route(request.prompt, request.mode)

        if intent == "summary":
            response = self._summary(request.session_id, intent, data)
        elif intent == "todos":
            response = self._todos(request.session_id, intent, data)
        elif intent == "quiz":
            response = self._quiz(request.session_id, intent, data)
        else:
            response = self._qa(request.session_id, intent, request.prompt, data)

        if data.data_status == "recording":
            response.warnings.append("课堂仍在录制中，回答只基于当前已收到的数据。")
        return response

    def _load_data(self, session_id: str) -> ClassroomAgentData:
        """Load classroom data from memory first, then persisted history.

        为什么优先读内存：
        - 正在录制的课堂尚未落盘，只有内存里有最新 transcript / visuals / graph。
        - 结束课堂后 SessionManager 仍保留内存状态；读内存可以避免刚保存后又读盘。

        为什么支持历史回退：
        - 后端重启后内存 session 消失，但 ``data/sessions/{session_id}`` 仍在。
        - Agent 查询历史课时不应该要求重新开始课堂。
        """
        try:
            context = self.context_manager.get_context(session_id)
            try:
                graph = self.knowledge_graph_manager.get_graph(session_id)
            except KnowledgeGraphNotFoundError:
                # 某些测试或未来轻量录制路径可能只创建 context，尚未创建图谱。
                # Agent 仍可基于 transcript 回答，因此这里使用空图谱降级。
                graph = KnowledgeTree(session_id=session_id)
            return ClassroomAgentData(
                context=context,
                knowledge_graph=graph,
                data_status="recording",
            )
        except ContextNotFoundError:
            # 内存没有该课堂时，继续尝试读取已保存历史。这里不立即报错，是为了
            # 支持“后端重启后打开历史课堂再问 Agent”的 Phase 2 场景。
            pass

        try:
            detail = self.storage.read_session(session_id)
        except (FileNotFoundError, ValueError) as exc:
            raise AgentSessionNotFoundError(f"Session not found: {session_id}") from exc

        return ClassroomAgentData(
            context=self._context_from_history(detail.session.session_id, detail.timeline),
            knowledge_graph=detail.knowledge_graph,
            data_status=detail.session.status,
        )

    def _context_from_history(
        self,
        session_id: str,
        timeline: list[TimelineItem],
    ) -> ClassroomContext:
        """Rebuild a ClassroomContext from persisted timeline entries.

        ``LocalStorage.read_session()`` 返回历史详情时只有完整 timeline 和 graph。
        实时内存里的 ``ClassroomContext`` 还包含 transcript / visuals /
        knowledge_extractions 这些分组列表。为了让 skill 不关心数据来源，这里从
        timeline.data 逐条校验并还原分组列表。

        注意：如果历史文件结构损坏，Pydantic 校验会抛错，并最终由 API 层返回
        404/错误响应；不要在这里吞掉坏数据，否则 Agent 会基于不可信内容回答。
        """
        context = ClassroomContext(session_id=session_id, timeline=timeline)
        for item in timeline:
            if item.type == "transcript":
                context.transcript.append(TranscriptSegment.model_validate(item.data))
            elif item.type == "visual":
                context.visuals.append(ImageCapture.model_validate(item.data))
            elif item.type == "knowledge":
                context.knowledge_extractions.append(
                    KnowledgeExtraction.model_validate(item.data)
                )
        return context

    def _summary(
        self,
        session_id: str,
        intent: ResolvedAgentIntent,
        data: ClassroomAgentData,
    ) -> AgentChatResponse:
        """Generate a lightweight classroom summary.

        规则版总结不做抽象改写，只把前几个知识节点和字幕片段整理成提纲。
        这样结果虽然朴素，但完全可追溯、可测试。后续 SummarizerSkill 或
        LLM-backed summary 可以替换这个方法内部实现。
        """
        # 限制条数是为了让第一版输出保持短小，也避免很长课堂把前端消息区撑爆。
        transcript = data.context.transcript[:8]
        nodes = data.knowledge_graph.nodes[:8]
        # 总结主要引用字幕。知识节点通常没有稳定时间戳，后续可用 node.source_refs
        # 映射回 segment/visual 后再补更精确引用。
        source_refs = [self._segment_ref(segment) for segment in transcript[:4]]

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
        return AgentChatResponse(
            session_id=session_id,
            intent=intent,
            answer=answer,
            artifacts=[
                AgentArtifact(type="summary", title="课堂总结", content=answer)
            ],
            source_refs=source_refs,
            warnings=warnings,
        )

    def _todos(
        self,
        session_id: str,
        intent: ResolvedAgentIntent,
        data: ClassroomAgentData,
    ) -> AgentChatResponse:
        """Extract rule-based todo candidates from transcript segments.

        第一版只从字幕中找“作业/待办/预习/考试”等关键词。它不会判断截止时间、
        责任人或是否真的是教师布置，因此统一标记为 candidate，并附带 warning。
        """
        matched = [
            segment
            for segment in data.context.transcript
            if any(keyword in segment.text for keyword in self._todo_keywords)
        ]
        items = [
            {
                "title": segment.text,
                "type": "candidate",
                "due_time": None,
                # 固定置信度表示“关键词命中但未经过模型确认”。Phase 4 可替换为
                # 更细的置信度计算。
                "confidence": 0.6,
            }
            for segment in matched
        ]
        source_refs = [self._segment_ref(segment) for segment in matched[:6]]

        if items:
            answer = "我找到这些疑似待办或考试相关提醒：\n" + "\n".join(
                f"- {item['title']}" for item in items
            )
            warnings: list[str] = ["规则版待办提取会保留候选项，请人工确认。"]
        else:
            answer = "没有在课堂资料中找到明确的作业或待办提醒。"
            warnings = ["未匹配到作业、待办、预习、考试等关键词。"]

        return AgentChatResponse(
            session_id=session_id,
            intent=intent,
            answer=answer,
            artifacts=[
                AgentArtifact(type="todos", title="待办候选", content=items)
            ],
            source_refs=source_refs,
            warnings=warnings,
        )

    def _quiz(
        self,
        session_id: str,
        intent: ResolvedAgentIntent,
        data: ClassroomAgentData,
    ) -> AgentChatResponse:
        """Generate simple self-check questions from graph nodes or transcript.

        优先使用知识图谱节点，因为节点代表课堂里已经被抽取出的概念；如果图谱
        还没有内容，就降级用字幕片段生成短答题，保证 demo 课堂即使只有 ASR
        数据也能看到结果。
        """
        nodes = data.knowledge_graph.nodes[:5]
        questions: list[dict[str, str]] = []
        for index, node in enumerate(nodes, start=1):
            answer = node.summary or f"课堂知识点：{node.label}"
            questions.append(
                {
                    "question": f"{index}. 请解释“{node.label}”的含义或作用。",
                    "type": "short_answer",
                    "answer": answer,
                    "explanation": "题目由课堂知识图谱节点生成。",
                }
            )

        if not questions:
            # 降级路径：没有知识节点时，不让 quiz 直接空掉，而是基于前几条字幕
            # 生成“这段主要讲什么”的短答题。
            for index, segment in enumerate(data.context.transcript[:3], start=1):
                questions.append(
                    {
                        "question": f"{index}. 这段课堂内容主要讲了什么？",
                        "type": "short_answer",
                        "answer": segment.text,
                        "explanation": "题目由课堂字幕片段生成。",
                    }
                )

        source_refs = [self._node_ref(node) for node in nodes[:5]]
        if not source_refs:
            source_refs = [
                self._segment_ref(segment) for segment in data.context.transcript[:3]
            ]

        warnings: list[str] = []
        if not questions:
            warnings.append("还没有知识点或字幕，无法生成自测题。")

        answer = (
            "已根据课堂资料生成自测题：\n"
            + "\n".join(f"- {item['question']}" for item in questions)
            if questions
            else "没有找到足够的课堂资料生成自测题。"
        )
        return AgentChatResponse(
            session_id=session_id,
            intent=intent,
            answer=answer,
            artifacts=[
                AgentArtifact(type="quiz", title="自测题", content=questions)
            ],
            source_refs=source_refs,
            warnings=warnings,
        )

    def _qa(
        self,
        session_id: str,
        intent: ResolvedAgentIntent,
        prompt: str,
        data: ClassroomAgentData,
    ) -> AgentChatResponse:
        """Answer a question through the RAG query service.

        Phase 3 先把 QA 从 Agent 内部搜索迁移到 ``backend.app.rag``。当前
        QueryService 仍是本地关键词检索，但它已经使用“课堂文档 + 查询服务”的
        形态，后续替换为 LlamaIndex 时不需要改 Agent API。
        """
        documents = build_session_documents(data.context, data.knowledge_graph)
        result = self.query_service.query(prompt, documents)

        return AgentChatResponse(
            session_id=session_id,
            intent=intent,
            answer=result.answer,
            source_refs=[self._rag_ref(ref) for ref in result.source_refs],
            warnings=result.warnings,
        )

    def _segment_ref(self, segment) -> AgentSourceRef:
        """Build a source ref for one transcript segment."""
        return AgentSourceRef(
            type="segment",
            id=segment.segment_id,
            ts=segment.start_ts,
            text=segment.text,
        )

    def _visual_ref(self, visual, text: str) -> AgentSourceRef:
        """Build a source ref for one visual capture."""
        return AgentSourceRef(
            type="visual",
            id=visual.image_id,
            ts=visual.capture_ts,
            text=text or visual.image_path,
        )

    def _node_ref(self, node) -> AgentSourceRef:
        """Build a source ref for one knowledge graph node."""
        return AgentSourceRef(
            type="knowledge_node",
            id=node.node_id,
            text=node.summary or node.label,
        )

    def _rag_ref(self, ref: RagSourceRef) -> AgentSourceRef:
        """Convert a RAG-layer source reference to the Agent API schema."""
        ref_type = (
            ref.type
            if ref.type in {"segment", "visual", "knowledge_node"}
            else "timeline"
        )
        return AgentSourceRef(type=ref_type, id=ref.id, ts=ref.ts, text=ref.text)


__all__ = ["AgentSessionNotFoundError", "ClassroomAgent", "ClassroomAgentData"]
