"""
RAG retrieval quality evaluator.

For each question in golden_qa.json that has a source_hint:
  1. Retrieve top-5 chunks via the ChromaDB retriever
  2. Check whether the correct source type/section is in the top-5 (precision@5)
  3. Compute Mean Reciprocal Rank (MRR)
  4. Record average relevance scores

Outputs:
  rag_metrics.json   — precision@5, MRR, per-question breakdown

Requires:
    CHROMA_PERSIST_DIR  (default: ../packages/rag/chroma_db)
    CHROMA_COLLECTION   (default: persona)
    EMBEDDING_PROVIDER  (optional: openai|groq)
    OPENAI_API_KEY or GROQ_API_KEY (based on EMBEDDING_PROVIDER)
    EMBEDDING_BASE_URL  (optional, for OpenAI-compatible endpoints)

Usage:
  python eval_rag.py
  python eval_rag.py --golden golden_qa.json --out rag_metrics.json
  python eval_rag.py --rag-dir /path/to/chroma_db
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

console = Console()

# Add the rag package to path so we can import retriever directly
_RAG_PKG = str(Path(__file__).resolve().parent.parent / "packages" / "rag")
if _RAG_PKG not in sys.path:
    sys.path.insert(0, _RAG_PKG)


def _import_retriever():
    try:
        from retriever import retrieve  # type: ignore
        return retrieve
    except ImportError as exc:
        console.print(f"[red]Cannot import rag retriever: {exc}[/red]")
        console.print(
            f"[dim]Make sure packages/rag deps are installed "
            f"(chromadb, openai) and chroma_db is populated.[/dim]"
        )
        sys.exit(1)


# ── Matching logic ─────────────────────────────────────────────────────────────

def _chunk_matches_hint(chunk: dict, hint: dict) -> bool:
    """
    Return True if this chunk satisfies the source_hint.

    source_hint can be:
      {"source": "resume", "section": "Education"}
      {"source": "github", "type": "overview"}
      {"source": "github", "type": "tradeoffs"}
    """
    meta = chunk.get("metadata", {})
    if hint.get("source") and meta.get("source") != hint["source"]:
        return False
    if hint.get("section") and meta.get("section") != hint["section"]:
        return False
    if hint.get("type") and meta.get("type") != hint["type"]:
        return False
    return True


def reciprocal_rank(chunks: list[dict], hint: dict) -> float:
    for rank, chunk in enumerate(chunks, start=1):
        if _chunk_matches_hint(chunk, hint):
            return 1.0 / rank
    return 0.0


# ── Eval loop ─────────────────────────────────────────────────────────────────

def run_eval(
    golden_path: str,
    out_path: str,
    rag_dir: str | None,
    top_k: int,
) -> None:
    with open(golden_path) as f:
        qa_set = json.load(f)

    # Override chroma path if requested
    if rag_dir:
        os.environ["CHROMA_PERSIST_DIR"] = rag_dir

    retrieve = _import_retriever()

    # Only evaluate questions that have a source_hint
    evaluable = [q for q in qa_set if q.get("source_hint")]
    console.print(
        f"\n[bold]RAG eval[/bold]: {len(evaluable)} / {len(qa_set)} questions "
        f"have source_hint (top_k={top_k})\n"
    )

    results = []
    for item in evaluable:
        qid      = item["id"]
        question = item["question"]
        hint     = item["source_hint"]
        category = item["category"]

        console.print(f"[dim]{qid}[/dim] {question[:70]}", end=" … ")

        try:
            chunks = retrieve(question, top_k=top_k)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
            results.append({"id": qid, "error": str(exc)})
            continue

        hit      = any(_chunk_matches_hint(c, hint) for c in chunks)
        rr       = reciprocal_rank(chunks, hint)
        avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks) if chunks else 0
        top_sources = [
            f"{c['metadata'].get('source','?')}/{c['metadata'].get('section') or c['metadata'].get('type','?')}"
            for c in chunks[:3]
        ]

        console.print(
            f"hit=[{'green' if hit else 'red'}]{'✓' if hit else '✗'}[/]  "
            f"rr={rr:.2f}  avg_score={avg_score:.3f}"
        )

        results.append({
            "id":          qid,
            "category":    category,
            "question":    question,
            "source_hint": hint,
            "hit":         hit,
            "rr":          round(rr, 4),
            "avg_score":   round(avg_score, 4),
            "top_sources": top_sources,
        })

    if not results:
        console.print("[red]No results — is chroma_db populated?[/red]")
        sys.exit(1)

    _print_table(results)
    metrics = _compute_metrics(results)
    _print_summary(metrics)
    _write_results(results, metrics, out_path)


def _compute_metrics(results: list[dict]) -> dict:
    valid = [r for r in results if "error" not in r]
    n     = len(valid)
    if n == 0:
        return {"error": "no valid results"}

    precision_at_k = sum(r["hit"] for r in valid) / n
    mrr            = sum(r["rr"]  for r in valid) / n
    avg_score      = sum(r["avg_score"] for r in valid) / n

    by_category: dict[str, dict] = {}
    for r in valid:
        cat = r["category"]
        by_category.setdefault(cat, {"n": 0, "hits": 0, "rr_sum": 0.0})
        by_category[cat]["n"]      += 1
        by_category[cat]["hits"]   += int(r["hit"])
        by_category[cat]["rr_sum"] += r["rr"]

    cat_summary = {
        cat: {
            "precision": d["hits"] / d["n"],
            "mrr":       d["rr_sum"] / d["n"],
        }
        for cat, d in by_category.items()
    }

    return {
        "n_evaluated":   n,
        "precision_at_5": round(precision_at_k, 4),
        "mrr":           round(mrr, 4),
        "avg_chunk_score": round(avg_score, 4),
        "by_category":   cat_summary,
    }


def _print_table(results: list[dict]) -> None:
    tbl = Table(title="RAG retrieval results (top-5)", show_lines=False)
    tbl.add_column("ID",       style="dim", width=4)
    tbl.add_column("Cat",      width=10)
    tbl.add_column("Hit",      width=4, justify="center")
    tbl.add_column("RR",       width=5, justify="right")
    tbl.add_column("Score",    width=6, justify="right")
    tbl.add_column("Top sources", overflow="fold")

    for r in results:
        if "error" in r:
            tbl.add_row(r["id"], "-", "[red]ERR[/red]", "-", "-", r["error"][:40])
            continue
        tbl.add_row(
            r["id"],
            r["category"],
            "[green]✓[/green]" if r["hit"] else "[red]✗[/red]",
            f"{r['rr']:.2f}",
            f"{r['avg_score']:.3f}",
            " | ".join(r["top_sources"]),
        )

    console.print(tbl)


def _print_summary(metrics: dict) -> None:
    console.print("\n[bold]── RAG Summary ────────────────────────[/bold]")
    console.print(f"  Precision@5  : {metrics['precision_at_5']:.1%}")
    console.print(f"  MRR          : {metrics['mrr']:.3f}")
    console.print(f"  Avg score    : {metrics['avg_chunk_score']:.3f}")
    console.print()


def _write_results(results: list[dict], metrics: dict, out_path: str) -> None:
    output = {
        "run_at":  datetime.utcnow().isoformat() + "Z",
        "metrics": metrics,
        "results": results,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    console.print(f"[dim]Saved to {out_path}[/dim]")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="RAG retrieval quality eval")
    parser.add_argument("--golden",  default="golden_qa.json")
    parser.add_argument("--out",     default="rag_metrics.json")
    parser.add_argument("--rag-dir", default=None,
                        help="Override CHROMA_PERSIST_DIR")
    parser.add_argument("--top-k",   type=int, default=5)
    args = parser.parse_args()

    run_eval(args.golden, args.out, args.rag_dir, args.top_k)


if __name__ == "__main__":
    main()
