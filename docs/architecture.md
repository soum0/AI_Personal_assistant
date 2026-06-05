# Architecture

Replace this file with an architecture diagram (PNG/SVG) before submission.

## System Overview

```
Phone call ──▶ Vapi Voice Agent
                    │ function calls (answer_question / get_availability / book_meeting)
                    ▼
Browser ───▶ persona-api (FastAPI :8000)
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
      Qdrant     OpenAI    Google Calendar
      (vector    GPT-4o-   API
       store)    mini
         ▲
    rag-ingest
    (one-shot)
    resume PDF +
    GitHub repos
```

## Data Flow

1. **Ingest** — `rag-ingest` clones GitHub repos + parses resume PDF, chunks text,
   embeds with `text-embedding-3-small`, stores vectors in Qdrant collection `persona`.

2. **Chat** — `POST /chat` embeds the user query, retrieves top-5 chunks from Qdrant,
   builds a grounded system prompt, calls GPT-4o-mini.

3. **Voice** — Vapi calls `voice-webhook` for each function call; webhook proxies to
   `persona-api` and returns the result to Vapi.

4. **Calendar** — `GET /calendar/slots` and `POST /calendar/book` hit the Google
   Calendar API (OAuth service account).
