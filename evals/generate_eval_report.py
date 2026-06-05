"""
Generate the 1-page PDF evaluation report for the AI Persona assignment.

Reads (all optional — missing files produce "N/A" placeholders):
  results.json        — from eval_chat.py
  voice_results.json  — from eval_voice_latency.py
  rag_metrics.json    — from eval_rag.py

Outputs:
  eval_report.pdf     (or --out path)

Usage:
  python generate_eval_report.py
  python generate_eval_report.py --out /path/to/report.pdf
    python generate_eval_report.py --name "Soumya"
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:
    raise SystemExit(
        "reportlab is required: pip install reportlab"
    )

# ── Colour palette ─────────────────────────────────────────────────────────────
_NAVY   = colors.HexColor("#1e3a5f")
_TEAL   = colors.HexColor("#0d9488")
_LIGHT  = colors.HexColor("#f0f4f8")
_PASS   = colors.HexColor("#16a34a")
_FAIL   = colors.HexColor("#dc2626")
_GREY   = colors.HexColor("#6b7280")


# ── Data loading ───────────────────────────────────────────────────────────────

def _load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _fmt(val, fmt=".1%", fallback="N/A"):
    if val is None:
        return fallback
    try:
        return format(val, fmt)
    except Exception:
        return str(val)


# ── Style helpers ──────────────────────────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Normal"],
            fontSize=18, textColor=_NAVY, fontName="Helvetica-Bold",
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"],
            fontSize=9, textColor=_GREY, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Normal"],
            fontSize=10, textColor=_NAVY, fontName="Helvetica-Bold",
            spaceBefore=8, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontSize=8.5, leading=12, spaceAfter=2,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"],
            fontSize=8.5, leading=11, leftIndent=10, spaceAfter=1,
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"],
            fontSize=7.5, textColor=_GREY, spaceAfter=0,
        ),
    }


def _metric_table(rows: list[tuple[str, str]], col_widths=(7*cm, 5*cm)) -> Table:
    tbl = Table(rows, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _LIGHT),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
        ("GRID",       (0, 0), (-1, -1), 0.4, _GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    return tbl


# ── Content builders ───────────────────────────────────────────────────────────

def _build_chat_section(chat: dict, s: dict) -> list:
    m = chat.get("metrics", {})
    elems = [
        Paragraph("2 · Chat Groundedness", s["h2"]),
    ]
    rows = [
        ("Metric", "Value"),
        ("Overall accuracy",  _fmt(m.get("overall_accuracy"), ".1%")),
        ("Hallucination rate", _fmt(m.get("hallucination_rate"), ".1%")),
        ("Correct refusal rate", _fmt(m.get("refusal_rate"), ".1%")),
        ("Avg latency",       _fmt(m.get("avg_latency_ms"), ".0f") + " ms"
         if m.get("avg_latency_ms") else "N/A"),
    ]
    elems.append(_metric_table(rows))

    # Per-category breakdown
    by_cat = m.get("by_category", {})
    if by_cat:
        cat_rows = [("Category", "Accuracy", "Avg latency")]
        for cat, stats in by_cat.items():
            cat_rows.append((
                cat.capitalize(),
                _fmt(stats.get("accuracy"), ".0%"),
                _fmt(stats.get("avg_latency_ms"), ".0f") + " ms"
                if stats.get("avg_latency_ms") else "N/A",
            ))
        cat_tbl = Table(cat_rows, colWidths=[4*cm, 3*cm, 4*cm])
        cat_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _LIGHT),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 8),
            ("GRID",       (0, 0), (-1, -1), 0.4, _GREY),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ]))
        elems.append(Spacer(1, 4))
        elems.append(cat_tbl)

    return elems


def _build_voice_section(voice: dict, s: dict) -> list:
    m = voice.get("metrics", {})
    elems = [Paragraph("1 · Voice Quality", s["h2"])]
    rows = [
        ("Metric", "Value"),
        ("Avg first-response latency",
         (_fmt(m.get("avg_first_response_latency_s"), ".2f") + "s")
         if m.get("avg_first_response_latency_s") is not None else "N/A"),
        ("Calls under 2 s target",
         _fmt(m.get("pct_under_2s"), ".0%")),
        ("Topic accuracy (transcription)",
         _fmt(m.get("topic_accuracy"), ".0%")),
    ]
    elems.append(_metric_table(rows))
    return elems


def _build_rag_section(rag: dict, s: dict) -> list:
    m = rag.get("metrics", {})
    elems = [Paragraph("3 · RAG Retrieval Quality", s["h2"])]
    rows = [
        ("Metric", "Value"),
        ("Precision@5",    _fmt(m.get("precision_at_5"), ".1%")),
        ("MRR",            _fmt(m.get("mrr"), ".3f")),
        ("Avg chunk score", _fmt(m.get("avg_chunk_score"), ".3f")),
    ]
    elems.append(_metric_table(rows))
    return elems


def _build_failure_modes(s: dict) -> list:
    failures = [
        "<b>Sparse RAG context for GitHub questions</b> — When repos haven't been "
        "ingested or READMEs are thin, the persona falls back to 'I don't have that "
        "information' instead of a specific answer. Fix: richer repo ingestion + "
        "on-demand GitHub API fetch.",
        "<b>Booking ambiguity in voice</b> — If the caller doesn't provide a slot ISO "
        "string, book_meeting fails silently. Fix: add a confirm-slot dialog turn before "
        "calling the tool.",
        "<b>Latency spikes on cold start</b> — First chat response after container start "
        "can exceed 3 s (ChromaDB loading + OpenAI embed round-trip). Fix: warm-up "
        "request in the Docker HEALTHCHECK.",
    ]
    elems = [Paragraph("4 · Failure Modes", s["h2"])]
    for f in failures:
        elems.append(Paragraph(f"• {f}", s["bullet"]))
    return elems


def _build_tradeoff(s: dict) -> list:
    text = (
        "<b>ChromaDB (local) vs. managed vector DB</b> — ChromaDB runs in-process with "
        "no network hop, which keeps median RAG latency under 80 ms. The tradeoff is that "
        "it doesn't scale horizontally and requires a shared bind-mount across containers. "
        "For production, Pinecone or Qdrant Cloud would replace it with zero ops overhead "
        "at the cost of ~20–40 ms extra latency."
    )
    return [
        Paragraph("5 · Key Tradeoff", s["h2"]),
        Paragraph(text, s["body"]),
    ]


def _build_next(s: dict) -> list:
    items = [
        "Streaming voice with barge-in detection via Deepgram interim transcripts",
        "Conversation memory: persist per-caller session context across multiple calls",
        "Retrieval re-ranker (cross-encoder) to improve precision on behavioral questions",
        "CI eval gate: run eval_chat.py on every PR and fail if hallucination_rate > 15%",
    ]
    elems = [Paragraph("6 · What I'd Build Next", s["h2"])]
    for item in items:
        elems.append(Paragraph(f"• {item}", s["bullet"]))
    return elems


def _build_cost_footer(s: dict) -> list:
    text = (
        "Cost estimate (per 100 calls): Vapi ≈ $0.05/min × 5 min avg = $25 | "
        "ElevenLabs ≈ $0.30/1k chars × 500 chars/call = $15 | "
        "OpenAI embed ≈ $0.001 | Anthropic claude-sonnet ≈ $0.15/call = $15 | "
        "<b>Total ≈ $55 / 100 calls</b>"
    )
    return [
        HRFlowable(width="100%", thickness=0.5, color=_GREY),
        Spacer(1, 3),
        Paragraph(text, s["small"]),
    ]


# ── Main ───────────────────────────────────────────────────────────────────────

def build_report(
    name: str,
    chat_path: str,
    voice_path: str,
    rag_path: str,
    out_path: str,
) -> None:
    chat  = _load(chat_path)
    voice = _load(voice_path)
    rag   = _load(rag_path)

    s = _styles()

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
    )

    story: list = []

    # ── Header ─────────────────────────────────────────────────────────────────
    story.append(Paragraph(f"AI Persona Eval Report — {name}", s["title"]))
    story.append(Paragraph(
        f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC  •  "
        f"claude-sonnet-4-20250514 as judge",
        s["subtitle"],
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_TEAL))
    story.append(Spacer(1, 6))

    # ── Sections (two-column layout via a wide Table) ──────────────────────────
    left_col  = []
    right_col = []

    if voice:
        left_col += _build_voice_section(voice, s)
    else:
        left_col += [Paragraph("1 · Voice Quality", s["h2"]),
                     Paragraph("Run eval_voice_latency.py to populate.", s["small"])]

    left_col += [Spacer(1, 4)]

    if chat:
        left_col += _build_chat_section(chat, s)
    else:
        left_col += [Paragraph("2 · Chat Groundedness", s["h2"]),
                     Paragraph("Run eval_chat.py to populate.", s["small"])]

    if rag:
        right_col += _build_rag_section(rag, s)
    else:
        right_col += [Paragraph("3 · RAG Retrieval Quality", s["h2"]),
                      Paragraph("Run eval_rag.py to populate.", s["small"])]

    right_col += [Spacer(1, 4)]
    right_col += _build_failure_modes(s)

    # Pad the shorter column so the table cells align
    max_len = max(len(left_col), len(right_col))
    left_col  += [Spacer(1, 1)] * (max_len - len(left_col))
    right_col += [Spacer(1, 1)] * (max_len - len(right_col))

    col_width = (A4[0] - 3.6*cm) / 2
    two_col = Table(
        [[left_col, right_col]],
        colWidths=[col_width, col_width],
    )
    two_col.setStyle(TableStyle([
        ("VALIGN",  (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    story.append(two_col)
    story.append(Spacer(1, 6))

    # ── Full-width bottom sections ─────────────────────────────────────────────
    story += _build_tradeoff(s)
    story += [Spacer(1, 2)]
    story += _build_next(s)
    story += [Spacer(1, 4)]
    story += _build_cost_footer(s)

    doc.build(story)
    print(f"Report written to {out_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 1-page PDF eval report")
    parser.add_argument("--name",        default=os.getenv("PERSONA_NAME", "Kanishk Krishna"))
    parser.add_argument("--chat",        default="results.json")
    parser.add_argument("--voice",       default="voice_results.json")
    parser.add_argument("--rag",         default="rag_metrics.json")
    parser.add_argument("--out",         default="eval_report.pdf")
    args = parser.parse_args()

    build_report(args.name, args.chat, args.voice, args.rag, args.out)


if __name__ == "__main__":
    main()
