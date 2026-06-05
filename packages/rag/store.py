"""
ChromaDB persistent vector store helpers (no LangChain).
Collection uses cosine distance so higher similarity = smaller distance.
"""
import chromadb
from chromadb.config import Settings

BATCH_SIZE = 100


def _collection(persist_dir: str, collection_name: str):
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert(chunks: list[dict], persist_dir: str, collection_name: str) -> None:
    """
    Upsert embedded chunks into ChromaDB.
    chunks: [{"id", "text", "vector", "metadata"}, ...]
    """
    col = _collection(persist_dir, collection_name)

    ids        = [c["id"]       for c in chunks]
    embeddings = [c["vector"]   for c in chunks]
    documents  = [c["text"]     for c in chunks]
    metadatas  = [c["metadata"] for c in chunks]

    for i in range(0, len(chunks), BATCH_SIZE):
        col.upsert(
            ids        = ids[i : i + BATCH_SIZE],
            embeddings = embeddings[i : i + BATCH_SIZE],
            documents  = documents[i : i + BATCH_SIZE],
            metadatas  = metadatas[i : i + BATCH_SIZE],
        )
