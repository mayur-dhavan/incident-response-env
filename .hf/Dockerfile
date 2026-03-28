# HF Spaces deployment wrapper — built by GitHub Actions
# The package is installed from the incident_response_env/ subdirectory.

FROM python:3.11-slim

ARG PORT=7860
ENV PORT=${PORT}

WORKDIR /app

# Install dependencies (single layer — HF Spaces has no Docker layer cache between deploys)
# --retries and --timeout guard against transient network errors during build
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --retries 5 --timeout 600 -r requirements.txt

# Copy the package
COPY incident_response_env/ /app/incident_response_env/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')" || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "python -m uvicorn incident_response_env.server.app:app --host 0.0.0.0 --port ${PORT}"]
