"""
Generate docs/architecture.png using the `diagrams` library.

Prerequisites:
  brew install graphviz          # macOS
  apt-get install graphviz       # Debian/Ubuntu
  pip install diagrams Pillow

Run from the repo root:
  python docs/create_diagram.py
"""
from pathlib import Path

try:
    from diagrams import Cluster, Diagram, Edge
    from diagrams.generic.compute import Rack
    from diagrams.generic.storage import Storage
    from diagrams.onprem.client import User
    from diagrams.onprem.database import Mongodb
    from diagrams.onprem.network import Nginx
    from diagrams.programming.framework import FastApi
    from diagrams.programming.language import Python
except ImportError:
    raise SystemExit(
        "Missing dependencies.\n"
        "Run:  pip install diagrams Pillow\n"
        "And:  brew install graphviz   (macOS)\n"
        "      apt-get install graphviz  (Debian/Ubuntu)"
    )

_OUT = str(Path(__file__).parent / "architecture")

graph_attr = {
    "fontsize":  "13",
    "bgcolor":   "white",
    "pad":       "0.5",
    "splines":   "ortho",
    "nodesep":   "0.6",
    "ranksep":   "0.9",
}

node_attr = {
    "fontsize": "11",
}


def main() -> None:
    with Diagram(
        "AI Persona Architecture — Soumya",
        filename=_OUT,
        outformat="png",
        show=False,
        direction="LR",
        graph_attr=graph_attr,
        node_attr=node_attr,
    ):
        # ── Callers ──────────────────────────────────────────────────────────
        with Cluster("Callers"):
            phone   = User("Phone caller")
            browser = User("Browser chat")

        # ── Voice platform ────────────────────────────────────────────────────
        with Cluster("Voice Platform"):
            vapi = Rack("Vapi\nDeepgram STT\nElevenLabs TTS")

        # ── Chat UI ───────────────────────────────────────────────────────────
        with Cluster("Chat UI  :3000"):
            ui = Nginx("Next.js 14\nApp Router + SSE")

        # ── persona-api ───────────────────────────────────────────────────────
        with Cluster("persona-api  :8000"):
            api = FastApi("FastAPI\n/chat  /voice-webhook\n/book-meeting")

        # ── RAG pipeline ──────────────────────────────────────────────────────
        with Cluster("RAG Pipeline"):
            chroma = Mongodb("ChromaDB\ncosine · 1536-dim")
            ingest = Python("rag-ingest\nresume PDF\nGitHub repos")

        # ── External APIs ─────────────────────────────────────────────────────
        with Cluster("External APIs"):
            claude = Rack("Claude Sonnet\n(Anthropic)")
            gcal   = Storage("Google Calendar\n+ Gmail API")

        # ── Edges ─────────────────────────────────────────────────────────────
        phone   >> Edge(label="phone call")          >> vapi
        browser >> Edge(label="HTTP / SSE")          >> ui

        vapi >> Edge(label="assistant-request\nfunction-call webhook") >> api
        ui   >> Edge(label="POST /chat\nPOST /book")                  >> api

        api >> Edge(label="embed + query top-5") >> chroma
        api >> Edge(label="generate (grounded)")  >> claude
        api >> Edge(label="create event")         >> gcal

        ingest >> Edge(
            label="upsert vectors",
            style="dashed",
            color="gray",
        ) >> chroma

    print(f"Diagram written to {_OUT}.png")


if __name__ == "__main__":
    main()
