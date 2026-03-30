# HF Spaces deployment wrapper — built by GitHub Actions
# Flat repo layout: all source files at root, Dockerfile recreates package structure.

FROM python:3.11-slim

ARG PORT=7860
ENV PORT=${PORT}

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Recreate package structure from flat layout
COPY __init__.py models.py client.py baseline.py demo.py /app/incident_response_env/
COPY server/ /app/incident_response_env/server/

# Hackathon validation files stay at /app root
COPY inference.py openenv.yaml pyproject.toml /app/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')" || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "python -m uvicorn incident_response_env.server.app:app --host 0.0.0.0 --port ${PORT}"]
