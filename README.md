# Incident Response Environment

An [OpenEnv](https://github.com/meta-llama/open-env)-compliant environment that simulates **production incident response** — the real-world task of diagnosing and resolving server outages that SREs (Site Reliability Engineers) perform daily.

An AI agent must investigate service health, read logs, check metrics, identify the root cause of an outage, and apply the correct fix — all under a step budget.

## Why This Domain?

Production incident response is a high-stakes, knowledge-intensive task where:
- **Partial information** is the norm — not everything is visible at once
- **Red herrings** exist — misleading log entries and correlated-but-not-causative symptoms
- **Wrong actions have consequences** — blindly restarting services can mask root causes or worsen outages
- **Sequential reasoning** is required — diagnose first, then fix

This makes it an excellent testbed for evaluating LLM agents on real-world decision-making.

## Tasks

| Task | ID | Difficulty | Description | Optimal Steps |
|---|---|---|---|---|
| OOM Killer | `task_1_oom` | Easy | api-server killed by Linux OOM killer. Clear logs point to the fix. | 2 |
| Memory Leak | `task_2_leak` | Medium | Worker has a memory leak from a bad deploy. API latency is a symptom, not the cause. Rollback, don't restart. | 3 |
| Cascading Failure | `task_3_cascade` | Hard | Postgres connection limit hit (max_connections=25). Everything is down. Misleading "disk full" error in nginx logs from 3 weeks ago. | 4 |

### Difficulty Progression

- **Easy**: Single service down, unambiguous logs, fix is `restart_service`
- **Medium**: Multiple degraded services, must distinguish cause from symptom, wrong fix (restart) is penalized
- **Hard**: Full outage, cascading failures, misleading red herring, requires SQL command to fix, blind restarts are penalized and don't work

## Action Space

```python
class IncidentAction(Action):
    action_type: str  # one of the 6 actions below
    target: str       # service name or command string
    parameters: dict  # optional extra params
```

| Action | Target | Description |
|---|---|---|
| `read_logs` | service name | Read recent log lines for a service |
| `check_metrics` | service name or `all` | Check CPU, memory, connections, error rates |
| `restart_service` | service name | Restart a service (may not fix root cause) |
| `rollback` | service name | Rollback to previous deployment version |
| `exec_command` | command string | Run a diagnostic/repair command (SQL, shell) |
| `check_network` | `svc1->svc2` | Check network connectivity between services |

**Services**: `api-server`, `postgres`, `redis`, `worker`, `nginx`

## Observation Space

```python
class IncidentObservation(Observation):
    output: str              # Human-readable result (log lines, metrics, status messages)
    services: dict[str, Any] # Current health snapshot of all services
    success: bool            # Whether the action executed successfully
    error: str               # Error message if success=False
    # Inherited from Observation:
    done: bool               # True when episode ends
    reward: float            # Per-step reward (score delta)
```

## State (for graders)

```python
class IncidentState(State):
    task_id: str
    actions_taken: list[dict]
    root_cause_identified: bool
    fix_applied: bool
    system_restored: bool
    current_score: float
    # Inherited: episode_id, step_count
```

## Reward Design

Rewards are computed as the **delta in grader score** at each step:

- **Positive reward** for investigation actions that move toward the root cause
- **Positive reward** for applying the correct fix
- **Negative reward** for wrong actions (e.g., restarting when you should rollback)
- **Zero reward** for redundant or neutral actions

This provides dense signal throughout the trajectory, not just a binary end-of-episode score.

### Grader Rubrics

**Task 1 (Easy)**: +0.20 read any logs, +0.20 read api-server logs, +0.30 restart api-server, +0.30 system restored = 1.0

**Task 2 (Medium)**: +0.15 any investigation, +0.20 investigate worker, +0.15 check worker metrics, +0.20 rollback worker, +0.30 system restored. Penalties: -0.15 restart api-server, -0.10 restart worker.

**Task 3 (Hard)**: +0.10 any investigation, +0.20 investigate postgres, +0.20 identify root cause, +0.20 correct fix command, +0.30 system restored. Penalties: -0.10 per blind restart (max -0.20), -0.05 per disk space investigation (max -0.10).

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/reset` | Start a new episode. Body: `{"task_id": "task_1_oom"}` |
| POST | `/step` | Take an action. Body: `{"action": {"action_type": "...", "target": "...", "parameters": {}}}` |
| GET | `/state` | Get full episode state (for grading) |
| GET | `/health` | Health check |
| GET | `/tasks` | List all tasks with action schema |
| POST | `/grader` | Grade the current episode (returns score 0.0–1.0) |
| POST | `/baseline` | Run rule-based baseline on all 3 tasks |
| GET | `/schema` | OpenEnv schema |

## Setup & Usage

### Local Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Start the server
uvicorn incident_response_env.server.app:app --port 7860

# Run baseline (rule-based, no API key needed)
python incident_response_env/baseline.py --url http://localhost:7860 --rule-based

# Run baseline (LLM, requires OPENAI_API_KEY)
export OPENAI_API_KEY=sk-...
python incident_response_env/baseline.py --url http://localhost:7860 --model gpt-4o-mini
```

### Docker

```bash
cd incident_response_env
docker build -f server/Dockerfile -t incident-response-env .
docker run -p 7860:7860 incident-response-env
```

### Hugging Face Spaces

The environment is deployed at: https://huggingface.co/spaces/mayur6901/incident-response-env

## Baseline Scores

### Rule-based agent (deterministic)

| Task | Difficulty | Score | Steps | Restored |
|---|---|---|---|---|
| OOM Killer | Easy | 1.0000 | 2 | Yes |
| Memory Leak | Medium | 1.0000 | 3 | Yes |
| Cascading Failure | Hard | 1.0000 | 4 | Yes |
| **Average** | | **1.0000** | | |

*The rule-based agent uses perfect domain knowledge — it represents the optimal policy.*

### LLM agent (gpt-4o-mini)

Scores will vary by model. The environment is designed so that:
- Easy task: most models should score 0.7–1.0
- Medium task: requires distinguishing cause from symptom (expected 0.5–0.9)
- Hard task: requires avoiding red herrings and executing SQL (expected 0.3–0.7)

## Project Structure

```
incident_response_env/
├── models.py              # Pydantic Action/Observation/State models
├── baseline.py            # Baseline inference script (OpenAI API + rule-based)
├── client.py              # EnvClient wrapper for programmatic use
├── openenv.yaml           # OpenEnv spec metadata
├── pyproject.toml         # Package config + dependencies
├── README.md              # This file
├── __init__.py
└── server/
    ├── app.py             # FastAPI application with all endpoints
    ├── environment.py     # Core environment logic (reset/step/state)
    ├── graders.py         # Deterministic grading functions
    ├── scenarios.py       # Task definitions (logs, metrics, services)
    ├── Dockerfile         # Container for HF Spaces deployment
    ├── requirements.txt   # Python dependencies
    └── __init__.py
```

## OpenEnv Compliance

- `spec_version: 1` in `openenv.yaml`
- Typed Pydantic models for Action, Observation, State
- `step()` / `reset()` / `state()` fully implemented
- Deterministic graders returning 0.0–1.0
- Per-step reward signal (not just end-of-episode)
- Clean episode boundaries with `reset()`
- Dockerfile builds and runs cleanly
- Baseline script uses OpenAI API client

## License

MIT
