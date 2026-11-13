# DocuLens: website, API, OCR models and Tesseract in one image.
#   docker build -t doculens .
#   docker run -p 8000:8000 doculens        then open http://localhost:8000

# --- Website -----------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Application -------------------------------------------------------------
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

# Tesseract is the optional fallback reader; libgomp and libglib are runtime
# libraries needed by ONNX Runtime and OpenCV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/doculens

# Dependencies first, so code changes do not reinstall them.
COPY backend/pyproject.toml ./backend/
RUN mkdir -p backend/app && touch backend/app/__init__.py \
    && pip install ./backend \
    && rm -rf backend

COPY backend/ ./backend/
COPY models/ ./models/
COPY --from=frontend /build/dist ./frontend/dist

# Model locations inside the image. Hosts and origins default to localhost;
# override them for a public address (see docker-compose.yml).
ENV DOCULENS_OCR_MODELS_DIR=/opt/doculens/models/ocr \
    DOCULENS_OCR_MEDIUM_DET_PATH=/opt/doculens/models/ocr/medium-det/inference.onnx \
    DOCULENS_OCR_MEDIUM_REC_PATH=/opt/doculens/models/ocr/medium-rec/inference.onnx \
    DOCULENS_OCR_FAST_TEXT=true \
    DOCULENS_SEMANTIC_MODELS_DIR=/opt/doculens/models/semantic \
    DOCULENS_ENABLE_TESSERACT_BACKUP=true

RUN useradd --create-home --uid 10001 doculens
USER doculens
WORKDIR /opt/doculens/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import json, urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health'))['ocr_ready']"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
