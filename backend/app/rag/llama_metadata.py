"""Metadata helpers for optional LlamaIndex document conversion."""

from __future__ import annotations

from typing import Any


LLAMA_METADATA_KEYS = {
    "session_id",
    "title",
    "course",
    "type",
    "source_id",
    "ts",
    "relation",
    "source",
    "target",
    "display_text",
}

LLAMA_METADATA_TEXT_LIMIT = 240


def compact_llama_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return compact metadata safe for LlamaIndex node parsing.

    LlamaIndex subtracts metadata length from chunk size. EDU-Mate's auditable
    records may include long display/source text, which should remain in
    documents.json but not in vector-index metadata.
    """
    compact: dict[str, Any] = {}
    for key in LLAMA_METADATA_KEYS:
        value = metadata.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            compact[key] = value[:LLAMA_METADATA_TEXT_LIMIT]
        elif isinstance(value, int | float | bool):
            compact[key] = value
    return compact


__all__ = ["LLAMA_METADATA_TEXT_LIMIT", "compact_llama_metadata"]
