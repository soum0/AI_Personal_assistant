"""
Comprehensive Vapi webhook handler.

Message types handled:
  assistant-request   — dynamically inject RAG context at call start
  function-call       — execute check_availability / book_meeting
  end-of-call-report  — log call outcome and persist transcript for evals
  status-update       — acknowledged silently
  transcript          — acknowledged silently
"""
import json
import logging
import os

log = logging.getLogger("persona-api")

PERSONA_NAME       = os.getenv("PERSONA_NAME", "Soumya")
_DEFAULT_RAG_QUERY = (
    f"{PERSONA_NAME} background experience skills projects "
    "education AI engineer Scaler role"
)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()
LLM_MODEL    = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")

# ── System prompt template ────────────────────────────────────────────────────
# {rag_context} is filled in per call so each caller gets accurate, fresh context.

_VOICE_SYSTEM_TEMPLATE = """\
You are {name}'s AI representative on a phone call.
Keep responses under 3 sentences for voice.

Retrieved context:
{rag_context}

If asked something not in the context above, say "{name} hasn't briefed me on that specifically, but I can have him follow up."
Never make up facts about {name}.
For scheduling, use the check_availability and book_meeting tools.\
"""


def _build_system_prompt(rag_context: str) -> str:
    return _VOICE_SYSTEM_TEMPLATE.format(
        name=PERSONA_NAME,
        rag_context=rag_context or "No context available — answer honestly that you don't have that detail.",
    )


# ── Tool definitions (sent inline for assistant-request fallback) ─────────────

def _tool_definitions() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name":        "check_availability",
                "description": "Check Soumya's calendar for free interview slots.",
                "parameters": {
                    "type":       "object",
                    "properties": {
                        "days_ahead": {
                            "type":        "integer",
                            "description": "How many days ahead to check (default 7).",
                            "default":     7,
                        }
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name":        "book_meeting",
                "description": "Book a confirmed meeting slot with Soumya.",
                "parameters": {
                    "type":       "object",
                    "properties": {
                        "slot_iso": {
                            "type":        "string",
                            "description": "ISO 8601 datetime, e.g. 2026-06-10T14:00:00+05:30.",
                        },
                        "name": {
                            "type":        "string",
                            "description": "Caller's full name.",
                        },
                        "email": {
                            "type":        "string",
                            "description": "Caller's email address for the calendar invite.",
                        },
                    },
                    "required": ["slot_iso", "name", "email"],
                },
            },
        },
    ]


# ── assistant-request ─────────────────────────────────────────────────────────

def handle_assistant_request(message: dict) -> dict:
    """
    Called when an inbound call arrives.
    Retrieves baseline RAG context and injects it into the system prompt.

    If VAPI_ASSISTANT_ID is set, responds with assistantOverrides so we
    only override the system prompt while keeping the rest of the assistant
    config managed in the Vapi dashboard.

    If not set, returns a full inline assistant object.
    """
    call     = message.get("call", {})
    call_id  = call.get("id", "unknown")
    caller   = call.get("customer", {}).get("number", "unknown")
    log.info(f"assistant-request  call_id={call_id}  caller={caller}")

    rag_context = _fetch_baseline_context()
    system_prompt = _build_system_prompt(rag_context)

    assistant_id = os.getenv("VAPI_ASSISTANT_ID", "")
    webhook_url  = os.getenv("PERSONA_API_URL", "")

    if assistant_id:
        # Minimal override — only replaces the system prompt; voice/tools stay
        # as configured in the Vapi dashboard.
        return {
            "assistantId": assistant_id,
            "assistantOverrides": {
                "model": {
                    "provider":    LLM_PROVIDER,
                    "model":       LLM_MODEL,
                    "systemPrompt": system_prompt,
                }
            },
        }

    # Fallback: full inline assistant (useful before setup_vapi.py has been run)
    log.warning("VAPI_ASSISTANT_ID not set — returning inline assistant config")
    return {
        "assistant": {
            "name": f"{PERSONA_NAME}'s AI Representative",
            "transcriber": {
                "provider": "deepgram",
                "model":    "nova-2",
                "language": "en",
            },
            "model": {
                "provider":    LLM_PROVIDER,
                "model":       LLM_MODEL,
                "temperature": 0.4,
                "systemPrompt": system_prompt,
                "tools":       _tool_definitions(),
            },
            "voice": {
                "provider":        "11labs",
                "voiceId":         "adam",
                "stability":       0.5,
                "similarityBoost": 0.75,
            },
            "firstMessage": (
                f"Hi! I'm {PERSONA_NAME}'s AI representative. "
                f"{PERSONA_NAME} asked me to handle their initial screening calls. "
                "What would you like to know about his background, or shall we find a time to meet?"
            ),
            "serverUrl":              f"{webhook_url}/voice-webhook",
            "endCallFunctionEnabled": True,
            "recordingEnabled":       True,
            "maxDurationSeconds":     600,
            "silenceTimeoutSeconds":  30,
        }
    }


def _fetch_baseline_context() -> str:
    try:
        from rag_client import retrieve
        chunks = retrieve(_DEFAULT_RAG_QUERY, top_k=6)
        return "\n\n".join(
            f"[{c['metadata'].get('section', 'general')}]\n{c['text']}"
            for c in chunks
        )
    except Exception as exc:
        log.error(f"Baseline RAG retrieval failed: {exc}")
        return ""


# ── function-call ─────────────────────────────────────────────────────────────

async def handle_function_call(message: dict) -> dict:
    fn     = message.get("functionCall", {})
    name   = fn.get("name", "")
    params = fn.get("parameters", {})

    log.info(f"function-call: {name}  params={params}")

    try:
        if name == "check_availability":
            return {"result": _format_slots(int(params.get("days_ahead", 7)))}
        if name == "book_meeting":
            return {"result": _do_book(params)}
        log.warning(f"Unknown function: {name}")
        return {"result": f"I don't have a '{name}' capability."}
    except Exception as exc:
        log.error(f"Function '{name}' failed: {exc}", exc_info=True)
        return {"result": "Sorry, I ran into a problem completing that. Please try again."}


def _format_slots(days_ahead: int = 7) -> str:
    from calendar_service import get_available_slots
    # days_ahead is accepted but calendar_service always returns 7-day window
    slots = get_available_slots()
    if not slots:
        return (
            "I don't have any open slots in the next 7 days. "
            "Please suggest a time and I'll have Kanishk check manually."
        )
    lines = "\n".join(s["label"] for s in slots[:6])
    return f"Available slots:\n{lines}\nWhich one works best for you?"


def _do_book(params: dict) -> str:
    from calendar_service import book_meeting
    result = book_meeting(
        slot_iso       = params.get("slot_iso", ""),
        attendee_email = params.get("email", ""),
        attendee_name  = params.get("name", ""),
    )
    if result["confirmed"]:
        meet     = result.get("meet_link", "")
        meet_msg = f" Your Google Meet link is {meet}." if meet else ""
        return (
            f"Done! Your meeting with {PERSONA_NAME} is confirmed.{meet_msg}"
            " You'll receive a calendar invite shortly."
        )
    return "I wasn't able to complete the booking. Please try a different slot."


# ── end-of-call-report ────────────────────────────────────────────────────────

def handle_end_of_call(body: dict) -> None:
    call      = body.get("call", {})
    call_id   = call.get("id", "unknown")
    reason    = body.get("endedReason", "unknown")
    duration  = body.get("durationSeconds", "?")
    summary   = body.get("summary", "")
    recording = body.get("recordingUrl", "")
    transcript_raw = body.get("transcript", "")

    # Detect whether a booking happened (scan assistant turns for "confirmed")
    messages = body.get("messages", [])
    booked   = any(
        "confirmed" in str(m.get("content", "")).lower()
        for m in messages
        if m.get("role") == "bot"
    )

    log.info(
        f"end-of-call  id={call_id}  reason={reason}"
        f"  duration={duration}s  booked={booked}"
    )
    if summary:
        log.info(f"call-summary [{call_id}]: {summary[:200]}")
    if recording:
        log.info(f"recording    [{call_id}]: {recording}")

    _persist_call_log({
        "call_id":     call_id,
        "reason":      reason,
        "duration_s":  duration,
        "booked":      booked,
        "summary":     summary,
        "recording":   recording,
        "transcript":  transcript_raw[:3000] if transcript_raw else "",
    })


def _persist_call_log(record: dict) -> None:
    """Append a JSONL record to the call log file (used by eval scripts)."""
    log_path = os.getenv("CALL_LOG_PATH", "/tmp/call_log.jsonl")
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        log.warning(f"Could not write call log to {log_path}: {exc}")
