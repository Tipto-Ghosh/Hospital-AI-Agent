"""
Operational readiness checker: run before going live and 
from CI.

Usage:
    uv run scripts/health_check.py
    uv run scripts/health_check.py --skip-ollama # if ollama is not deployed
    uv run scripts/health_check.py --skip-chroma # if chroma is not yet seeded
    
Exit code:
    0: all checks passed
    1: one or more checks failed
"""

import argparse
import asyncio
import os 
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_env(dotenv_path: Path) -> None:
    """
    Load environment variables from a .env file.
    """
    import re 
    if not dotenv_path.exists():
        return
    
    loaded: dict[str, str] = {}
    
    for raw_line in dotenv_path.read_text(encoding = "utf-8").splitlines():
        line = raw_line.strip()
        
        if not line or line.startswith("#") or "=" not in line:
            continue
        
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        
        def _expand(m):
            var = m.group(1)
            return loaded.get(var) or os.environ.get(var) or ""
        
        value = re.sub(r"\$\{([^}]+)\}", _expand, value)
        loaded[key] = value
        os.environ[key] = value

_load_env(PROJECT_ROOT / ".env")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
 
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    latency_ms: Optional[float] = None

def _colour(result: CheckResult) -> str:
    if result.status == PASS:
        return f"{GREEN}{PASS}{RESET}"
    elif result.status == FAIL:
        return f"{RED}{FAIL}{RESET}"
    
    return f"{YELLOW}{SKIP}{RESET}"

def _print_table(results: list[CheckResult]) -> None:
    col_name = max(len(r.name) for r in results) + 2
    col_status = 6
    print()
    print(f"{'Check':<{col_name}} {'Status':<{col_status}}  {'Latency':>10}  Detail")
    print("-" * (col_name + col_status + 40))
    for r in results:
        latency = f"{r.latency_ms:.0f} ms" if r.latency_ms is not None else ""
        print(f"{r.name:<{col_name}} {_colour(r):<{col_status + 10}}  {latency:>10}  {r.detail}")
    print()

async def check_mysql() -> CheckResult:
    name = "MySQL"
    t0 = time.monotonic()
    try:
        from app.db.base import get_session_context
        from app.db.models.patient import Patient
        from sqlalchemy import select, func
 
        async with get_session_context() as session:
            result = await session.execute(select(func.count()).select_from(Patient))
            count = result.scalar_one()
 
        latency = (time.monotonic() - t0) * 1000
        return CheckResult(name, PASS, f"{count} patient row(s) found", latency)
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return CheckResult(name, FAIL, str(exc)[:120], latency)

async def check_redis() -> CheckResult:
    name = "Redis"
    t0 = time.monotonic()
    try:
        from app.api.dependencies import get_redis_pool
 
        redis = await get_redis_pool()
        response = await redis.ping()
        latency = (time.monotonic() - t0) * 1000
        if response:
            return CheckResult(name, PASS, "PONG received", latency)
        return CheckResult(name, FAIL, "ping returned falsy response", latency)
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return CheckResult(name, FAIL, str(exc)[:120], latency)
    

async def check_ollama() -> CheckResult:
    name = "Ollama"
    t0 = time.monotonic()
    try:
        import httpx
        from app.llm.ollama_client import get_ollama_base_url
 
        base_url = get_ollama_base_url()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
 
        latency = (time.monotonic() - t0) * 1000
 
        if resp.status_code != 200:
            return CheckResult(name, FAIL, f"HTTP {resp.status_code}", latency)
 
        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        detail = f"{len(models)} model(s): {', '.join(models[:3]) or 'none'}"
        return CheckResult(name, PASS, detail, latency)
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return CheckResult(name, FAIL, str(exc)[:120], latency)
    

async def check_groq() -> CheckResult:
    name = "Groq API"
    t0 = time.monotonic()
    try:
        from langchain_core.messages import HumanMessage
        from app.llm.factory import LLMTier, get_llm
 
        llm = get_llm(LLMTier.FAST)
        response = await llm.ainvoke([HumanMessage(content="Reply with the single word: ok")])
        latency = (time.monotonic() - t0) * 1000
 
        reply = response.content if isinstance(response.content, str) else str(response.content)
        if reply.strip():
            return CheckResult(name, PASS, f"Response: {reply.strip()[:60]!r}", latency)
        return CheckResult(name, FAIL, "Empty response from Groq", latency)
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return CheckResult(name, FAIL, str(exc)[:120], latency)
    

async def check_chromadb() -> CheckResult:
    name = "ChromaDB"
    t0 = time.monotonic()
    try:
        import chromadb
        from app.rag.vector_store import get_or_create_collection
 
        collection = get_or_create_collection("hospital_faqs")
        result = collection.query(query_texts=["visiting hours"], n_results=1)
        latency = (time.monotonic() - t0) * 1000
 
        docs = result.get("documents", [[]])[0]
        count = collection.count()
 
        if count == 0:
            return CheckResult(
                name, FAIL,
                "Collection is empty - run: python scripts/ingest_rag_docs.py",
                latency,
            )
        detail = f"{count} document(s) in collection, query returned {len(docs)} result(s)"
        return CheckResult(name, PASS, detail, latency)
    except ImportError:
        return CheckResult(name, SKIP, "chromadb not installed")
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        return CheckResult(name, FAIL, str(exc)[:120], latency)
 
 
async def _run_checks(args: argparse.Namespace) -> list[CheckResult]:
    tasks = {
        "mysql": check_mysql(),
        "redis": check_redis(),
        "ollama": check_ollama() if not args.skip_ollama else None,
        "groq": check_groq() if not args.skip_groq   else None,
        "chroma": check_chromadb() if not args.skip_chroma else None,
    }
 
    skipped_names = {
        "Ollama": args.skip_ollama,
        "Groq API": args.skip_groq,
        "ChromaDB": args.skip_chroma,
    }
 
    results: list[CheckResult] = []
    coros = {k: v for k, v in tasks.items() if v is not None}
 
    gathered = await asyncio.gather(*coros.values(), return_exceptions=True)
 
    for (key, _), result in zip(coros.items(), gathered):
        if isinstance(result, BaseException):
            results.append(CheckResult(key.capitalize(), FAIL, str(result)[:120]))
        else:
            results.append(result)
 
    for display_name, should_skip in skipped_names.items():
        if should_skip:
            results.append(CheckResult(display_name, SKIP, "--skip flag set"))
 
    order = {"MySQL": 0, "Redis": 1, "Groq API": 2, "Ollama": 3, "ChromaDB": 4}
    results.sort(key=lambda r: order.get(r.name, 99))
    return results
 
 
async def _main() -> int:
    parser = argparse.ArgumentParser(description="Hospital-AI-Agent health check")
    parser.add_argument("--skip-ollama", action="store_true", help="Skip Ollama check")
    parser.add_argument("--skip-groq", action="store_true", help="Skip Groq API check")
    parser.add_argument("--skip-chroma", action="store_true", help="Skip ChromaDB check")
    args = parser.parse_args()
 
    print("Running Hospital-AI-Agent health checks...")
    results = await _run_checks(args)
    _print_table(results)
 
    failed = [r for r in results if r.status == FAIL]
    passed = [r for r in results if r.status == PASS]
    skipped = [r for r in results if r.status == SKIP]
 
    print(f"Results: {len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
 
    if failed:
        print(f"\n{RED}FAILED checks:{RESET}")
        for r in failed:
            print(f"  {r.name}: {r.detail}")
        print()
        return 1
 
    print(f"\n{GREEN}All checks passed.{RESET}\n")
    return 0
 
 
if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))