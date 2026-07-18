FROM python:3.10-slim

# Install only the system packages needed at serve time.
# build-essential is kept for packages that compile C extensions (e.g. psycopg).
# git is removed — no VCS operations at serve time.
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------------------------
# Environment flags
# ---------------------------------------------------------------------------
# CUDA_VISIBLE_DEVICES="" — force CPU mode; prevents PyTorch CUDA init hangs
ENV CUDA_VISIBLE_DEVICES=""
ENV PYTHONUNBUFFERED=1
# TOKENIZERS_PARALLELISM=false — prevents Rust tokenizer deadlocks inside
#   gVisor (Cloud Run sandboxed kernel).
ENV TOKENIZERS_PARALLELISM=false
# HF_HOME is kept to silence any HF cache path warnings.
ENV HF_HOME=/app/.cache/huggingface
ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed

# ---------------------------------------------------------------------------
# Python dependencies — production-only (no torch / sentence-transformers)
# ---------------------------------------------------------------------------
COPY requirements.prod.txt .

# Use requirements.prod.txt instead of requirements.txt (DEC-036).
RUN pip install --no-cache-dir -r requirements.prod.txt

# Pre-download FastEmbed model weights during building to bake them into the image.
# This ensures zero runtime network request and fast startup.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-base-en-v1.5')"

# Set offline flags at runtime after the downloads are completed.
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1


# ---------------------------------------------------------------------------
# Application source
# NOTE: .dockerignore excludes: data/, recruiter/models/, .venv/, tests/,
#       notebooks/, baseline/, graphify-out/, docs/, scripts/, reports/,
#       run_reports/, scratch/, mlruns/, logs/, .env*, *.log
# ---------------------------------------------------------------------------
COPY . .

# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------
# Expose 7860 as documentation; Cloud Run overrides with $PORT at runtime.
EXPOSE 7860

# Run uvicorn on the dynamic $PORT provided by Cloud Run (fallback: 7860).
CMD ["sh", "-c", "python -m uvicorn recruiter.src.api.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
