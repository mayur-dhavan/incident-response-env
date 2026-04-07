---
title: Incident Response Environment
emoji: 🚨
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
tags:
  - openenv
pinned: false
---

# Incident Response Environment

An [OpenEnv](https://github.com/meta-pytorch/OpenEnv)-compliant environment that trains and evaluates AI agents on **production incident response** -- diagnosing and resolving real server outages, the same task SREs perform under pressure every day.

## Why This Domain?

- **High-stakes and common**: Every production system experiences outages; skilled SRE reasoning is scarce.
- **Partially observable**: The agent chooses *which* service to inspect -- not everything is visible at once.
- **Red-herring-rich**: Correlated-but-non-causative symptoms appear naturally (e.g. all services failing when Postgres connection pool is exhausted).
- **Action-consequence-dependent**: Wrong actions cost score -- blind restarts can mask root causes.
- **Sequentially demanding**: Diagnose first, then fix -- the grader enforces this order.

## Tasks

| Task | ID | Difficulty | Description | Max Steps | Optimal Steps |
|---|---|---|---|---|---|
| OOM Killer | `task_1_oom` | Easy | api-server killed by Linux OOM killer. Clear logs point to the fix. | 10 | 2 |
| Memory Leak | `task_2_leak` | Medium | Worker memory leak from bad deploy. API latency is a symptom. Rollback -- do not restart. | 12 | 3 |
| Redis Cache Poisoning | `task_4_cache` | Medium | Schema mismatch (msgpack v1 vs v2) causes 62% of requests to 500. Fix: FLUSHALL. Restarts do nothing. | 15 | 3 |
| Cascading Failure | `task_3_cascade` | Hard | Postgres max_connections=25 exhausted. False disk-full in nginx logs is a red herring. Fix: ALTER SYSTEM SET max_connections = 200. | 15 | 4 |
| TLS Certificate Expiry | `task_5_cert` | Hard | Internal TLS cert expired 45 min ago. 847 connections look like a DDoS -- they are retry storms. Fix: certbot renew + restart nginx. | 20 | 4 |

## Reward Design

Dense per-step reward: `reward_t = score(state_t) - score(state_{t-1})`

Every observation includes `steps_remaining` and `partial_score` so agents can make budget-aware decisions.

## Action Space

| Action | Target | Description |
|---|---|---|
| `read_logs` | service name | Read recent log lines |
| `check_metrics` | service name or `all` | Check CPU, memory, connections |
| `restart_service` | service name | Restart a service (may not fix root cause!) |
| `rollback` | service name | Rollback to previous version |
| `exec_command` | command string | Run diagnostic/repair command |
| `check_network` | `svc1->svc2` | Check network connectivity |

**Services**: `api-server`, `postgres`, `redis`, `worker`, `nginx`

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/reset` | Start a new episode -- `{"task_id": "task_1_oom"}` |
| POST | `/step` | Take an action |
| GET | `/state` | Full episode state |
| GET | `/health` | Health check |
| GET | `/tasks` | All 5 tasks with descriptions and full grader rubrics |
| POST | `/grader` | Grade current episode -- returns score, breakdown, penalties |
| POST | `/baseline` | Run rule-based baseline on all 5 tasks |

## Baseline Scores (Rule-based, imperfect heuristic)

| Task | Difficulty | Score |
|---|---|---|
| OOM Killer | Easy | 0.99 |
| Memory Leak | Medium | 0.85 |
| Redis Cache Poisoning | Medium | 0.65 |
| TLS Certificate Expiry | Hard | 0.80 |
| Cascading Failure | Hard | 0.60 |
| **Average** | | **0.778** |

*Scores vary by difficulty -- the baseline skips investigation steps on harder tasks to demonstrate grader sensitivity.*

Source: [github.com/mayur-dhavan/incident-response-env](https://github.com/mayur-dhavan/incident-response-env)
