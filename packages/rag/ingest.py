"""
RAG ingestion pipeline — run once to index resume + GitHub repos into ChromaDB.

Usage:
    python ingest.py                    # uses config.yaml in same dir
    python ingest.py --config path.yaml
    python ingest.py --reset            # wipe collection before ingesting
"""
import argparse
import os
import time

import yaml
from dotenv import load_dotenv

load_dotenv()


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _stats(label: str, chunks: list[dict], elapsed: float) -> None:
    if not chunks:
        print(f"  [{label}] 0 chunks  ({elapsed:.1f}s)")
        return
    sizes = [len(c["text"]) for c in chunks]
    avg   = sum(sizes) // len(sizes)
    mn    = min(sizes)
    mx    = max(sizes)
    print(f"  [{label}] {len(chunks):>4} chunks | avg {avg} chars | min {mn} | max {mx} | {elapsed:.1f}s")


def _reset_collection(persist_dir: str, collection_name: str) -> None:
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(path=persist_dir, settings=Settings(anonymized_telemetry=False))
    try:
        client.delete_collection(collection_name)
        print(f"  Deleted existing collection '{collection_name}'")
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest resume + GitHub repos into ChromaDB")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--reset",  action="store_true",   help="Delete collection before ingesting")
    args = parser.parse_args()

    cfg = load_config(args.config)

    persist_dir  = cfg.get("chroma",    {}).get("persist_dir",  "./chroma_db")
    collection   = cfg.get("chroma",    {}).get("collection",   "persona")
    resume_path  = cfg.get("resume",    {}).get("path",         "./data/resume.pdf")
    repo_urls    = cfg.get("github",    {}).get("repos",        []) or []
    max_commits  = cfg.get("github",    {}).get("max_commits",  30)
    embed_cfg    = cfg.get("embedding", {})
    provider     = embed_cfg.get("provider")
    model        = embed_cfg.get("model")
    github_token = os.getenv("GITHUB_TOKEN", "")

    print(f"\nai-persona RAG ingest  |  collection={collection}  |  store={persist_dir}")
    print("=" * 60)

    if args.reset:
        print("\n[0/4] Resetting collection...")
        _reset_collection(persist_dir, collection)

    all_chunks: list[dict] = []
    total_start = time.perf_counter()

    # ── 1. Resume ────────────────────────────────────────────────
    print("\n[1/4] Loading resume...")
    from loaders.resume import load_resume
    t = time.perf_counter()
    try:
        resume_chunks = load_resume(resume_path)
    except FileNotFoundError as e:
        print(f"  WARNING: {e} — skipping resume.")
        resume_chunks = []
    _stats("resume", resume_chunks, time.perf_counter() - t)
    all_chunks.extend(resume_chunks)

    # ── 2. GitHub ────────────────────────────────────────────────
    if repo_urls:
        print(f"\n[2/4] Fetching {len(repo_urls)} GitHub repo(s)...")
        from loaders.github import load_github_repos
        t = time.perf_counter()
        github_chunks = load_github_repos(repo_urls, token=github_token, max_commits=max_commits)
        _stats("github", github_chunks, time.perf_counter() - t)
        all_chunks.extend(github_chunks)
    else:
        print("\n[2/4] No GitHub repos configured in config.yaml — skipping.")

    if not all_chunks:
        print("\nNothing to ingest. Add a resume PDF and/or GitHub repos to config.yaml.")
        return

    # ── 3. Embed ─────────────────────────────────────────────────
    embed_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    if provider and not os.getenv("EMBEDDING_PROVIDER"):
        os.environ["EMBEDDING_PROVIDER"] = str(provider)
    if model and not os.getenv("EMBEDDING_MODEL"):
        os.environ["EMBEDDING_MODEL"] = str(model)

    embed_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    print(f"\n[3/4] Embedding {len(all_chunks)} chunks (model={embed_model})...")
    from embeddings import embed_chunks
    t = time.perf_counter()
    embedded = embed_chunks(all_chunks)
    _stats("embed", embedded, time.perf_counter() - t)

    # ── 4. Store ─────────────────────────────────────────────────
    print(f"\n[4/4] Upserting to ChromaDB...")
    from store import upsert
    t = time.perf_counter()
    upsert(embedded, persist_dir=persist_dir, collection_name=collection)
    elapsed_store = time.perf_counter() - t

    # ── Summary ──────────────────────────────────────────────────
    total = time.perf_counter() - total_start
    sizes = [len(c["text"]) for c in all_chunks]
    type_counts: dict[str, int] = {}
    for c in all_chunks:
        t_key = c["metadata"].get("type", "unknown")
        type_counts[t_key] = type_counts.get(t_key, 0) + 1

    print(f"""
╔══════════════════════════════════════════════╗
  Ingestion complete in {total:.1f}s
  Total chunks   : {len(all_chunks)}
  Avg chunk size : {sum(sizes) // len(sizes)} chars
  Store time     : {elapsed_store:.1f}s
  Collection     : {collection}
  Persist dir    : {persist_dir}

  Chunk breakdown by type:""")
    for chunk_type, count in sorted(type_counts.items()):
        print(f"    {chunk_type:<20} {count}")
    print("╚══════════════════════════════════════════════╝")


if __name__ == "__main__":
    main()
