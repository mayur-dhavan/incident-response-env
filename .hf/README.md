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

An [OpenEnv](https://github.com/meta-llama/open-env)-compliant environment that simulates **production incident response** — the real-world task of diagnosing and resolving server outages that SREs (Site Reliability Engineers) perform daily.

An AI agent must investigate service health, read logs, check metrics, identify the root cause of an outage, and apply the correct fix — all under a step budget.

## Why This Domain?

Production incident response is a high-stakes, knowledge-intensive task where:
- **Partial information** is the norm — not everything is visible at once
- **Red herrings** exist — misleading log entries and correlated-but-not-causative symptoms
- **Wrong actions have consequences** — blindly restarting services can mask root causes or worsen outages
- **Sequential reasoning** is required — diagnose first, then fix

## Tasks

| Task | ID | Difficulty | Description | Optimal Steps |
|---|---|---|---|---|
| OOM Killer | `task_1_oom` | Easy | api-server killed by Linux OOM killer | 2 |
| Memory Leak | `task_2_leak` | Medium | Worker memory leak from bad deploy | 3 |
| Cascading Failure | `task_3_cascade` | Hard | Postgres connection limit hit, cascading outage | 4 |

## Action Space

| Action | Target | Description |
|---|---|---|
| `read_logs` | service name | Read recent log lines |
| `check_metrics` | service name or `all` | Check CPU, memory, connections |
| `restart_service` | service name | Restart a service |
| `rollback` | service name | Rollback to previous version |
| `exec_command` | command string | Run diagnostic/repair command |
| `check_network` | `svc1->svc2` | Check network connectivity |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/reset` | Start a new episode |
| POST | `/step` | Take an action |
| GET | `/state` | Get full episode state |
| GET | `/health` | Health check |
| POST | `/grader` | Grade current episode |

## Baseline Scores (Rule-based)

| Task | Score | Steps |
|---|---|---|
| OOM Killer | 1.0000 | 2 |
| Memory Leak | 1.0000 | 3 |
| Cascading Failure | 1.0000 | 4 |

Source: [github.com/mayur-dhavan/incident-response-env](https://github.com/mayur-dhavan/incident-response-env)
