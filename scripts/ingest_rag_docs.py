""" 
One-Command ingestion runner for the ChromaDB RAG knowledge base.
"""
import os 
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0 , str(PROJECT_ROOT))


def _load_dotenv(dotenv_path: Path) -> None:
    """ 
    Minimal .env loader, no external dependencies required.
    Reads key=value lines, strips quotes and calls os.environ.setdefault()
    so that existing environment variables are not overwritten.
    """
    if not dotenv_path.exists():
        print(f"Warning: .env file not found at {dotenv_path}, skipping dotenv load.")
        return
    
    loaded = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        
        if not line or line.startswith("#") or "=" not in line:
            continue
        if "=" not in line:
            continue
        
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        
        import re as _re 
        def _expand(m: "_re.Match[str]") -> str:
            var_name = m.group(1)
            return loaded.get(var_name) or os.environ.get(var_name) or ""
        
        value = _re.sub(r"\$\{(\w+)\}", _expand, value)
        loaded[key] = value
        os.environ.setdefault(key, value)
        
_load_dotenv(PROJECT_ROOT / ".env")

import asyncio
import argparse

DATA_DOCS_DIR = PROJECT_ROOT / "data" / "docs"
SUPPORTED_EXTENSIONS = {".txt", ".pdf"}
 
 
async def _ingest_from_mysql() -> dict[str, int]:
    from app.db.base import get_session_context
    from app.rag.ingestion import ingest_hospital_info_from_db
 
    print("Ingesting hospital_info rows from MySQL ...")
    try:
        async with get_session_context() as db:
            summary = await ingest_hospital_info_from_db(db)
    except Exception as exc:
        print(f"  ERROR: failed to ingest from MySQL: {exc}")
        return {"total_rows": 0, "ingested": 0, "skipped": 0}
 
    print(
        f"  hospital_info: {summary['total_rows']} row(s) found, "
        f"{summary['ingested']} ingested, {summary['skipped']} skipped (unchanged)"
    )
    return summary

def _discover_doc_files(docs_dir: Path) -> list[Path]:
    if not docs_dir.exists():
        print(f"  {docs_dir} does not exist — skipping file ingestion.")
        return []
 
    files = sorted(
        p for p in docs_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return files

def _ingest_from_files(docs_dir: Path) -> dict[str, int]:
    from app.rag.ingestion import ingest_from_file
 
    print(f"Looking for .txt and .pdf files in {docs_dir} ...")
    files = _discover_doc_files(docs_dir)
 
    if not files:
        print("No documents found.")
        return {"files_processed": 0, "total_chunks": 0, "ingested": 0, "skipped": 0}
 
    totals = {"files_processed": 0, "total_chunks": 0, "ingested": 0, "skipped": 0}
 
    for file_path in files:
        print(f"  Ingesting {file_path.name} ...")
        try:
            # FIX: Pass the Path object directly instead of converting to string
            summary = ingest_from_file(file_path)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}")
            continue
        except ImportError as exc:
            print(f"ERROR: missing dependency — {exc}")
            continue
        except Exception as exc:
            print(f"ERROR: failed to ingest {file_path.name}: {exc}")
            continue
 
        print(
            f"{summary['total_chunks']} chunk(s), "
            f"{summary['ingested']} ingested, {summary['skipped']} skipped (unchanged)"
        )
        totals["files_processed"] += 1
        totals["total_chunks"] += summary["total_chunks"]
        totals["ingested"] += summary["ingested"]
        totals["skipped"] += summary["skipped"]
 
    return totals

async def _main() -> None:
    parser = argparse.ArgumentParser(description="Ingest hospital documents into the ChromaDB RAG store.")
    parser.add_argument(
        "--docs-dir",
        default=str(DATA_DOCS_DIR),
        help=f"Directory to scan for .txt/.pdf files (default: {DATA_DOCS_DIR}).",
    )
    parser.add_argument(
        "--skip-mysql",
        action="store_true",
        help="Skip ingesting hospital_info rows from MySQL.",
    )
    parser.add_argument(
        "--skip-files",
        action="store_true",
        help="Skip ingesting .txt/.pdf files from --docs-dir.",
    )
    args = parser.parse_args()
 
    print("=" * 60)
    print("RAG Document Ingestion")
    print("=" * 60)
 
    try:
        import chromadb  # noqa: F401
    except ImportError:
        print(
            "ERROR: chromadb is not installed. Install it with: pip install chromadb\n"
            "Aborting — nothing was ingested."
        )
        sys.exit(1)
 
    mysql_summary = {"total_rows": 0, "ingested": 0, "skipped": 0}
    file_summary = {"files_processed": 0, "total_chunks": 0, "ingested": 0, "skipped": 0}
 
    if not args.skip_mysql:
        mysql_summary = await _ingest_from_mysql()
    else:
        print("Skipping MySQL ingestion (--skip-mysql).")
 
    if not args.skip_files:
        file_summary = _ingest_from_files(Path(args.docs_dir))
    else:
        print("Skipping file ingestion (--skip-files).")
 
    total_ingested = mysql_summary["ingested"] + file_summary["ingested"]
    total_skipped = mysql_summary["skipped"] + file_summary["skipped"]
 
    print("-" * 60)
    print(
        f"Done. {total_ingested} document(s)/chunk(s) ingested, "
        f"{total_skipped} skipped (already up to date)."
    )
    print("=" * 60)
 
 
if __name__ == "__main__":
    asyncio.run(_main())