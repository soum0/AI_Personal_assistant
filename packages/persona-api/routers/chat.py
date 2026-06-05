import json
import logging
import os

from openai import AsyncOpenAI, OpenAI
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()
log    = logging.getLogger("persona-api")

DEFAULT_LLM_MODEL = "llama-3.1-8b-instant"
LLM_PROVIDER      = os.getenv("LLM_PROVIDER", "groq").strip().lower()
LLM_MODEL         = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)


class Message(BaseModel):
    role:    str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message:              str
    session_id:           str           = "default"
    conversation_history: list[Message] = []
    stream:               bool          = False


class ChatResponse(BaseModel):
    response:   str
    sources:    list[str] = []
    session_id: str


def _build_context(chunks: list[dict]) -> str:
    return "\n\n---\n\n".join(
        f"[{c['metadata'].get('source', '')} / {c['metadata'].get('section', '')}]\n{c['text']}"
        for c in chunks
    )


def _format_sources(chunks: list[dict]) -> list[str]:
    """Return human-readable source labels, deduplicated."""
    seen: set[str] = set()
    out:  list[str] = []
    for c in chunks:
        m      = c["metadata"]
        source  = m.get("source", "")
        section = m.get("section", "")
        repo    = m.get("repo_name", "")
        label   = f"{source} · {section}" + (f" ({repo})" if repo else "")
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def _build_messages(req: ChatRequest) -> list[dict]:
    msgs = [
        {"role": m.role, "content": m.content}
        for m in req.conversation_history
        if m.role in ("user", "assistant")
    ]
    msgs.append({"role": "user", "content": req.message})
    return msgs


async def _stream_gen(req: ChatRequest, chunks: list[dict], system_prompt: str):
    """Async generator that yields SSE events from Groq (OpenAI-compatible) streaming."""
    sources  = _format_sources(chunks)
    client   = _create_async_client()
    messages = _build_messages(req)
    messages.insert(0, {"role": "system", "content": system_prompt})

    try:
        stream = await client.chat.completions.create(
            model      = LLM_MODEL,
            max_tokens = 1024,
            messages   = messages,
            stream     = True,
        )
        async for event in stream:
            delta = event.choices[0].delta.content
            if delta:
                yield f"data: {json.dumps({'t': delta})}\n\n"
        yield f"data: {json.dumps({'done': True, 'sources': sources})}\n\n"
    except Exception as exc:
        log.error(f"Groq streaming error: {exc}")
        yield f"data: {json.dumps({'done': True, 'sources': [], 'error': str(exc)})}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    from rag_client import retrieve
    from persona    import build_system_prompt

    try:
        chunks = retrieve(req.message, top_k=5)
    except Exception as exc:
        log.error(f"RAG retrieval failed: {exc}")
        raise HTTPException(status_code=503, detail="Knowledge base unavailable")

    context       = _build_context(chunks)
    system_prompt = build_system_prompt(context)

    if req.stream:
        log.info(f"[{req.session_id}] stream-chat  chunks={len(chunks)}")
        return StreamingResponse(
            _stream_gen(req, chunks, system_prompt),
            media_type = "text/event-stream",
            headers    = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Non-streaming path ────────────────────────────────────────
    messages = _build_messages(req)
    messages.insert(0, {"role": "system", "content": system_prompt})
    try:
        client   = _create_client()
        response = client.chat.completions.create(
            model      = LLM_MODEL,
            max_tokens = 1024,
            messages   = messages,
        )
    except Exception as exc:
        log.error(f"Groq API error: {exc}")
        raise HTTPException(status_code=502, detail="LLM unavailable")

    usage = response.usage
    if usage:
        log.info(
            f"[{req.session_id}] chat  chunks={len(chunks)}"
            f"  in={usage.prompt_tokens}  out={usage.completion_tokens}"
        )
    return ChatResponse(
        response   = response.choices[0].message.content or "",
        sources    = _format_sources(chunks),
        session_id = req.session_id,
    )


def _create_client() -> OpenAI:
    return OpenAI(
        api_key=_get_llm_api_key(),
        base_url=_get_llm_base_url(),
    )


def _create_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_get_llm_api_key(),
        base_url=_get_llm_base_url(),
    )


def _get_llm_base_url() -> str | None:
    base_url = os.getenv("LLM_BASE_URL")
    if LLM_PROVIDER == "groq" and not base_url:
        return "https://api.groq.com/openai/v1"
    return base_url


def _get_llm_api_key() -> str:
    if LLM_PROVIDER == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return api_key

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    return api_key
