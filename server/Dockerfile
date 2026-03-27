# ── Stage: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim

# HF Spaces routes to this port; configurable via ENV
ARG PORT=7860
ENV PORT=${PORT}

WORKDIR /app

# Install dependencies first (cached layer)
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the whole package as incident_response_env/
COPY . /app/incident_response_env/

# Set workdir to parent so "incident_response_env" is importable as a package
WORKDIR /app

# Health check — pings the /health endpoint provided by openenv
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')" || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "python -m uvicorn incident_response_env.server.app:app --host 0.0.0.0 --port ${PORT}"]
