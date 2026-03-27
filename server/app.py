"""
FastAPI application.

Standard OpenEnv endpoints (provided by create_app):
  POST /reset
  POST /step
  GET  /state
  GET  /health
  GET  /schema
  WS   /ws

Hackathon-required extra endpoints:
  GET  /tasks    — list tasks with action schema
  POST /grader   — score the current (or a completed) episode
  POST /baseline — run the rule-based baseline agent, return all 3 scores
"""

from __future__ import annotations

import copy
from typing import Any

from fastapi import HTTPException
from openenv.core.env_server.http_server import create_app
from pydantic import BaseModel

from ..models import IncidentAction, IncidentObservation, IncidentState
from .environment import IncidentEnvironment
from .graders import grade
from .scenarios import ALL_TASKS

# ──────────────────────────────────────────────
# Shared environment instance
# The factory always returns the same instance so /grader and /state
# can read episode state after /reset + /step calls.
# ──────────────────────────────────────────────
_shared_env = IncidentEnvironment()


def _env_factory() -> IncidentEnvironment:
    """Factory returned to create_app for session management."""
    return _shared_env


# Build the base OpenEnv app (provides /reset /step /state /health /schema /ws)
app = create_app(_env_factory, IncidentAction, IncidentObservation, env_name="incident-response-env")

# Override /state to return full IncidentState (base only returns episode_id, step_count)
# We remove the original route and add our own.
app.routes[:] = [r for r in app.routes if not (hasattr(r, "path") and r.path == "/state")]


@app.get("/state", response_model=IncidentState)
def get_full_state() -> IncidentState:
    """Return the full episode state including custom fields for grader use."""
    return _shared_env.state


# ──────────────────────────────────────────────
# Pydantic models for extra endpoints
# ──────────────────────────────────────────────

class GraderRequest(BaseModel):
    task_id: str | None = None  # if None, uses current episode task


class BaselineResponse(BaseModel):
    task_id: str
    title: str
    difficulty: str
    score: float
    steps_taken: int
    system_restored: bool


# ──────────────────────────────────────────────
# GET /tasks
# ──────────────────────────────────────────────

@app.get("/tasks")
def get_tasks() -> dict[str, Any]:
    """
    Return all available tasks and the action schema.
    Required by the hackathon pre-submission checklist.
    """
    tasks = [
        {
            "task_id":    t["task_id"],
            "title":      t["title"],
            "difficulty": t["difficulty"],
            "description": t["description"],
            "max_steps":  t["max_steps"],
        }
        for t in ALL_TASKS
    ]

    action_schema = {
        "action_type": {
            "type": "string",
            "required": True,
            "enum": [
                "read_logs",
                "check_metrics",
                "restart_service",
                "rollback",
                "exec_command",
                "check_network",
            ],
            "description": "The type of action to execute",
        },
        "target": {
            "type": "string",
            "required": True,
            "description": (
                "Service name (for read_logs / check_metrics / restart_service / rollback / check_network) "
                "or command string (for exec_command).  "
                "Valid services: api-server, postgres, redis, worker, nginx, all"
            ),
        },
        "parameters": {
            "type": "object",
            "required": False,
            "description": "Optional extra parameters.  E.g. {\"lines\": 50} for read_logs.",
        },
    }

    return {"tasks": tasks, "action_schema": action_schema}


# ──────────────────────────────────────────────
# POST /grader
# ──────────────────────────────────────────────

@app.post("/grader")
def get_grader_score(request: GraderRequest | None = None) -> dict[str, Any]:
    """
    Grade the current (active) episode and return the score.
    Optionally pass task_id to verify which task is being scored.
    """
    state = _shared_env.state

    if not state.task_id:
        raise HTTPException(status_code=400, detail="No active episode.  Call /reset first.")

    if request and request.task_id and request.task_id != state.task_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Requested task_id '{request.task_id}' does not match "
                f"active task '{state.task_id}'."
            ),
        )

    score = grade(state)

    return {
        "task_id":              state.task_id,
        "score":                score,
        "episode_id":           state.episode_id,
        "step_count":           state.step_count,
        "root_cause_identified": state.root_cause_identified,
        "fix_applied":          state.fix_applied,
        "system_restored":      state.system_restored,
    }


# ──────────────────────────────────────────────
# POST /baseline
# ──────────────────────────────────────────────

@app.post("/baseline")
def run_baseline() -> dict[str, Any]:
    """
    Run a deterministic rule-based baseline agent against all 3 tasks.
    Returns reproducible scores for the pre-submission checklist.

    The baseline agent follows a simple policy:
      Task 1: read api-server logs → restart api-server
      Task 2: check worker metrics → check worker logs → rollback worker
      Task 3: check postgres metrics → read postgres logs →
              exec ALTER SYSTEM SET max_connections = 200 →
              exec pg_reload_conf
    """
    results: list[dict[str, Any]] = []

    from .scenarios import TASK_MAP

    policies: dict[str, list[IncidentAction]] = {
        "task_1_oom": [
            IncidentAction(action_type="read_logs",       target="api-server"),
            IncidentAction(action_type="restart_service", target="api-server"),
        ],
        "task_2_leak": [
            IncidentAction(action_type="check_metrics", target="worker"),
            IncidentAction(action_type="read_logs",     target="worker"),
            IncidentAction(action_type="rollback",      target="worker"),
        ],
        "task_3_cascade": [
            IncidentAction(action_type="check_metrics",  target="postgres"),
            IncidentAction(action_type="read_logs",      target="postgres"),
            IncidentAction(action_type="exec_command",   target="ALTER SYSTEM SET max_connections = 200"),
            IncidentAction(action_type="exec_command",   target="SELECT pg_reload_conf()"),
        ],
    }

    # Use a fresh environment per task so they don't bleed into each other
    for task in ALL_TASKS:
        task_id = task["task_id"]
        tmp_env = IncidentEnvironment()
        tmp_env.reset(task_id=task_id)

        for action in policies[task_id]:
            obs = tmp_env.step(action)
            if obs.done:
                break

        final_state = tmp_env.state
        final_score = grade(final_state)

        results.append({
            "task_id":         task_id,
            "title":           task["title"],
            "difficulty":      task["difficulty"],
            "score":           final_score,
            "steps_taken":     final_state.step_count,
            "system_restored": final_state.system_restored,
        })

    average = round(sum(r["score"] for r in results) / len(results), 4)

    return {
        "baseline_scores": results,
        "average_score":   average,
        "agent":           "rule-based-baseline-v1",
    }


# ──────────────────────────────────────────────
# Entry point for openenv validate / direct execution
# ──────────────────────────────────────────────

def main(host: str = "0.0.0.0", port: int = 7860) -> None:
    """Entry point for direct execution via uv run or python -m.

    Enables:
        uv run server
        uv run server --port 8001
    Port default is 7860 to match HF Spaces requirements.
    Override via PORT env var: PORT=8000 uv run server
    """
    import os
    import uvicorn
    port = int(os.environ.get("PORT", str(port)))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
