import os 
from dotenv import load_dotenv
load_dotenv()  
import hashlib
from typing import List, Optional, Any
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.medication import HospitalInfo
from app.logger import logging
from app.rag.vector_store import get_or_create_collection

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = os.getenv("DEFAULT_CHUNK_SIZE", 500)
DEFAULT_CHUNK_OVERLAP = os.getenv("DEFAULT_CHUNK_OVERLAP", 50)


def _content_hash(content: str) -> str:
    """Generate a hash for the given content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def _existing_ids(collection, candidate_ids: List[str]) -> List[str]:
    """Check which of the candidate IDs already exist in the collection."""
    if not candidate_ids:
        return set()
    
    try:
        result = collection.get(ids=candidate_ids)
        return set(result.get("ids", []))
    except Exception as e:
        logger.warning(
            f"_existing_ids: collection.get() failed, assuming no existing IDs. Error: {e}"
        )
        return set()
    
async def ingest_hospital_info_from_db(
    db: AsyncSession,
    collection_name: str = os.getenv("DEFAULT_COLLECTION_NAME", "hospital_faqs")
) -> dict[str, int]:
    """
    Read every row from the hospital_info MySql table, convert each row into a 
    Langchain Document, and ingest them into the specified Chroma collection.
    """
    try:
        collection = get_or_create_collection(collection_name)
    except ImportError as e:
        logger.error(f"ingest_hospital_info_from_db: chromadb is not installed: {e}")
        return {"total_rows": 0, "ingested": 0, "skipped": 0}
    
    except ImportError as e:
        logger.error(f"Failed to import Chroma or related modules: {e}")
        return {"total_rows": 0, "ingested": 0, "skipped": 0}
    
    # Fetch all rows from the hospital_info table
    result = await db.execute(select(HospitalInfo))
    rows = result.scalars().all()
    
    if not rows:
        logger.info("No rows found in hospital_info table.")
        return {"total_rows": 0, "ingested": 0, "skipped": 0}
    
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for row in rows:
        page_content = f"{row.topic}\n\n{row.content}"
        doc_id = _content_hash(page_content)
        metadata = {
            "source": "hospital_info",
            "info_id": row.id,
            "category": row.category,
            "topic": row.topic,
        }
        candidates.append((doc_id, page_content, metadata))
    
    candidate_ids = [doc_id for doc_id, _, _ in candidates]
    already_present = _existing_ids(collection, candidate_ids)
    
    to_ingest = [
        c for c in candidates if c[0] not in already_present
    ]
    
    if to_ingest:
        try:
            collection.upsert(
                ids=[c[0] for c in to_ingest],
                documents=[c[1] for c in to_ingest],
                metadatas=[c[2] for c in to_ingest]
            )
        except Exception as e:
            logger.error(f"Failed to upsert documents into collection '{collection_name}': {e}")
            return {"total_rows": len(rows), "ingested": 0, "skipped": len(rows)}
    
    summary = {
        
        "total_rows": len(rows),
        "ingested": len(to_ingest),
        "skipped": len(rows) - len(to_ingest)
    }
    logger.info(
        f"ingest_hospital_info_from_db: Ingestion summary for collection '{collection_name}': {summary}"
    )
    return summary

def _load_text_from_file(file_path: Path) -> str:
    """
    Load raw text frin a plain text file(.txt, .md) or PDF(.pdf) file.
    """
    path = Path(file_path)
    if not path.exists():
        logger.error(f"File not found: {file_path}")
        return ""
    
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.error("pypdf is not installed. Please install it to read PDF files.")
            return ""
        
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    
    return path.read_text(encoding="utf-8", errors="ignore")

def _chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> List[str]:
    """
    Split the text into chunks of specified size with optional overlap.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len
    )
    chunks = splitter.split_text(text)
    return [chunk for chunk in chunks if chunk.strip()]

def ingest_from_file(
    file_path: str,
    collection_name: str = os.getenv("DEFAULT_COLLECTION_NAME", "hospital_faqs"),
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
) -> dict[str, int]:
    """ 
    Load a plain text or PDF file, split it into chunks, and ingest them into the specified Chroma collection.
    """
    text = _load_text_from_file(Path(file_path))
    if not text.exists():
        logger.warning(
            f"ingest_from_file: {file_path} contains no extractable text.")
        return {"total_chunks": 0, "ingested": 0, "skipped": 0}
    
    chunks = _chunk_text(text, chunk_size, chunk_overlap)
    if not chunks:
        logger.warning(
            f"ingest_from_file: {file_path} yielded no chunks after splitting.")
        return {"total_chunks": 0, "ingested": 0, "skipped": 0}
    
    try:
        collection = get_or_create_collection(collection_name)
    except ImportError as e:
        logger.error(f"ingest_from_file: chromadb is not installed: {e}")
        return {"total_chunks": len(chunks), "ingested": 0, "skipped": len(chunks)}
    except Exception as e:
        logger.error(f"ingest_from_file: Failed to get or create collection '{collection_name}': {e}")
        return {"total_chunks": len(chunks), "ingested": 0, "skipped": len(chunks)}
    
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for index, chunk in enumerate(chunks):
        doc_id = _content_hash(chunk)
        metadata = {
            "source": "file",
            "file_path": str(file_path),
            "chunk_index": index,
        }
        candidates.append((doc_id, chunk, metadata))
    
    candidate_ids = [doc_id for doc_id, _, _ in candidates]
    already_present = _existing_ids(collection, candidate_ids)
    to_ingest = [c for c in candidates if c[0] not in already_present]
    
    if to_ingest:
        try:
            collection.upsert(
                ids=[c[0] for c in to_ingest],
                documents=[c[1] for c in to_ingest],
                metadatas=[c[2] for c in to_ingest]
            )
        except Exception as e:
            logger.error(f"Failed to upsert chunks into collection '{collection_name}': {e}")
            return {"total_chunks": len(chunks), "ingested": 0, "skipped": len(chunks)}
        
    summary = {
        "total_chunks": len(chunks),
        "ingested": len(to_ingest),
        "skipped": len(chunks) - len(to_ingest)
    }
    logger.info(
        f"ingest_from_file: Ingestion summary for collection '{collection_name}': {summary}"
    )
    return summary