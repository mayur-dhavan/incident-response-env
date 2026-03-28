# HF Spaces deployment wrapper — built by GitHub Actions
# The package is installed from the incident_response_env/ subdirectory.

FROM python:3.11-slim

ARG PORT=7860
ENV PORT=${PORT}

WORKDIR /app

# ── Stage 1: install heavy base deps first (separate layer for Docker cache) ──
# openenv-core brings in gradio/fastmcp/numpy — install alone with long timeout
# so Docker can cache this layer and reruns only reinstall if this changes.
RUN pip install --no-cache-dir --retries 10 --timeout 300 \
    "openenv-core>=0.2.1"

# ── Stage 2: install remaining lightweight runtime deps ──
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 120 -r requirements.txt

# ── Stage 3: copy application code ──
COPY incident_response_env/ /app/incident_response_env/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')" || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "python -m uvicorn incident_response_env.server.app:app --host 0.0.0.0 --port ${PORT}"]
