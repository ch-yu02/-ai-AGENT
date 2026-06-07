"""本地规则版课堂 Agent。

第一版 Agent 刻意保持小而确定：只读取 EDU-Mate 已经持有的课堂数据，根据
prompt 路由到简单技能，并返回带来源引用的答案。后续接入 LLM/RAG 时，可以
替换各个技能内部实现，但尽量不改变对外 HTTP 契约。

当前文件承担的是 Phase 1 的“Agent 外壳”职责：

1. 统一读取课堂数据。
   - 正在录制的课堂优先从 ``ContextManager`` / ``KnowledgeGraphManager`` 读内存。
   - 后端重启后的历史课堂从 ``LocalStorage`` 读保存文件。
2. 调用 ``IntentRouter`` 把 prompt 分到 qa / summary / todos / quiz。
3. 用规则版技能生成可演示结果，并尽量返回 ``source_refs``。

重要边界：
- 这里不直接 import FastAPI，也不抛 HTTPException；HTTP 状态码映射留给
  ``backend/app/api/agent.py``。
- 这里不调用云端模型，不需要 API key。后续 LLM/RAG 只应替换技能内部实现，
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
from backend.app.skills import (
    QaSkill,
    QuizMasterSkill,
    SkillResult,
    SkillSourceRef,
    SummarizerSkill,
    TodoDetectiveSkill,
)
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
    """内存和本地历史中都找不到课堂时抛出。

    API 层会把这个领域错误映射为 HTTP 404。这样 Agent 层保持纯业务语义，
    不依赖 FastAPI。
    """


@dataclass(frozen=True)
class ClassroomAgentData:
    """规则版技能消费的课堂数据快照。

    ``context`` 和 ``knowledge_graph`` 是所有技能的统一输入形态。即使数据
    来自历史文件，也会先还原成和内存课堂一致的模型，避免每个技能都写
    “内存/历史”两套路由。
    """

    context: ClassroomContext
    """课堂上下文：字幕、视觉内容、知识抽取和统一时间线。"""
    knowledge_graph: KnowledgeTree
    """课堂知识图谱快照。没有图谱时使用空 KnowledgeTree。"""
    data_status: str
    """数据状态，通常是 recording / ended。用于给前端附加提示。"""


class ClassroomAgent:
    """基于内存课堂或已保存历史课堂回答用户 prompt。

    这个类是后端 Agent 的主入口。API 路由只需要构造 ``AgentChatRequest`` 并
    调用 ``chat()``；所有读取、路由和规则技能都在这里完成。
    """

    def __init__(
        self,
        context_manager: ContextManager,
        knowledge_graph_manager: KnowledgeGraphManager,
        storage: LocalStorage,
        intent_router: IntentRouter | None = None,
        summarizer_skill: SummarizerSkill | None = None,
        todo_skill: TodoDetectiveSkill | None = None,
        quiz_skill: QuizMasterSkill | None = None,
        qa_skill: QaSkill | None = None,
    ) -> None:
        self.context_manager = context_manager
        self.knowledge_graph_manager = knowledge_graph_manager
        self.storage = storage
        self.intent_router = intent_router or IntentRouter()
        self.summarizer_skill = summarizer_skill or SummarizerSkill()
        self.todo_skill = todo_skill or TodoDetectiveSkill()
        self.quiz_skill = quiz_skill or QuizMasterSkill()
        self.qa_skill = qa_skill or QaSkill()

    def chat(self, request: AgentChatRequest) -> AgentChatResponse:
        """路由一次 prompt，并运行对应的本地技能。

        调用流程：
        1. ``_load_data()`` 读取课堂资料，并统一成 ``ClassroomAgentData``。
        2. ``IntentRouter`` 解析意图，或尊重前端显式传入的 mode。
        3. 调用对应规则版技能。
        4. 如果课堂仍在录制，补充提示，避免用户误以为回答覆盖完整课堂。
        """
        data = self._load_data(request.session_id)
        intent = self.intent_router.route(request.prompt, request.mode)

        if intent == "summary":
            result = self.summarizer_skill.run(
                request.session_id,
                data.context,
                data.knowledge_graph,
            )
        elif intent == "todos":
            result = self.todo_skill.run(
                request.session_id,
                data.context,
                data.knowledge_graph,
            )
        elif intent == "quiz":
            result = self.quiz_skill.run(
                request.session_id,
                data.context,
                data.knowledge_graph,
            )
        else:
            result = self.qa_skill.run(
                request.session_id,
                request.prompt,
                data.context,
                data.knowledge_graph,
            )

        response = self._response_from_skill_result(request.session_id, intent, result)
        self._save_artifacts_when_possible(request.session_id, response)

        if data.data_status == "recording":
            response.warnings.append("课堂仍在录制中，回答只基于当前已收到的数据。")
        return response

    def _load_data(self, session_id: str) -> ClassroomAgentData:
        """优先从内存读取课堂数据，内存未命中时回退读取本地历史。

        为什么优先读内存：
        - 正在录制的课堂尚未落盘，只有内存里有最新字幕、视觉内容和图谱。
        - 结束课堂后 SessionManager 仍保留内存状态；读内存可以避免刚保存后又读盘。

        为什么支持历史回退：
        - 后端重启后内存课堂消失，但 ``data/sessions/{session_id}`` 仍在。
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
        """根据已保存的 timeline 条目重建 ClassroomContext。

        ``LocalStorage.read_session()`` 返回历史详情时只有完整时间线和图谱。
        实时内存里的 ``ClassroomContext`` 还包含字幕、视觉内容、
        knowledge_extractions 这些分组列表。为了让技能不关心数据来源，这里从
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

    def _response_from_skill_result(
        self,
        session_id: str,
        intent: ResolvedAgentIntent,
        result: SkillResult,
    ) -> AgentChatResponse:
        """把技能层结果转换成 Agent API 响应。

        这个转换点是技能层和 API 层之间的边界。技能层返回 dataclass，方便被
        批处理或未来独立技能接口复用；Agent API 继续返回 Pydantic 模型，保证
        HTTP 序列化和前端契约稳定。
        """
        artifacts = []
        if result.artifact is not None:
            artifacts.append(
                AgentArtifact(
                    type=result.artifact.type,
                    title=result.artifact.title,
                    content=result.artifact.content,
                )
            )
        return AgentChatResponse(
            session_id=session_id,
            intent=intent,
            answer=result.answer,
            artifacts=artifacts,
            source_refs=[self._skill_ref(ref) for ref in result.source_refs],
            warnings=list(result.warnings),
        )

    def _skill_ref(self, ref: SkillSourceRef) -> AgentSourceRef:
        """把技能层来源引用转换成 Agent API 响应模型。"""
        ref_type = (
            ref.type
            if ref.type in {"segment", "visual", "knowledge_node"}
            else "timeline"
        )
        return AgentSourceRef(type=ref_type, id=ref.id, ts=ref.ts, text=ref.text)

    def _save_artifacts_when_possible(
        self,
        session_id: str,
        response: AgentChatResponse,
    ) -> None:
        """在历史课堂目录存在时保存本次 Agent 生成的结构化产物。

        这里是“用户主动生成”的保存入口，和结束课堂时的自动产物入口互补：
        - 结束课堂 API 会自动生成 summary.md / todos.json；
        - 用户在 AgentPanel 中点击“生成自测”或输入出题类 prompt 时，才会
          经过这里保存 quiz.json；
        - 如果用户手动让 Agent 重新总结或重新提取待办，也会通过这里覆盖
          对应的 summary.md / todos.json，让历史课堂里的产物保持最新。

        Agent 不强制要求课堂已经落盘。正在录制的课堂通常还没有
        ``data/sessions/{session_id}`` 目录，此时跳过保存，仍然把结果返回给
        前端；已结束并保存过的历史课堂才写入本地文件，避免产生缺少
        metadata.json 的半成品历史目录。
        """
        if not response.artifacts or not self.storage.session_exists(session_id):
            return

        self.storage.save_agent_artifacts(
            session_id,
            [artifact.model_dump() for artifact in response.artifacts],
        )


__all__ = ["AgentSessionNotFoundError", "ClassroomAgent", "ClassroomAgentData"]
