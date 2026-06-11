from __future__ import annotations
import os
from enum import Enum
from functools import lru_cache
from typing import Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_huggingface import HuggingFaceEmbeddings

from app.logger import logging as logger
from app.config import get_settings
from app.llm.groq_client import build_groq_llm
from app.llm.ollama_client import build_ollama_llm, get_ollama_base_url


class LLMTier(str, Enum):
    """The five LLM tiers used across the agent graph."""

    FAST = "fast"
    CAPABLE = "capable"
    HEAVY = "heavy"
    SUMMARIZE = "summarize"
    EMBED = "embed"


# Ollama model tags used ONLY as a fallback when Groq is rate-limited
# AND OLLAMA_BASE_URL is configured. These are not used otherwise.
_TIER_OLLAMA_FALLBACK_MODEL: dict[LLMTier, str] = {
    LLMTier.FAST: "qwen2.5:7b-instruct",
    LLMTier.CAPABLE: "qwen2.5:7b-instruct",
    LLMTier.HEAVY: "qwen2.5:14b-instruct",
    LLMTier.SUMMARIZE: "phi3:mini",
}


def _is_rate_limit_error(exc: BaseException) -> bool:
    """
    Return True if `exc` represents an HTTP 429 rate-limit response
    from the Groq API.

    Groq's client is OpenAI-compatible and raises errors that expose a
    `status_code` attribute (directly or via a nested `response`
    object) for HTTP errors. This helper checks both shapes so it
    works whether the error originates from the `groq` SDK or the
    underlying `httpx` transport.
    """
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    return status_code == 429


def _tier_to_groq_config(tier: LLMTier) -> tuple[str, float, Optional[int]]:
    """
    Map an LLMTier to (model_name, temperature, max_tokens) using the
    centralised settings.

    SUMMARIZE reuses the FAST model at a lower temperature — see the
    module docstring for rationale.
    """
    cfg = get_settings().llm

    if tier == LLMTier.FAST:
        return cfg.LLM_FAST_MODEL, cfg.LLM_FAST_TEMPERATURE, cfg.LLM_FAST_MAX_TOKENS
    if tier == LLMTier.CAPABLE:
        return cfg.LLM_CAPABLE_MODEL, cfg.LLM_CAPABLE_TEMPERATURE, cfg.LLM_CAPABLE_MAX_TOKENS
    if tier == LLMTier.HEAVY:
        return cfg.LLM_HEAVY_MODEL, cfg.LLM_HEAVY_TEMPERATURE, cfg.LLM_HEAVY_MAX_TOKENS
    if tier == LLMTier.SUMMARIZE:
        return cfg.LLM_FAST_MODEL, 0.0, cfg.LLM_FAST_MAX_TOKENS

    raise ValueError(f"{tier!r} has no chat-model configuration (use get_embeddings()).")


def get_llm(tier: LLMTier) -> BaseChatModel:
    """
    Return a configured chat model for the given tier.

    The returned object is a Groq chat model. If OLLAMA_BASE_URL is set
    in the environment, an Ollama fallback for the same tier is
    attached via .with_fallbacks() — it only activates if the Groq call
    raises an HTTP 429 (rate limit) error, and a warning is logged when
    that happens.

    Parameters
    ----------
    tier    One of LLMTier.FAST, CAPABLE, HEAVY, SUMMARIZE.
            LLMTier.EMBED is invalid here — use get_embeddings().

    Returns
    -------
    A LangChain chat model (BaseChatModel) ready for
    .invoke() / .ainvoke() / .astream() / .with_structured_output(), etc.

    Raises
    ------
    ValueError  if tier == LLMTier.EMBED.
    """
    if tier == LLMTier.EMBED:
        raise ValueError("LLMTier.EMBED has no chat model — call get_embeddings() instead.")

    model_name, temperature, max_tokens = _tier_to_groq_config(tier)
    primary = build_groq_llm(model_name, temperature=temperature, max_tokens=max_tokens)

    ollama_url = get_ollama_base_url()
    if "OLLAMA_BASE_URL" not in os.environ:
        # No on-prem Ollama configured — Groq only, no fallback attached.
        return primary

    try:
        fallback_model = _TIER_OLLAMA_FALLBACK_MODEL[tier]
        fallback = build_ollama_llm(fallback_model, temperature=temperature, base_url=ollama_url)
    except ImportError:
        logger.warning(
            "OLLAMA_BASE_URL is set but langchain_ollama is not installed — "
            "no fallback attached for tier=%s.", tier.value,
        )
        return primary

    def _on_fallback(_exc: BaseException) -> None:
        logger.warning(
            "Groq rate-limited for tier=%s (model=%s) — falling back to "
            "Ollama model=%s at %s.",
            tier.value, model_name, fallback_model, ollama_url,
        )

    chain = primary.with_fallbacks(
        [fallback],
        exception_key=None,
    )

    # with_fallbacks() does not provide a direct "on fallback" hook in
    # all LangChain versions, so we wrap the chain to log the rate-limit
    # warning ourselves before delegating.
    original_ainvoke = chain.ainvoke
    original_invoke = chain.invoke

    async def _ainvoke_with_logging(*args, **kwargs):
        try:
            return await primary.ainvoke(*args, **kwargs)
        except Exception as exc:
            if _is_rate_limit_error(exc):
                _on_fallback(exc)
                return await fallback.ainvoke(*args, **kwargs)
            raise

    def _invoke_with_logging(*args, **kwargs):
        try:
            return primary.invoke(*args, **kwargs)
        except Exception as exc:
            if _is_rate_limit_error(exc):
                _on_fallback(exc)
                return fallback.invoke(*args, **kwargs)
            raise

    chain.ainvoke = _ainvoke_with_logging  # type: ignore[method-assign]
    chain.invoke = _invoke_with_logging    # type: ignore[method-assign]

    return chain


def get_embeddings():
    """
    Return a sentence embedding model for the ChromaDB RAG layer (Phase 4).

    Uses settings.llm.EMBEDDING_MODEL (default:
    'sentence-transformers/all-MiniLM-L6-v2') via langchain_huggingface.

    Returns
    -------
    A LangChain Embeddings instance with .embed_documents() and
    .embed_query().

    Raises
    ------
    ImportError     if langchain_huggingface / sentence-transformers
                    are not installed. Install with:
                        pip install langchain-huggingface sentence-transformers
    """
    cfg = get_settings().llm
    logger.debug("Building HuggingFaceEmbeddings | model=%s", cfg.EMBEDDING_MODEL)
    return HuggingFaceEmbeddings(model_name=cfg.EMBEDDING_MODEL)