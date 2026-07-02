import os
from dotenv import load_dotenv
load_dotenv()
from langchain_core.tools import tool

from app.logger import logging
from app.rag.vector_store import get_or_create_collection

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", 3))
DEFAULT_SIMILARITY_THRESHOLD = float(os.getenv("DEFAULT_SIMILARITY_THRESHOLD", 0.7))

def _distance_to_similarity(distance: float) -> float:
    """Convert a ChromaDB query distance into a 0-1 similarity score."""
    similarity = 1.0 - distance
    return max(0.0, min(1.0, similarity))  # Clamp to [0, 1]

@tool
async def rag_search(query: str) -> str:
    """ 
    Semantic search over hostpital FAQ and Policy documents using ChromaDB.
    
    Use this for open-ended questions that the structured info tools
    (get_doctor_info, get_department_info, get_hospital_info,
    list_services) don't directly cover — for example, paraphrased
    policy questions, multi-part questions, or anything where an exact
    keyword match against the hospital_info table is unlikely to
    succeed but the underlying content has been ingested into the
    knowledge base (see app/rag/ingestion.py).
 
    Parameters
    ----------
    query: The patient's question, in their own words. Used directly
            as the semantic search query — no need to extract keywords first.
 
    Returns
    -------
    A formatted string containing up to 3 matched FAQ/policy excerpts
    for the LLM to synthesize an answer from, each labeled with its
    source. Results below a similarity threshold of 0.7 are filtered
    out as too weak a match to be trustworthy. Returns a clear
    "no relevant information found" string if nothing clears the
    threshold (including if the collection is empty or unavailable) —
    callers should treat this the same as any other empty tool result
    and say so to the patient rather than guessing.
    """
    
    try:
        collection = get_or_create_collection(os.getenv("DEFAULT_COLLECTION_NAME", "hospital_faqs"))
    except ImportError as e:
        logger.error(f"rag_search: chromadb is not installed: {e}")
        return "No relevant information found."
    except Exception as e:
        logger.error(f"rag_search: failed to get or create collection: {e}")
        return "No relevant information found."
    
    try:
        result = collection.query(
            query_texts=[query],
            n_results=DEFAULT_TOP_K,
        )
    except Exception as e:
        logger.error(f"rag_search: collection.query() failed: {e}")
        return "No relevant information found."
    
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    
    if not documents:
        logger.info(f"rag_search: query = {query} returned no documents.")
        return "No relevant information found."
    
    matches = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        similarity = _distance_to_similarity(dist)
        if similarity >= DEFAULT_SIMILARITY_THRESHOLD:
            matches.append((doc, meta or {}, similarity))
    
    if not matches:
        logger.info(f"rag_search: query = {query} returned no matches above similarity threshold.")
        return "No relevant information found."
    
    formatted_sections = []
    for doc, meta, similarity in matches:
        source = meta.get("topic") or meta.get("source") or "Hospital Knowledge Base"
        formatted_sections.append(
            f"Source: {source} (relevance: {similarity:.2f})\n{doc}"
        )
    
    logger.info(f"rag_search: query = {query} returned {len(formatted_sections)} matches above threshold.")
    return "\n\n---\n\n".join(formatted_sections)