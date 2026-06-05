"""
Vapi webhook router — delegates to voice_webhook.py handlers.

Message types:
  assistant-request   → dynamic RAG injection into system prompt
  function-call       → check_availability / book_meeting
  end-of-call-report  → log + persist call record for evals
  status-update / transcript / speech-update → acknowledged silently
"""
import logging

from fastapi import APIRouter, Request

import voice_webhook

router = APIRouter()
log    = logging.getLogger("persona-api")


@router.post("/voice-webhook")
async def vapi_webhook(request: Request) -> dict:
    body     = await request.json()
    message  = body.get("message", {})
    msg_type = message.get("type", "")

    if msg_type == "assistant-request":
        return voice_webhook.handle_assistant_request(message)

    if msg_type == "function-call":
        return await voice_webhook.handle_function_call(message)

    if msg_type == "end-of-call-report":
        voice_webhook.handle_end_of_call(body)
        return {"status": "ok"}

    # status-update, transcript, speech-update — acknowledge silently
    log.debug(f"voice-webhook: ignoring type={msg_type!r}")
    return {"status": "ok"}
