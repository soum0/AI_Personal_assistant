"""
Generate embeddings using a local SentenceTransformers model (default) or an
OpenAI-compatible API. Processes chunks in batches to stay within API limits.

EMBEDDING_PROVIDER: local (default) | openai | groq
EMBEDDING_MODEL:    all-MiniLM-L6-v2 (default for local)
"""
import hashlib
import os

DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"
BATCH_SIZE = 100


def _get_embed_model() -> str:
    return os.getenv("EMBEDDING_MODEL", DEFAULT_EMBED_MODEL)


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """
    Attach vector + stable ID to each chunk.

    Input:  [{"text": str, "metadata": dict}, ...]
    Output: [{"id": str, "text": str, "vector": list[float], "metadata": dict}, ...]
    """
    provider = _get_embedding_provider()
    texts = [c["text"] for c in chunks]

    if provider == "local":
        vectors = _embed_local(texts)
    else:
        from openai import OpenAI
        client = _create_client(provider)
        vectors = _embed_in_batches(client, texts)

    return [
        {
            "id":       _stable_id(c),
            "text":     c["text"],
            "vector":   v,
            "metadata": c["metadata"],
        }
        for c, v in zip(chunks, vectors)
    ]


def _embed_local(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(_get_embed_model())
    return model.encode(texts, show_progress_bar=False).tolist()


def _embed_in_batches(client, texts: list[str]) -> list[list[float]]:
    embed_model = _get_embed_model()
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        resp  = client.embeddings.create(model=embed_model, input=batch)
        batch_vecs = [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]
        all_vectors.extend(batch_vecs)
    return all_vectors


def _create_client(provider: str):
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


def _stable_id(chunk: dict) -> str:
    """
    Content-addressed ID so re-ingesting the same chunk is a no-op upsert.
    Uses the first 16 hex chars of an MD5 over text + metadata.
    """
    meta    = chunk["metadata"]
    payload = f'{meta["source"]}|{meta["type"]}|{meta["repo_name"]}|{meta["section"]}|{chunk["text"]}'
    return hashlib.md5(payload.encode()).hexdigest()[:16]
