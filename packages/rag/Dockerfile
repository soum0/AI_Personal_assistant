FROM python:3.11-slim
WORKDIR /app
# chromadb needs build tools for its native extensions
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Pre-download the embedding model so production startup needs no internet access
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
COPY . .
CMD ["python", "ingest.py"]
