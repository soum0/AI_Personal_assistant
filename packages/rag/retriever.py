"""
Retrieve relevant chunks from ChromaDB.

Public API:
    retrieve(query, top_k=5, persist_dir=..., collection_name=...) -> list[dict]
"""
import os

import chromadb
from chromadb.config import Settings

DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"


def retrieve(
    query: str,
    top_k: int = 5,
    persist_dir: str | None = None,
    collection_name: str | None = None,
) -> list[dict]:
    """
    Return top_k chunks most semantically similar to query.

    Each result:
        {
            "text":     str,
            "score":    float,   # cosine similarity in [0, 1], higher = more relevant
            "metadata": {
                "source":    "resume" | "github",
                "type":      str,
                "repo_name": str,
                "section":   str,
            }
        }
    """
    persist_dir     = persist_dir     or os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    collection_name = collection_name or os.getenv("CHROMA_COLLECTION",  "persona")

    vec = _embed(query)

    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    col = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    results = col.query(
        query_embeddings=[vec],
        n_results=min(top_k, col.count() or top_k),
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        score = round(max(0.0, 1.0 - dist), 4)
        output.append({"text": doc, "score": score, "metadata": meta})

    return output


def _embed(text: str) -> list[float]:
    provider = _get_embedding_provider()
    embed_model = os.getenv("EMBEDDING_MODEL", DEFAULT_EMBED_MODEL)

    if provider == "local":
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(embed_model)
        return model.encode([text])[0].tolist()

    from openai import OpenAI
    client = _create_api_client(provider)
    resp = client.embeddings.create(model=embed_model, input=[text])
    return resp.data[0].embedding


def _create_api_client(provider: str):
    from openai import OpenAI
    if provider not in {"openai", "groq"}:
        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider!r}. Use local, openai, or groq.")
    return OpenAI(
        api_key=_get_embedding_api_key(provider),
        base_url=_get_embedding_base_url(provider),
    )


def _get_embedding_provider() -> str:
    return os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()


def _get_embedding_base_url(provider: str) -> str | None:
    base_url = os.getenv("EMBEDDING_BASE_URL")
    if provider == "groq" and not base_url:
        return "https://api.groq.com/openai/v1"
    return base_url


def _get_embedding_api_key(provider: str) -> str:
    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is required when EMBEDDING_PROVIDER=groq")
        return api_key

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
    return api_key
