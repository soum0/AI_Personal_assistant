import logging
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from routers.chat     import router as chat_router
from routers.calendar import router as calendar_router
from routers.voice    import router as voice_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("persona-api")

app = FastAPI(title="persona-api", version="0.2.0", docs_url="/docs")

# ── CORS ─────────────────────────────────────────────────────────────────────
import os

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request logging + request-id ─────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        log.error(f"[{request_id}] Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    log.info(
        f"[{request_id}] {request.method} {request.url.path}"
        f"  →  {response.status_code}  ({elapsed_ms:.0f}ms)"
    )
    response.headers["X-Request-ID"] = request_id
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(chat_router)
app.include_router(calendar_router)
app.include_router(voice_router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": "0.2.0"}
