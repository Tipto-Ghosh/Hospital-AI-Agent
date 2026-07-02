import os
from dotenv import load_dotenv
load_dotenv()
from typing import Optional
from app.llm.factory import get_embeddings
from app.logger import logging

logger = logging.getLogger(__name__)

DEFAULT_CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
DEFAULT_COLLECTION_NAME = os.getenv("DEFAULT_COLLECTION_NAME", "hospital_faqs")

_client = None
_collections: dict[str, object] = {}

def get_chroma_persist_dir()->str:
    """Return the configured ChromaDB persistence directory."""
    return os.environ.get("CHROMA_PERSIST_DIR", DEFAULT_CHROMA_PERSIST_DIR)

def get_chroma_client():
    """Return a persistent ChromaDB client pointed at the configured persistence directory.
    
    The client is cached at module level, so repeated calls return the same client instance, avoiding redundant on-disk index loads.
    
    Returns
    -------
    A chromadb.PersistentClient instance.
    """
    
    global _client
    if _client is not None:
        return _client
    
    try:
        import chromadb
    except ImportError as exc:
        logger.error("ChromaDB is not installed. Please install it with `pip install chromadb`.")
        raise ImportError("ChromaDB is not installed. Please install it with `pip install chromadb`.") from exc
    
    persist_dir = get_chroma_persist_dir()
    try:
        _client = chromadb.PersistentClient(path=persist_dir)
        logger.info(f"ChromaDB client initialized with persistence directory: {persist_dir}")
    except Exception as exc:
        logger.error(f"Failed to initialize ChromaDB client with persistence directory {persist_dir}: {exc}")
        raise
    
    return _client

class _LangChainEmbeddingFunction:
    """Adapts a Langchain Embeddings instance from app.llm.factory.get_embeddings()
    to ChromaDB's embedding_function interface, which expects a callable
    taking a list of strings and returning a list of vectors.
    """
    def __init__(self, embeddings):
        self.embeddings = embeddings
    
    def __call__(self, input: list[str]) -> list[list[float]]:
        """Compute embeddings for a list of strings using the Langchain Embeddings instance."""
        return self.embeddings.embed_documents(input)
    
    def name(self) -> str:
        """Return a name for this embedding function, for logging/debugging purposes."""
        return f"LangChainEmbeddingFunction({self.embeddings.__class__.__name__})"
    
def get_or_create_collection(collection_name: str = DEFAULT_COLLECTION_NAME):
    """ 
    Get or create a ChromaDB collection with the given name, using the configured embedding function.
    
    Collections are cached at module level, so repeated calls with the same name return the same collection instance.
    """
    
    if collection_name in _collections:
        return _collections[collection_name]
    
    client = get_chroma_client()
    embeddings = get_embeddings()
    embedding_function = _LangChainEmbeddingFunction(embeddings)
    
    try:
        collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function
        )
    except Exception as exc:
        logger.error(f"Failed to get or create ChromaDB collection '{collection_name}': {exc}")
    
    _collections[collection_name] = collection
    logger.info(f"ChromaDB collection '{collection_name}' initialized.")
    return collection

def reset_chroma_cache():
    """Reset the module-level cache of ChromaDB client and collections.
    
    Intended for testing purposes, to force re-initialization of the client and collections.
    """
    global _client, _collections
    _client = None
    _collections.clear()
    logger.debug("ChromaDB client and collections cache reset.")