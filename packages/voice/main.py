"""Vapi webhook handler — receives function-call events and proxies to persona-api."""
import os

import httpx
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="voice-webhook", version="0.1.0")

PERSONA_API = os.getenv("PERSONA_API_URL", "http://persona-api:8000")


@app.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    body = await request.json()
    message = body.get("message", {})

    if message.get("type") == "function-call":
        return await _handle_function_call(message)

    return {"status": "ok"}


async def _handle_function_call(message: dict) -> dict:
    fn = message.get("functionCall", {})
    fn_name = fn.get("name")
    params = fn.get("parameters", {})

    async with httpx.AsyncClient(timeout=15.0) as client:
        if fn_name == "answer_question":
            resp = await client.post(
                f"{PERSONA_API}/chat",
                json={"message": params.get("question", ""), "session_id": "voice"},
            )
            return {"result": resp.json().get("reply", "I'm not sure about that.")}

        if fn_name == "get_availability":
            resp = await client.get(f"{PERSONA_API}/calendar/slots")
            return {"result": resp.json()}

        if fn_name == "book_meeting":
            resp = await client.post(f"{PERSONA_API}/calendar/book", json=params)
            return {"result": resp.json()}

    return {"result": "Unknown function."}


@app.get("/health")
def health():
    return {"status": "ok"}
