"""Smoke-test the configured RAG query backend.

The script intentionally uses a tiny in-memory classroom document so it can
validate provider/dependency configuration without requiring a saved session.
Use ``--require-llamaindex`` in demos or deployment checks when vector RAG must
be available.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from backend.app.rag import LlamaIndexQueryService, RagDocument, build_query_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test EDU-Mate RAG backend")
    parser.add_argument(
        "--query",
        default="傅里叶变换讲了什么？",
        help="query text for the smoke document",
    )
    parser.add_argument(
        "--require-llamaindex",
        action="store_true",
        help="exit non-zero unless the configured backend is usable LlamaIndex",
    )
    args = parser.parse_args()

    service = build_query_service()
    documents = [
        RagDocument(
            text="[1.00s-3.00s] 傅里叶变换可以把时域信号转换到频域，是频谱分析的重要工具。",
            metadata={
                "session_id": "lec_rag_smoke",
                "type": "segment",
                "source_id": "seg_smoke_001",
                "ts": 1.0,
            },
        ),
        RagDocument(
            text="结构化课堂笔记：本节重点包括时域、频域和傅里叶变换的应用场景。",
            metadata={
                "session_id": "lec_rag_smoke",
                "type": "structured_note",
                "source_id": "structured_notes",
                "display_text": "结构化课堂笔记：时域、频域和傅里叶变换的应用场景。",
            },
        ),
    ]
    result = service.query(args.query, documents, limit=3)
    service_name = service.__class__.__name__
    payload = {
        "service": service_name,
        "rag_backend": os.getenv("RAG_QUERY_BACKEND", "lexical"),
        "embedding_backend": os.getenv("RAG_EMBEDDING_BACKEND", "huggingface"),
        "embedding_model": os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
        "answer": result.answer,
        "source_refs": [asdict(ref) for ref in result.source_refs],
        "warnings": result.warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.require_llamaindex:
        if not isinstance(service, LlamaIndexQueryService):
            print("RAG_QUERY_BACKEND is not llamaindex.", file=sys.stderr)
            return 1
        if any("LlamaIndex 查询不可用" in warning for warning in result.warnings):
            print("LlamaIndex query fell back to lexical search.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
