from __future__ import annotations
from typing import Optional
from langchain_groq import ChatGroq

from app.logger import logging as logger
from app.config import get_settings

def build_groq_llm(
    model_name: str,
    temperature: float = 0.1,
    max_tokens: Optional[int] = None,
) -> ChatGroq:
    """
    Build a configured ChatGroq instance.
    """
    cfg = get_settings().llm

    kwargs: dict = {
        "model": model_name,
        "api_key": cfg.GROQ_API_KEY,
        "temperature": temperature,
        "timeout": cfg.LLM_REQUEST_TIMEOUT,
        "max_retries": cfg.LLM_MAX_RETRIES,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    logger.debug(
        "Building ChatGroq | model=%s temperature=%.2f max_tokens=%s",
        model_name, temperature, max_tokens,
    )
    return ChatGroq(**kwargs)