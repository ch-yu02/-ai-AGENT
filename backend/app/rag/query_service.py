"""Local retrieval service for classroom RAG documents.

This module is a dependency-free stepping stone toward LlamaIndex. It exposes a
query-oriented interface that returns an answer and source references, while the
implementation is currently a deterministic lexical search over ``RagDocument``
objects.

When LlamaIndex is introduced, keep the public ``QueryService.query()`` shape
and replace the internals with index construction + query engine calls.
"""

import re
from dataclasses import dataclass

from .documents import RagDocument


@dataclass(frozen=True)
class RagSourceRef:
    """Provider-neutral source reference returned by the retrieval layer."""

    type: str
    id: str
    text: str
    ts: float | None = None


@dataclass(frozen=True)
class QueryResult:
    """Result returned by QueryService."""

    answer: str
    source_refs: list[RagSourceRef]
    warnings: list[str]


class QueryService:
    """Query classroom documents with a deterministic lexical retriever."""

    def query(
        self,
        prompt: str,
        documents: list[RagDocument],
        limit: int = 5,
    ) -> QueryResult:
        """Search documents and build a classroom-grounded answer."""
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
        refs = [self._source_ref(document) for document in ranked[:limit]]

        if not refs:
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
        source_type = document.metadata.get("type", "timeline")
        source_id = str(document.metadata.get("source_id", "unknown"))
        ts = document.metadata.get("ts")
        return RagSourceRef(
            type=str(source_type),
            id=source_id,
            ts=ts if isinstance(ts, int | float) else None,
            text=document.text,
        )

    def _keywords(self, prompt: str) -> list[str]:
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
                keywords.extend(
                    token[index : index + 4] for index in range(0, len(token) - 3)
                )
        if not keywords and prompt.strip():
            keywords = [prompt.strip()]
        return list(dict.fromkeys(keywords))

    def _score(self, text: str, keywords: list[str]) -> int:
        normalized = text.lower()
        return sum(len(keyword) for keyword in keywords if keyword in normalized)


__all__ = ["QueryResult", "QueryService", "RagSourceRef"]
