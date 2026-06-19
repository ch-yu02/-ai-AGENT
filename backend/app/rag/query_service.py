"""课堂 RAG 文档的本地检索服务。

本模块是接入 LlamaIndex 前的无依赖过渡层。它对外暴露“输入 prompt 和文档，
返回回答与来源引用”的查询接口；内部目前使用确定性的关键词检索，避免在
MVP 阶段引入向量库、本地 embedding 或云端模型。

后续接入 LlamaIndex 时，尽量保持 ``QueryService.query()`` 的入参和返回
结构不变，只把内部实现替换为索引构建、query engine 调用和引用映射。
"""

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .documents import RagDocument

MAX_SOURCE_REF_COUNT = 3
SOURCE_PREVIEW_CHARS = 240


@dataclass(frozen=True)
class RagSourceRef:
    """检索层返回的轻量来源引用，不绑定 Agent API schema。

    RAG 层不直接依赖 ``backend.app.agent.schemas.AgentSourceRef``，是为了避免
    Agent 层和 RAG 层互相 import 形成环。Agent 会在边界处把这个对象转换成
    对外 API 响应里的 ``AgentSourceRef``。
    """

    type: str
    id: str
    text: str
    ts: float | None = None


@dataclass(frozen=True)
class QueryResult:
    """QueryService 的查询结果。"""

    answer: str
    source_refs: list[RagSourceRef]
    warnings: list[str]


class QueryService:
    """使用确定性词法检索查询课堂文档。

    这个类现在不是完整 RAG 引擎，但接口已经按 RAG 查询服务设计：
    - ``prompt`` 是用户问题。
    - ``documents`` 是某节课的检索语料。
    - 返回 ``answer``、``source_refs`` 和 ``warnings``。
    """

    def query(
        self,
        prompt: str,
        documents: list[RagDocument],
        limit: int = 5,
    ) -> QueryResult:
        """检索文档并构造带来源的课堂回答。

        当前排序规则非常朴素：文档命中的关键词总长度越大，排序越靠前。
        这种方式可测试、可解释；真正的语义相似度排序留给后续向量索引实现。
        """
        keywords = self._keywords(prompt)
        scored: list[tuple[int, RagDocument]] = []

        for document in documents:
            score = self._score(document.text, keywords)
            if score > 0:
                scored.append((score, document))

        ranked = [
            document
            for _, document in sorted(scored, key=lambda item: item[0], reverse=True)
        ]
        source_limit = _source_limit(limit)
        refs = [self._source_ref(document) for document in ranked[:source_limit]]

        if not refs:
            # 找不到来源时明确返回“没有依据”，而不是编造答案。这是课堂 Agent
            # 和开放域聊天机器人的关键边界。
            return QueryResult(
                answer="没有在课堂资料中找到足够依据回答这个问题。",
                source_refs=[],
                warnings=["请换一个课堂中出现过的关键词，或等更多课堂数据进入系统。"],
            )

        return QueryResult(
            answer="我在课堂资料中找到这些相关内容：\n"
            + "\n".join(f"- {ref.text}" for ref in refs),
            source_refs=refs,
            warnings=[],
        )

    def _source_ref(self, document: RagDocument) -> RagSourceRef:
        """从 RagDocument 元数据构造检索层来源引用。"""
        source_type = document.metadata.get("type", "timeline")
        source_id = str(document.metadata.get("source_id", "unknown"))
        ts = document.metadata.get("ts")
        return RagSourceRef(
            type=str(source_type),
            id=source_id,
            ts=ts if isinstance(ts, int | float) else None,
            text=compact_source_ref_text(document.text, metadata=document.metadata),
        )

    def _keywords(self, prompt: str) -> list[str]:
        """从中英文 prompt 中提取粗粒度关键词。

        这里不是通用中文分词，只做课堂演示足够用的启发式处理：
        - 去掉“讲了什么/这节课/老师”等问题外壳。
        - 保留英文单词和连续中文短语。
        - 对较长中文短语生成 4 字滑窗，提高局部命中率。
        """
        normalized = prompt.lower()
        stop_phrases = (
            "讲了什么",
            "是什么",
            "这一段",
            "这节课",
            "老师",
            "什么",
            "一下",
            "这个",
            "根据",
            "课堂",
        )
        for phrase in stop_phrases:
            normalized = normalized.replace(phrase, " ")

        tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", normalized)
        keywords = [token for token in tokens if token.strip()]
        for token in list(keywords):
            if re.fullmatch(r"[\u4e00-\u9fff]{4,}", token):
                # 没有引入 jieba 等分词依赖，所以用简单滑窗覆盖中文长词的局部匹配。
                keywords.extend(
                    token[index : index + 4] for index in range(0, len(token) - 3)
                )
        if not keywords and prompt.strip():
            keywords = [prompt.strip()]
        return list(dict.fromkeys(keywords))

    def _score(self, text: str, keywords: list[str]) -> int:
        """按命中关键词长度计算文档相关性分数。"""
        normalized = text.lower()
        return sum(len(keyword) for keyword in keywords if keyword in normalized)


def compact_source_ref_text(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    max_chars: int = SOURCE_PREVIEW_CHARS,
) -> str:
    """生成适合 Agent 来源区展示的短摘录。

    RAG 文档正文可能是整份结构化笔记或长段 OCR。检索可以使用长文本，但
    ``source_refs`` 只应该承载可读、可追溯的短来源，避免前端把整份字幕展开。
    """
    display_text = metadata.get("display_text") if metadata else None
    candidate = display_text if isinstance(display_text, str) and display_text.strip() else text
    normalized = re.sub(r"\s+", " ", candidate).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."


def _source_limit(limit: int) -> int:
    return min(max(1, limit), MAX_SOURCE_REF_COUNT)


__all__ = [
    "MAX_SOURCE_REF_COUNT",
    "QueryResult",
    "QueryService",
    "RagSourceRef",
    "compact_source_ref_text",
]
