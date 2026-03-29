# HF Spaces deployment wrapper — built by GitHub Actions
# All source files live at HF Space root (flat layout).
# The Dockerfile reconstructs the Python package hierarchy inside the container
# so that relative imports (from ..models, from .environment) still work.

FROM python:3.11-slim

ARG PORT=7860
ENV PORT=${PORT}

WORKDIR /app

# Install dependencies using uv (10-100x faster than pip for resolution + install)
# HF Spaces has no Docker layer cache between deploys, so speed matters.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY requirements.txt ./requirements.txt
RUN uv pip install --system --no-cache-dir -r requirements.txt

# Reconstruct the incident_response_env package inside the container
# from the flat files at HF Space root.
COPY __init__.py models.py baseline.py client.py demo.py /app/incident_response_env/
COPY server/ /app/incident_response_env/server/

# The source __init__.py eagerly imports IncidentEnv (the HTTP *client*),
# which pulls in openenv.core.EnvClient → gradio chain.  The server only
# needs the models, so override with a minimal init.
RUN printf 'from .models import IncidentAction, IncidentObservation, IncidentState\n__all__ = ["IncidentAction", "IncidentObservation", "IncidentState"]\n' \
    > /app/incident_response_env/__init__.py

# Fail-fast: verify the import works at build time (gives a real traceback)
RUN python -c "from incident_response_env.server.app import app; print('Import OK')"

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')" || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "python -m uvicorn incident_response_env.server.app:app --host 0.0.0.0 --port ${PORT}"]
