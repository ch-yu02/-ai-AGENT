"""skills 层复用的 LLM 辅助函数。

这里不放具体技能逻辑，只处理三件事：
1. 需要时根据环境变量创建云端 LLM 客户端；
2. 把课堂上下文压缩成适合放进 prompt 的简短材料；
3. 对模型返回的结构化 JSON 做最小防御式校验。
"""

from typing import Any, Protocol

from backend.app.llm import CloudLLMClient, CloudLLMError, load_llm_settings
from backend.app.models import ClassroomContext, KnowledgeTree

from .schemas import SkillSourceRef


class JsonLLMClient(Protocol):
    """skills 需要的最小 LLM 能力协议。

    测试可以传入 fake client；生产环境传 ``CloudLLMClient``。这样 skills 不
    依赖具体 HTTP 实现，也不会在单元测试里误触发真实网络。
    """

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """返回 JSON object。"""


def build_default_llm_client() -> JsonLLMClient | None:
    """按环境变量创建默认 LLM client。

    没有 ``LLM_API_KEY`` 时返回 None，表示技能应继续使用规则版实现。
    """
    settings = load_llm_settings()
    if not settings.enabled:
        return None
    return CloudLLMClient(settings)


def classroom_brief(
    context: ClassroomContext,
    knowledge_graph: KnowledgeTree,
    *,
    max_segments: int = 12,
    max_nodes: int = 10,
) -> str:
    """把课堂资料压缩成稳定、可引用的文本材料。

    LLM 不能直接拿完整长课堂内容。第一版先保守截取前若干条字幕和知识节点，
    每条都带稳定 ID，方便模型把结果里的 ``source_refs`` 指回原始课堂资料。
    """
    lines = [f"session_id: {context.session_id}", "", "transcript:"]

    if context.transcript:
        for segment in context.transcript[:max_segments]:
            lines.append(
                f"- id={segment.segment_id}; ts={segment.start_ts:.2f}; text={segment.text}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "knowledge_nodes:"])
    if knowledge_graph.nodes:
        for node in knowledge_graph.nodes[:max_nodes]:
            summary = node.summary or ""
            lines.append(f"- id={node.node_id}; label={node.label}; summary={summary}")
    else:
        lines.append("- none")

    return "\n".join(lines)


def source_refs_from_payload(
    items: object,
    context: ClassroomContext,
    knowledge_graph: KnowledgeTree,
) -> list[SkillSourceRef]:
    """把 LLM JSON 里的 source_refs 转为技能层引用。

    为了防止模型返回不存在的 ID，这里只接受能在当前课堂资料中查到的引用。
    """
    segments = {segment.segment_id: segment for segment in context.transcript}
    nodes = {node.node_id: node for node in knowledge_graph.nodes}
    refs: list[SkillSourceRef] = []
    if not isinstance(items, list):
        return refs

    for item in items:
        if not isinstance(item, dict):
            continue
        ref_type = str(item.get("type", ""))
        ref_id = str(item.get("id", ""))
        if ref_type == "segment" and ref_id in segments:
            segment = segments[ref_id]
            refs.append(
                SkillSourceRef(
                    type="segment",
                    id=segment.segment_id,
                    ts=segment.start_ts,
                    text=segment.text,
                )
            )
        elif ref_type == "knowledge_node" and ref_id in nodes:
            node = nodes[ref_id]
            refs.append(
                SkillSourceRef(
                    type="knowledge_node",
                    id=node.node_id,
                    text=node.summary or node.label,
                )
            )

    return refs


def require_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """读取 JSON object 中的 list[dict] 字段。"""
    value = payload.get(key)
    if not isinstance(value, list):
        raise CloudLLMError(f"LLM output missing list field: {key}")

    items = [item for item in value if isinstance(item, dict)]
    if len(items) != len(value):
        raise CloudLLMError(f"LLM output field {key} must contain objects")
    return items


def require_string(payload: dict[str, Any], key: str) -> str:
    """读取 JSON object 中的非空字符串字段。"""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CloudLLMError(f"LLM output missing string field: {key}")
    return value.strip()
