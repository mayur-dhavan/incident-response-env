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
from fastapi.responses import HTMLResponse
from openenv.core.env_server.http_server import create_app
from pydantic import BaseModel

from ..models import IncidentAction, IncidentObservation, IncidentState
from .environment import IncidentEnvironment
from .graders import grade, grade_detailed
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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root() -> HTMLResponse:
    """Landing page — shown when you open the HF Space URL in a browser."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Incident Response Env</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:2rem}
    .container{max-width:860px;margin:0 auto}
    h1{font-size:2rem;font-weight:700;color:#38bdf8;margin-bottom:.4rem}
    .subtitle{color:#94a3b8;margin-bottom:2rem;font-size:1.05rem}
    .badge{display:inline-block;padding:.2rem .6rem;border-radius:9999px;font-size:.75rem;font-weight:600;margin-right:.4rem}
    .easy{background:#166534;color:#bbf7d0}.medium{background:#92400e;color:#fde68a}.hard{background:#7f1d1d;color:#fecaca}
    .card{background:#1e293b;border:1px solid #334155;border-radius:.75rem;padding:1.25rem 1.5rem;margin-bottom:1rem}
    .card h2{font-size:1rem;font-weight:600;color:#f1f5f9;margin-bottom:.5rem}
    .card p{font-size:.9rem;color:#94a3b8;line-height:1.5}
    .endpoint{font-family:monospace;background:#0f172a;border:1px solid #334155;border-radius:.375rem;padding:.75rem 1rem;margin:.4rem 0;font-size:.85rem;display:flex;gap:1rem;align-items:baseline}
    .method{font-weight:700;min-width:3rem}.get{color:#34d399}.post{color:#f59e0b}
    .path{color:#e2e8f0}.desc{color:#64748b;font-size:.8rem;margin-left:auto}
    .codeblock{background:#0f172a;border:1px solid #334155;border-radius:.5rem;padding:1rem;font-family:monospace;font-size:.82rem;color:#a5f3fc;overflow-x:auto;margin-top:.75rem}
    a{color:#38bdf8;text-decoration:none}a:hover{text-decoration:underline}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem;margin-bottom:1.5rem}
    .stat{background:#1e293b;border:1px solid #334155;border-radius:.75rem;padding:1rem 1.25rem}
    .stat-val{font-size:1.75rem;font-weight:700;color:#38bdf8}.stat-label{font-size:.8rem;color:#64748b;margin-top:.2rem}
    footer{margin-top:2.5rem;text-align:center;color:#475569;font-size:.8rem}
  </style>
</head>
<body>
<div class="container">
  <h1>&#x1F6A8; Incident Response Environment</h1>
  <p class="subtitle">OpenEnv &mdash; Meta PyTorch Hackathon &bull; Production Server Debugging &bull; Agentic RL Training</p>

  <div class="grid">
    <div class="stat"><div class="stat-val">5</div><div class="stat-label">Tasks (1 Easy / 2 Medium / 2 Hard)</div></div>
    <div class="stat"><div class="stat-val">6</div><div class="stat-label">Action types</div></div>
    <div class="stat"><div class="stat-val">0.99</div><div class="stat-label">Baseline max score (rule-based)</div></div>
    <div class="stat"><div class="stat-val">&#x2714;</div><div class="stat-label">OpenEnv-compatible API</div></div>
  </div>

  <div class="card">
    <h2>Tasks</h2>
    <p style="margin-bottom:.75rem">Each task is a realistic production incident. Agents must diagnose and fix the system.</p>
    <p><span class="badge easy">EASY</span> <strong>task_1_oom</strong> &mdash; OOM Killer killed the api-server. Logs are clear. Fix: restart.</p>
    <br/>
    <p><span class="badge medium">MEDIUM</span> <strong>task_2_leak</strong> &mdash; Worker has a memory leak after bad deploy v2.4.1. Fix: rollback (not restart).</p>
    <br/>
    <p><span class="badge medium">MEDIUM</span> <strong>task_4_cache</strong> &mdash; Redis cache poisoned by bad serialization format. 62% of requests return 500. Fix: <code>FLUSHALL</code> (not restart).</p>
    <br/>
    <p><span class="badge hard">HARD</span> <strong>task_3_cascade</strong> &mdash; Full outage. Postgres <code>max_connections=25</code> exhausted. Misleading nginx disk error as a trap. Fix: <code>ALTER SYSTEM SET max_connections = 200</code>.</p>
    <br/>
    <p><span class="badge hard">HARD</span> <strong>task_5_cert</strong> &mdash; TLS certificate expired. nginx returns 502. High connection count looks like DDoS (red herring). Fix: <code>certbot renew</code> + restart nginx.</p>
  </div>

  <div class="card">
    <h2>API Endpoints</h2>
    <div class="endpoint"><span class="method get">GET</span><span class="path">/health</span><span class="desc">Liveness check</span></div>
    <div class="endpoint"><span class="method get">GET</span><span class="path">/tasks</span><span class="desc">List all tasks + action schema</span></div>
    <div class="endpoint"><span class="method post">POST</span><span class="path">/reset</span><span class="desc">Start episode &mdash; body: <code>{"task_id":"task_1_oom"}</code></span></div>
    <div class="endpoint"><span class="method post">POST</span><span class="path">/step</span><span class="desc">Execute action &mdash; body: <code>{"action":{"action_type":"read_logs","target":"api-server"}}</code></span></div>
    <div class="endpoint"><span class="method get">GET</span><span class="path">/state</span><span class="desc">Full episode state (for graders)</span></div>
    <div class="endpoint"><span class="method post">POST</span><span class="path">/grader</span><span class="desc">Score current episode</span></div>
    <div class="endpoint"><span class="method post">POST</span><span class="path">/baseline</span><span class="desc">Run rule-based baseline on all 5 tasks</span></div>
    <div class="endpoint"><span class="method get">GET</span><span class="path">/docs</span><span class="desc">Interactive Swagger UI</span></div>
  </div>

  <div class="card">
    <h2>Quick Start</h2>
    <div class="codeblock">BASE = "https://mayur6901-incident-response-env.hf.space"

# 1. Start an episode
curl -X POST $BASE/reset -H "Content-Type: application/json" \\
     -d '{"task_id": "task_1_oom"}'

# 2. Take an action
curl -X POST $BASE/step -H "Content-Type: application/json" \\
     -d '{"action": {"action_type": "read_logs", "target": "api-server"}}'

# 3. Fix the incident
curl -X POST $BASE/step -H "Content-Type: application/json" \\
     -d '{"action": {"action_type": "restart_service", "target": "api-server"}}'

# 4. Get your score
curl -X POST $BASE/grader</div>
  </div>

  <div class="card">
    <h2>Scoring Rubric</h2>
    <p style="margin-bottom:.75rem">Each task is graded on a composable rubric (0.0&ndash;1.0):</p>
    <p><strong>Investigation</strong> (10&ndash;40%) &mdash; Did the agent read logs / check metrics for the correct services?</p><br/>
    <p><strong>Root Cause</strong> (15&ndash;20%) &mdash; Was the root cause service correctly identified?</p><br/>
    <p><strong>Fix Applied</strong> (20&ndash;30%) &mdash; Was the correct remediation action taken (restart vs rollback vs exec_command)?</p><br/>
    <p><strong>System Restored</strong> (30%) &mdash; Are all services healthy after the fix?</p><br/>
    <p><strong>Step Efficiency</strong> (+5% bonus) &mdash; Solve within optimal step count for a bonus.</p><br/>
    <p><strong>Penalties</strong> (&minus;5 to &minus;20%) &mdash; Blind restarts, chasing red herrings, fixing symptoms instead of root cause.</p>
  </div>

  <div class="card">
    <h2>Run the demo locally</h2>
    <div class="codeblock">git clone https://github.com/mayur-dhavan/incident-response-env
cd incident-response-env
pip install -r requirements.txt
python demo.py</div>
    <p style="margin-top:.75rem">Or against this live Space: <code>python demo.py --url https://mayur6901-incident-response-env.hf.space</code></p>
  </div>

  <footer>
    <a href="https://github.com/mayur-dhavan/incident-response-env">GitHub</a> &bull;
    <a href="/docs">Swagger UI</a> &bull;
    <a href="https://huggingface.co/spaces/mayur6901/incident-response-env">HF Spaces</a>
  </footer>
</div>
</body>
</html>"""
    return HTMLResponse(content=html)


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

_TASK_RUBRICS: dict[str, dict[str, Any]] = {
    "task_1_oom": {
        "rubric": {"investigation_any_logs": 0.20, "investigation_api_server_logs": 0.20, "fix_restart_api_server": 0.30, "system_restored": 0.30},
        "penalties": [],
        "optimal_steps": 2,
    },
    "task_2_leak": {
        "rubric": {"investigation_any": 0.15, "investigation_worker": 0.20, "diagnosis_worker_metrics": 0.15, "fix_rollback_worker": 0.20, "system_restored": 0.30},
        "penalties": [{"trigger": "restart_service api-server", "amount": -0.15}, {"trigger": "restart_service worker", "amount": -0.10}],
        "optimal_steps": 3,
    },
    "task_3_cascade": {
        "rubric": {"investigation_any": 0.10, "investigation_postgres": 0.20, "root_cause_identified": 0.20, "fix_applied": 0.20, "system_restored": 0.30},
        "penalties": [{"trigger": "blind restart before diagnosis", "amount": -0.10, "max": -0.20}, {"trigger": "df/du disk check (red herring)", "amount": -0.05, "max": -0.10}],
        "optimal_steps": 4,
    },
    "task_4_cache": {
        "rubric": {"investigation_any": 0.10, "investigation_redis": 0.20, "diagnosis_redis_metrics": 0.15, "fix_flush_cache": 0.25, "system_restored": 0.30},
        "penalties": [{"trigger": "restart_service api-server", "amount": -0.10}, {"trigger": "restart_service redis", "amount": -0.10}],
        "optimal_steps": 3,
    },
    "task_5_cert": {
        "rubric": {"investigation_any": 0.10, "investigation_nginx": 0.15, "diagnosis_cert_check": 0.20, "fix_renew_cert": 0.25, "system_restored": 0.30},
        "penalties": [{"trigger": "blind restart before diagnosis", "amount": -0.10, "max": -0.20}, {"trigger": "iptables/fail2ban (DDoS red herring)", "amount": -0.10}],
        "optimal_steps": 4,
    },
}


@app.get("/tasks")
def get_tasks() -> dict[str, Any]:
    """
    Return all available tasks and the action schema.
    Required by the hackathon pre-submission checklist.
    """
    tasks = [
        {
            "task_id":     t["task_id"],
            "title":       t["title"],
            "difficulty":  t["difficulty"],
            "description": t["description"],
            "max_steps":   t["max_steps"],
            "grader_rubric": _TASK_RUBRICS.get(t["task_id"], {}),
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
    detailed = grade_detailed(state)

    return {
        "task_id":              state.task_id,
        "score":                score,
        "episode_id":           state.episode_id,
        "step_count":           state.step_count,
        "root_cause_identified": state.root_cause_identified,
        "fix_applied":          state.fix_applied,
        "system_restored":      state.system_restored,
        "breakdown":            detailed["breakdown"],
        "penalties":            detailed["penalties"],
    }


# ──────────────────────────────────────────────
# POST /baseline
# ──────────────────────────────────────────────

@app.post("/baseline")
def run_baseline() -> dict[str, Any]:
    """
    Run a deterministic rule-based baseline agent against all 5 tasks.
    Returns reproducible scores for the pre-submission checklist.

    The baseline agent is NOT an oracle — it applies shallow, fixed rules
    that a naive script would use.  It fixes every task but skips deeper
    investigation steps on harder tasks, so partial-credit scores vary by
    difficulty:

      Task 1 (easy):   read api-server logs → restart             → ~0.99
      Task 2 (medium): read worker logs → rollback                 → ~0.85
                       (skips check_metrics → loses metrics credit)
      Task 3 (hard):   check postgres metrics → exec fix commands  → ~0.80
                       (skips read_logs → loses investigation credit)
      Task 4 (medium): read api-server logs → FLUSHALL             → ~0.65
                       (never inspects redis → loses redis credits)
      Task 5 (hard):   read nginx logs → certbot renew → restart   → ~0.80
                       (skips openssl check → loses cert-check credit)
    """
    results: list[dict[str, Any]] = []

    from .scenarios import TASK_MAP

    policies: dict[str, list[IncidentAction]] = {
        # Task 1 (easy): logs clearly show OOM → restart.
        "task_1_oom": [
            IncidentAction(action_type="read_logs",       target="api-server"),
            IncidentAction(action_type="restart_service", target="api-server"),
        ],
        # Task 2 (medium): reads logs and rolls back; skips check_metrics.
        # Missing diagnosis_worker_metrics credit (0.15).
        "task_2_leak": [
            IncidentAction(action_type="read_logs",  target="worker"),
            IncidentAction(action_type="rollback",   target="worker"),
        ],
        # Task 3 (hard): checks nginx first (wrong service), then jumps to the fix.
        # Misses postgres investigation → no investigation_postgres or root_cause credit.
        "task_3_cascade": [
            IncidentAction(action_type="check_metrics", target="nginx"),
            IncidentAction(action_type="exec_command",  target="ALTER SYSTEM SET max_connections = 200"),
            IncidentAction(action_type="exec_command",  target="SELECT pg_reload_conf()"),
        ],
        # Task 4 (medium): reads api-server logs and flushes cache.
        # Never checks redis-specific metrics → no investigation_redis or diagnosis credit.
        "task_4_cache": [
            IncidentAction(action_type="read_logs",    target="api-server"),
            IncidentAction(action_type="exec_command", target="redis-cli FLUSHALL"),
        ],
        # Task 5 (hard): reads nginx logs, renews cert, restarts nginx.
        # Skips openssl diagnostic → no diagnosis_cert_check credit (0.20).
        "task_5_cert": [
            IncidentAction(action_type="read_logs",       target="nginx"),
            IncidentAction(action_type="exec_command",    target="certbot renew --force-renewal"),
            IncidentAction(action_type="restart_service", target="nginx"),
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
