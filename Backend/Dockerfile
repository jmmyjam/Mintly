FROM python:3.12-slim
WORKDIR /app

# CPU-only PyTorch first (pikachuserver has no GPU) so sentence-transformers
# doesn't drag in the multi-GB CUDA build via requirements.txt.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the CLIP model into the image so the container needs no network at
# runtime (and the first scan isn't slowed by a download). Cached under HF_HOME,
# which persists to runtime via this ENV.
ENV HF_HOME=/opt/models
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('clip-ViT-B-32')"

COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
