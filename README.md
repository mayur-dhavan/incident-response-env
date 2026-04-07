---
title: Incident Response Environment
emoji: 🚨
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Incident Response Environment

An [OpenEnv](https://github.com/meta-pytorch/OpenEnv)-compliant environment that trains and evaluates AI agents on **production incident response** -- diagnosing and resolving real server outages, the same task SREs perform under pressure every day.

An agent must investigate service health, read logs, check metrics, identify the root cause of an outage, and apply the correct fix -- all within a step budget and with deliberate red herrings.

## Why This Domain?

Production incident response is one of the best testbeds for sequential decision-making because it is:

- **High-stakes and common**: Every production system has outages; skilled SRE reasoning is scarce and expensive.
- **Partially observable**: Not everything is visible at once -- the agent must choose *which* service to inspect.
- **Red-herring-rich**: Correlated-but-not-causative symptoms naturally occur (e.g. all services failing when the database connection pool is exhausted).
- **Action-consequence-dependent**: Wrong actions have real costs -- blindly restarting services can mask root causes or prevent self-healing.
- **Sequentially demanding**: Diagnose first, then fix -- the order matters and grader rubrics enforce this.
- **Differentially hard**: Easy tasks are solvable with basic log-reading. Hard tasks require understanding cascading failures and avoiding misleading signals.

This makes the environment excellent for training agents that must **reason before acting** -- a capability central to agentic AI and LLM-based SRE automation.

## Tasks

| Task | ID | Difficulty | Description | Max Steps | Optimal Steps |
|---|---|---|---|---|---|
| OOM Killer | `task_1_oom` | Easy | api-server killed by Linux OOM killer. Clear logs point directly to the fix. | 10 | 2 |
| Memory Leak | `task_2_leak` | Medium | Worker has a memory leak from bad deploy v2.4.1. API latency is a symptom, not the cause. Rollback -- do not restart. | 12 | 3 |
| Redis Cache Poisoning | `task_4_cache` | Medium | v3.1.0 wrote msgpack v1 keys; api-server v3.2 expects v2 -- 62% of requests return 500. Fix: FLUSHALL. Restarting redis or api-server does nothing. | 15 | 3 |
| Cascading Failure | `task_3_cascade` | Hard | Postgres max_connections=25 exhausted -- all services degraded. False "disk full" entry in nginx logs from 3 weeks ago is a red herring. Fix: ALTER SYSTEM SET max_connections = 200 + reload. | 15 | 4 |
| TLS Certificate Expiry | `task_5_cert` | Hard | Internal TLS cert expired 45 min ago. nginx returns 502. 847 active connections look like a DDoS -- they are retry storms from the cert error. Fix: certbot renew + restart nginx. | 20 | 4 |

### Difficulty Progression

- **Easy**: One service down, unambiguous logs, single-step fix.
- **Medium**: Multiple degraded services; must distinguish root cause from symptom; wrong fix is penalized.
- **Hard**: Cascading or subtle failure; realistic red herrings; multi-step fix; penalty for blind restarts.

## Reward Design

Rewards are computed as the **delta in grader partial-credit score** at each step -- providing a dense signal throughout the trajectory:

```
reward_t = score(state_t) - score(state_{t-1})
```

- **+reward** for investigation actions that move toward the root cause
- **+reward** for applying the correct fix
- **-reward** for wrong actions (restart when you should rollback; chasing red herrings)
- **zero** for redundant or neutral actions

Every observation includes:
- `output` -- human-readable result (log lines, metrics, command output)
- `services` -- live health snapshot of all 5 services
- `steps_remaining` -- explicit step budget (agents can decide when to stop investigating and act)
- `partial_score` -- running grader score after this step
- `reward` -- delta since last step

### Grader Rubrics (deterministic partial credit)

**Task 1 -- OOM Killer (Easy)**

| Component | Weight |
|---|---|
| Read any logs | +0.20 |
| Read api-server logs specifically | +0.20 |
| Restart api-server | +0.30 |
| System restored | +0.30 |

**Task 2 -- Memory Leak (Medium)**

| Component | Weight |
|---|---|
| Any investigation | +0.15 |
| Investigate worker | +0.20 |
| Check worker metrics | +0.15 |
| Rollback worker | +0.20 |
| System restored | +0.30 |
| Restart api-server (wrong service) | -0.15 |
| Restart worker (wrong action) | -0.10 |

**Task 4 -- Redis Cache Poisoning (Medium)**

| Component | Weight |
|---|---|
| Any investigation | +0.10 |
| Investigate redis | +0.20 |
| Check redis metrics | +0.15 |
| FLUSHALL / FLUSHDB | +0.25 |
| System restored | +0.30 |
| Restart api-server | -0.10 |
| Restart redis | -0.10 |

**Task 3 -- Cascading Failure (Hard)**

| Component | Weight |
|---|---|
| Any investigation | +0.10 |
| Investigate postgres | +0.20 |
| Root cause identified | +0.20 |
| Correct fix command | +0.20 |
| System restored | +0.30 |
| Blind restart before diagnosis | -0.10 each (max -0.20) |
| Disk space check (red herring) | -0.05 each (max -0.10) |

**Task 5 -- TLS Certificate Expiry (Hard)**

| Component | Weight |
|---|---|
| Any investigation | +0.10 |
| Investigate nginx | +0.15 |
| openssl / cert diagnostic | +0.20 |
| certbot renew | +0.25 |
| System restored | +0.30 |
| Blind restart before cert check | -0.10 each (max -0.20) |
| iptables/fail2ban (DDoS red herring) | -0.10 |

## Action Space

```python
class IncidentAction(Action):
    action_type: str  # one of 6 actions below
    target: str       # service name or command string
    parameters: dict  # optional (e.g. {"lines": 50} for read_logs)
```

| Action | Target | Description |
|---|---|---|
| `read_logs` | service name | Read recent log lines for a service |
| `check_metrics` | service name or `all` | Check CPU, memory, connections, error rates |
| `restart_service` | service name | Restart a service (may not fix root cause!) |
| `rollback` | service name | Rollback to previous deployment version |
| `exec_command` | command string | Run a diagnostic/repair command (SQL, shell) |
| `check_network` | `svc1->svc2` | Check network connectivity between two services |

**Services**: `api-server`, `postgres`, `redis`, `worker`, `nginx`

## Observation Space

```python
class IncidentObservation(Observation):
    output: str              # Human-readable result (logs, metrics, status)
    services: dict[str, Any] # Live health snapshot of all 5 services
    success: bool            # False if the action was invalid
    error: str               # Error message when success=False
    steps_remaining: int     # Steps left in the budget
    partial_score: float     # Running grader score (0.01-0.99)
    # Inherited from Observation:
    done: bool               # True when episode ends
    reward: float            # Delta partial_score since last step
```

## State (for graders)

```python
class IncidentState(State):
    task_id: str
    actions_taken: list[dict]        # Full action history with step numbers
    root_cause_identified: bool      # Set when the agent finds the root cause
    fix_applied: bool                # Set when the correct repair is applied
    system_restored: bool            # True when all health checks pass
    current_score: float             # Running partial-credit score
    # Inherited: episode_id, step_count
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/reset` | Start a new episode. Body: `{"task_id": "task_1_oom"}` |
| POST | `/step` | Take an action. Body: `{"action": {"action_type": "...", "target": "..."}}` |
| GET | `/state` | Full episode state with action history |
| GET | `/health` | Health check |
| GET | `/tasks` | All 5 tasks with descriptions, max_steps, and full grader rubrics |
| POST | `/grader` | Score the current episode -- returns score, breakdown per rubric item, and penalties |
| POST | `/baseline` | Run rule-based baseline on all 5 tasks -- returns per-task scores and average |
| GET | `/schema` | OpenEnv schema |
| GET | `/` | Live demo landing page |

## Baseline Scores

### Rule-based baseline (imperfect heuristic -- not oracle)

The baseline uses realistic but suboptimal policies: always applies the correct fix, but skips investigation steps on harder tasks. This demonstrates that grader scores genuinely vary by agent quality.

| Task | Difficulty | Baseline Score | Steps | System Restored |
|---|---|---|---|---|
| OOM Killer | Easy | 0.99 | 2 | Yes |
| Memory Leak | Medium | 0.85 | 2 | Yes |
| Redis Cache Poisoning | Medium | 0.65 | 2 | Yes |
| TLS Certificate Expiry | Hard | 0.80 | 3 | Yes |
| Cascading Failure | Hard | 0.60 | 3 | Yes |
| **Average** | | **0.778** | | |

*An optimal agent (diagnose -> investigate -> fix systematically) would score 0.99 on all tasks. The baseline intentionally skips investigation steps to show grader sensitivity.*

### LLM agent (Llama 3.3 70B Instruct via OpenRouter)

| Task | Difficulty | Observed Score |
|---|---|---|
| OOM Killer | Easy | 0.99 |
| Memory Leak | Medium | 0.65-0.85 |
| Cascading Failure | Hard | 0.30-0.60 |

*Hard tasks with red herrings significantly reduce LLM performance -- exactly the intended difficulty gradient.*

## Setup & Usage

### Local Development

```bash
# Install
pip install -e ".[dev]"

# Start the server
uvicorn incident_response_env.server.app:app --port 7860

# Run baseline (deterministic, no API key needed)
python incident_response_env/inference.py

# Run tests (41 tests)
pytest tests/ -v
```

### Docker

```bash
docker build -f .hf/Dockerfile -t incident-response-env .
docker run -p 7860:7860 incident-response-env
```

### HF Space

Live environment: https://huggingface.co/spaces/mayur6901/incident-response-env

## Project Structure

```
incident_response_env/
--  models.py              # Pydantic Action/Observation/State models (typed)
--  inference.py           # Baseline inference script (OpenAI-compatible)
--  openenv.yaml           # OpenEnv spec metadata
--  pyproject.toml         # Package config + dependencies
--  README.md              # This file
--  tests/
--      test_graders.py    # 21 grader unit tests (all 5 tasks, clamping, penalties)
--      test_environment.py# 14 environment step/reset tests
--      test_api.py        # 6 FastAPI endpoint tests
--  server/
--      app.py             # FastAPI application -- all endpoints
--      environment.py     # Core reset/step logic with per-step reward
--      graders.py         # Deterministic graders with partial-credit rubrics
--      scenarios.py       # Task definitions (logs, metrics, services, grader config)
```

## OpenEnv Compliance

- `spec_version: 1` in `openenv.yaml`
- Typed Pydantic models for Action, Observation, State
- `step()` / `reset()` / `state()` fully implemented
- Deterministic graders returning values in (0.01, 0.99)
- Dense per-step reward signal (`reward = delta partial_score`)
- `steps_remaining` in every observation for budget-aware agent policies
- Clean episode boundaries with `reset(task_id=...)`
- Dockerfile builds and runs cleanly
- 41 pytest tests passing
- Baseline script reproduces scores without an LLM API key

## License

MIT
