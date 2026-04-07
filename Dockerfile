FROM public.ecr.aws/docker/library/python:3.11-slim

ARG PORT=7860
ENV PORT=${PORT}

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "openenv-core[core]>=0.2.1" \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.24.0" \
    "pydantic>=2.0.0" \
    "openai>=1.0.0"

# Copy source — package root is the repo root
COPY __init__.py models.py client.py baseline.py demo.py inference.py ./
COPY server/ ./server/
COPY openenv.yaml pyproject.toml ./

# Install as editable package so imports resolve correctly
RUN pip install --no-cache-dir -e . --no-deps

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')" || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn incident_response_env.server.app:app --host 0.0.0.0 --port ${PORT}"]
