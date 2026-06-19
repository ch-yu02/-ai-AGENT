"""Runtime configuration helpers for optional LlamaIndex backends."""

from __future__ import annotations

import os
from typing import Any


_CONFIGURED_SIGNATURE: tuple[str, str, str, str, str] | None = None


def configure_llamaindex_settings(settings: Any) -> None:
    """Configure LlamaIndex embedding/LLM settings from environment variables.

    The project uses LlamaIndex mainly as a vector retriever. By default we
    disable LlamaIndex's LLM layer and set a local HuggingFace embedding model
    when optional dependencies are installed.
    """
    global _CONFIGURED_SIGNATURE

    backend = os.getenv("RAG_EMBEDDING_BACKEND", "huggingface").strip().lower()
    model = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip()
    device = os.getenv("RAG_EMBEDDING_DEVICE", "cpu").strip()
    trust_remote_code = os.getenv("RAG_EMBEDDING_TRUST_REMOTE_CODE", "false").strip().lower()
    llm_mode = os.getenv("RAG_LLAMAINDEX_LLM", "disabled").strip().lower()
    signature = (backend, model, device, trust_remote_code, llm_mode)

    if _CONFIGURED_SIGNATURE == signature:
        return

    if llm_mode in {"", "disabled", "none", "off"}:
        settings.llm = None

    if backend in {"", "default"}:
        _CONFIGURED_SIGNATURE = signature
        return

    if backend == "huggingface":
        settings.embed_model = _huggingface_embedding(
            model_name=model,
            device=device,
            trust_remote_code=trust_remote_code in {"1", "true", "yes", "on"},
        )
    elif backend == "openai":
        settings.embed_model = _openai_embedding(model_name=model)
    else:
        raise RuntimeError(f"Unsupported RAG_EMBEDDING_BACKEND: {backend}")

    _CONFIGURED_SIGNATURE = signature


def _huggingface_embedding(
    *,
    model_name: str,
    device: str,
    trust_remote_code: bool,
) -> Any:
    try:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    except ImportError as exc:
        raise RuntimeError(
            "llama-index HuggingFace embeddings are not installed; run "
            "scripts/dev.sh install-rag or set RAG_EMBEDDING_BACKEND=default"
        ) from exc

    kwargs: dict[str, Any] = {
        "model_name": model_name,
    }
    if device:
        kwargs["device"] = device
    if trust_remote_code:
        kwargs["trust_remote_code"] = True

    try:
        return HuggingFaceEmbedding(**kwargs)
    except TypeError:
        kwargs.pop("device", None)
        kwargs.pop("trust_remote_code", None)
        return HuggingFaceEmbedding(**kwargs)


def _openai_embedding(*, model_name: str) -> Any:
    try:
        from llama_index.embeddings.openai import OpenAIEmbedding
    except ImportError as exc:
        raise RuntimeError(
            "llama-index OpenAI embeddings are not installed; run "
            "scripts/dev.sh install-rag"
        ) from exc

    api_key = os.getenv("RAG_EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY")
    base_url = os.getenv("RAG_EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL")
    kwargs: dict[str, Any] = {"model": model_name or "text-embedding-3-small"}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["api_base"] = base_url

    try:
        return OpenAIEmbedding(**kwargs)
    except TypeError:
        kwargs.pop("api_base", None)
        return OpenAIEmbedding(**kwargs)


__all__ = ["configure_llamaindex_settings"]
