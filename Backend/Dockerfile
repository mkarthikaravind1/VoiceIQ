FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

# libgomp1: OpenMP runtime needed by the speech models (CTranslate2 / ONNX Runtime)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only PyTorch: the default Linux wheels bundle CUDA and add several GB
COPY requirements.txt .
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY . .

EXPOSE 8000

# The first start downloads the Whisper, embedding and voice models, so allow time
HEALTHCHECK --interval=15s --timeout=5s --start-period=300s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["python", "docker_entrypoint.py"]
