"""
Voice latency evaluator via Vapi's call API.

Creates 5 outbound test calls (or reads existing call logs in dry-run mode),
measures first_response_latency, and checks transcription accuracy on known phrases.

Required env vars (live mode):
  VAPI_API_KEY
  VAPI_ASSISTANT_ID
  VAPI_PHONE_NUMBER_ID
  EVAL_TEST_PHONE_NUMBER  — the phone number to dial for test calls (e.g. +15551234567)

Optional:
  CALL_LOG_PATH  — local JSONL log written by voice_webhook.py (used in dry-run mode)

Usage:
  python eval_voice_latency.py                   # live calls
  python eval_voice_latency.py --dry-run         # parse existing CALL_LOG_PATH
  python eval_voice_latency.py --calls 3         # fewer test calls
  python eval_voice_latency.py --out voice_results.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from difflib import SequenceMatcher

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

console   = Console()
VAPI_BASE = "https://api.vapi.ai"

# Test script: known caller utterances paired with expected transcript fragments
_TEST_CALLS = [
    {
        "id":           "v1",
        "label":        "Background query",
        "first_words":  "Tell me about your background and experience.",
        "expect_topic": "experience",
    },
    {
        "id":           "v2",
        "label":        "Skills query",
        "first_words":  "What is your strongest technical skill?",
        "expect_topic": "skill",
    },
    {
        "id":           "v3",
        "label":        "Availability check",
        "first_words":  "Can you check if Kanishk is available next week for a call?",
        "expect_topic": "availability",
    },
    {
        "id":           "v4",
        "label":        "GitHub project query",
        "first_words":  "What GitHub projects has Kanishk worked on?",
        "expect_topic": "project",
    },
    {
        "id":           "v5",
        "label":        "Fit question",
        "first_words":  "Why should we hire Kanishk at Scaler?",
        "expect_topic": "scaler",
    },
]


# ── Vapi helpers ──────────────────────────────────────────────────────────────

def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def create_call(
    api_key: str,
    assistant_id: str,
    phone_number_id: str,
    customer_number: str,
) -> str:
    """Create an outbound call and return the call ID."""
    resp = httpx.post(
        f"{VAPI_BASE}/call",
        headers=_headers(api_key),
        json={
            "type":          "outboundPhoneCall",
            "assistantId":   assistant_id,
            "phoneNumberId": phone_number_id,
            "customer":      {"number": customer_number},
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def poll_call(api_key: str, call_id: str, timeout_s: int = 180) -> dict:
    """Poll GET /call/{id} until status is ended or timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = httpx.get(
            f"{VAPI_BASE}/call/{call_id}",
            headers=_headers(api_key),
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") in ("ended", "failed"):
            return data
        time.sleep(5)
    raise TimeoutError(f"Call {call_id} did not end within {timeout_s}s")


# ── Latency extraction ────────────────────────────────────────────────────────

def extract_latency(call_data: dict) -> float | None:
    """
    first_response_latency = time between end of first USER utterance and
    start of first BOT response (in seconds).

    Vapi messages have a `secondsFromStart` field.
    """
    messages = call_data.get("messages", [])
    if not messages:
        return None

    # Find the first user turn (after the opening bot firstMessage)
    first_user_idx = next(
        (i for i, m in enumerate(messages) if m.get("role") == "user"),
        None,
    )
    if first_user_idx is None:
        return None

    # The bot response following that user turn
    bot_response = next(
        (m for m in messages[first_user_idx + 1:] if m.get("role") == "bot"),
        None,
    )
    if bot_response is None:
        return None

    user_msg     = messages[first_user_idx]
    user_end_s   = user_msg.get("secondsFromStart", 0) + user_msg.get("duration", 0)
    bot_start_s  = bot_response.get("secondsFromStart", user_end_s)

    latency = bot_start_s - user_end_s
    return max(0.0, round(latency, 3))


def check_transcription(call_data: dict, expect_topic: str) -> float:
    """
    Return a 0–1 similarity score: does any bot message mention the expected topic?
    """
    messages = call_data.get("messages", [])
    bot_text = " ".join(
        str(m.get("message", "")) for m in messages if m.get("role") == "bot"
    ).lower()
    return float(expect_topic.lower() in bot_text)


# ── Dry-run: read from local CALL_LOG_PATH ────────────────────────────────────

def load_call_log(path: str) -> list[dict]:
    records = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except FileNotFoundError:
        pass
    return records


def make_mock_result(spec: dict, log_record: dict | None) -> dict:
    """Build a result dict from a local call log record (dry-run)."""
    latency = None
    if log_record:
        latency = log_record.get("first_response_latency_s")

    return {
        "id":                spec["id"],
        "label":             spec["label"],
        "call_id":           log_record.get("call_id", "dry-run") if log_record else "dry-run",
        "latency_s":         latency,
        "latency_ok":        latency is not None and latency < 2.0,
        "transcription_hit": None,
        "ended_reason":      log_record.get("reason", "n/a") if log_record else "n/a",
        "note":              "dry-run — from CALL_LOG_PATH",
    }


# ── Live eval ─────────────────────────────────────────────────────────────────

def run_live(api_key: str, assistant_id: str, phone_number_id: str,
             customer_number: str, n_calls: int, out_path: str) -> None:
    tests   = _TEST_CALLS[:n_calls]
    results = []

    for spec in tests:
        console.print(f"[cyan]{spec['id']}[/cyan] {spec['label']} … creating call")
        try:
            call_id = create_call(api_key, assistant_id, phone_number_id, customer_number)
            console.print(f"  call_id={call_id}  waiting for completion (up to 3 min) …")
            call_data = poll_call(api_key, call_id)
        except Exception as exc:
            console.print(f"  [red]Failed: {exc}[/red]")
            results.append({
                "id": spec["id"], "label": spec["label"],
                "error": str(exc),
            })
            continue

        latency         = extract_latency(call_data)
        transcr_hit     = check_transcription(call_data, spec["expect_topic"])
        ended_reason    = call_data.get("endedReason", "unknown")

        icon = "✓" if (latency is not None and latency < 2.0) else "✗"
        console.print(
            f"  [{('green' if icon == '✓' else 'red')}]{icon}[/]"
            f"  latency={latency}s  topic_hit={transcr_hit:.0f}"
            f"  reason={ended_reason}"
        )

        results.append({
            "id":                spec["id"],
            "label":             spec["label"],
            "call_id":           call_id,
            "latency_s":         latency,
            "latency_ok":        latency is not None and latency < 2.0,
            "transcription_hit": transcr_hit,
            "ended_reason":      ended_reason,
        })

    _finish(results, out_path)


def run_dry(call_log_path: str, out_path: str) -> None:
    records = load_call_log(call_log_path)
    console.print(
        f"[dim]Dry-run: found {len(records)} record(s) in {call_log_path}[/dim]\n"
    )

    results = []
    for i, spec in enumerate(_TEST_CALLS):
        record = records[i] if i < len(records) else None
        results.append(make_mock_result(spec, record))
        note = results[-1]["note"]
        console.print(f"[cyan]{spec['id']}[/cyan] {spec['label']}  [{note}]")

    _finish(results, out_path)


def _finish(results: list[dict], out_path: str) -> None:
    _print_table(results)

    valid = [r for r in results if "error" not in r and r.get("latency_s") is not None]
    avg_latency  = sum(r["latency_s"] for r in valid) / len(valid) if valid else None
    under_2s     = sum(1 for r in valid if r["latency_ok"]) / len(valid) if valid else None
    transcr_acc  = (
        sum(r["transcription_hit"] for r in valid if r["transcription_hit"] is not None)
        / len([r for r in valid if r["transcription_hit"] is not None])
        if any(r.get("transcription_hit") is not None for r in valid)
        else None
    )

    metrics = {
        "n_calls":             len(results),
        "avg_first_response_latency_s": round(avg_latency, 3) if avg_latency else None,
        "pct_under_2s":        round(under_2s, 3) if under_2s is not None else None,
        "topic_accuracy":      round(transcr_acc, 3) if transcr_acc is not None else None,
    }

    console.print("\n[bold]── Voice Summary ────────────────────[/bold]")
    console.print(f"  Calls measured        : {len(valid)} / {len(results)}")
    if avg_latency is not None:
        console.print(f"  Avg first-response    : {avg_latency:.2f}s")
        console.print(f"  Under 2s target       : {under_2s:.0%}")
    if transcr_acc is not None:
        console.print(f"  Topic accuracy        : {transcr_acc:.0%}")

    output = {
        "run_at":  datetime.utcnow().isoformat() + "Z",
        "metrics": metrics,
        "results": results,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    console.print(f"\n[dim]Saved to {out_path}[/dim]")


def _print_table(results: list[dict]) -> None:
    tbl = Table(title="Voice latency results")
    tbl.add_column("ID",       style="dim", width=4)
    tbl.add_column("Label",    width=22)
    tbl.add_column("Latency",  width=10, justify="right")
    tbl.add_column("<2s",      width=5, justify="center")
    tbl.add_column("Topic",    width=6, justify="center")
    tbl.add_column("Reason",   width=14)

    for r in results:
        if "error" in r:
            tbl.add_row(r["id"], r["label"], "[red]ERROR[/red]", "-", "-", str(r["error"])[:20])
            continue
        lat    = f"{r['latency_s']:.2f}s" if r.get("latency_s") is not None else "n/a"
        ok     = "[green]✓[/green]" if r.get("latency_ok") else "[red]✗[/red]"
        topic  = (
            "[green]✓[/green]" if r.get("transcription_hit") == 1.0
            else ("[red]✗[/red]" if r.get("transcription_hit") == 0.0 else "-")
        )
        tbl.add_row(r["id"], r["label"], lat, ok, topic, r.get("ended_reason", ""))

    console.print(tbl)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Voice latency eval via Vapi")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Parse local CALL_LOG_PATH instead of making live calls")
    parser.add_argument("--calls",    type=int, default=5,
                        help="Number of test calls to make (max 5)")
    parser.add_argument("--out",      default="voice_results.json")
    args = parser.parse_args()

    if args.dry_run:
        log_path = os.getenv("CALL_LOG_PATH", "/tmp/call_log.jsonl")
        run_dry(log_path, args.out)
        return

    api_key         = os.getenv("VAPI_API_KEY")
    assistant_id    = os.getenv("VAPI_ASSISTANT_ID")
    phone_number_id = os.getenv("VAPI_PHONE_NUMBER_ID")
    customer_number = os.getenv("EVAL_TEST_PHONE_NUMBER")

    missing = [k for k, v in {
        "VAPI_API_KEY":          api_key,
        "VAPI_ASSISTANT_ID":     assistant_id,
        "VAPI_PHONE_NUMBER_ID":  phone_number_id,
        "EVAL_TEST_PHONE_NUMBER": customer_number,
    }.items() if not v]

    if missing:
        console.print(f"[red]Missing env vars: {', '.join(missing)}[/red]")
        console.print("[dim]Use --dry-run to parse existing call logs instead.[/dim]")
        raise SystemExit(1)

    run_live(api_key, assistant_id, phone_number_id, customer_number,
             min(args.calls, 5), args.out)


if __name__ == "__main__":
    main()
