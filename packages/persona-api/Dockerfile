FROM python:3.11-slim

WORKDIR /app

# build-essential  — chromadb compiles its HNSW C extension at install time
# curl             — used by Docker healthcheck (docker-compose + Fly.io)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Pre-download the embedding model so production startup needs no internet access
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

# Warm up ChromaDB on container start before accepting traffic.
# We use a single uvicorn worker to avoid concurrent writes to ChromaDB files.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info"]
