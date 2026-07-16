FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV CUDA_VISIBLE_DEVICES=""
ENV PYTHONUNBUFFERED=1
ENV TOKENIZERS_PARALLELISM=false

# Copy requirements and project files
COPY requirements.txt .
COPY pyproject.toml .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model so it is baked into the image
RUN python -c "import os; os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING']='1'; from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"

ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

# Copy all source files
COPY . .

# Expose port 7860 (Hugging Face default)
EXPOSE 7860

# Run uvicorn pointing to the recruiter sandbox application, binding to dynamic $PORT for Cloud Run (fallback to 7860)
CMD ["sh", "-c", "python -m uvicorn recruiter.src.api.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
