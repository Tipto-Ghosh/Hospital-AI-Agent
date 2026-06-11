from __future__ import annotations
import os
import httpx
from typing import Optional
from app.logger import logging as logger
from langchain_ollama import ChatOllama

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

def get_ollama_base_url() -> str:
    """Return the configured Ollama base URL, or the local default."""
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)


def build_ollama_llm(
    model_name: str,
    temperature: float = 0.1,
    base_url: Optional[str] = None,
):
    """
    Build a configured ChatOllama instance.
    """
    url = base_url or get_ollama_base_url()

    logger.debug(
        f"Building ChatOllama | model={model_name} temperature={temperature} base_url={url}"
    )
    return ChatOllama(model=model_name, temperature=temperature, base_url=url)


async def ping_ollama(base_url: Optional[str] = None, timeout: float = 2.0) -> bool:
    
    url = base_url or get_ollama_base_url()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{url}/api/tags")
            return response.status_code == 200
    except Exception as exc:
        logger.debug(f"ping_ollama: {url} unreachable ({exc})")
        return False