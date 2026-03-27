#!/usr/bin/env python3
"""
demo.py — Interactive showcase of the Incident Response Environment.

Walks through all three tasks using an optimal rule-based strategy,
printing every observation and reward so you can see what an agent
experiences at each step.

Usage:
    python demo.py                              # against live HF Space
    python demo.py --url http://localhost:7860  # against local server

No API key required.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import textwrap
from typing import Any

# Ensure UTF-8 output on all platforms (fixes Windows cp1252 terminal)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is not installed. Run: pip install requests")
    sys.exit(1)

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

DEFAULT_BASE_URL = "https://mayur6901-incident-response-env.hf.space"

DIVIDER_WIDE  = "=" * 70
DIVIDER_THIN  = "-" * 70
DIVIDER_STEP  = "·" * 70


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m"


# ──────────────────────────────────────────────
# HTTP helpers
# ──────────────────────────────────────────────

class EnvClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def health(self) -> dict:
        r = self.session.get(f"{self.base_url}/health", timeout=15)
        r.raise_for_status()
        return r.json()

    def tasks(self) -> dict:
        r = self.session.get(f"{self.base_url}/tasks", timeout=15)
        r.raise_for_status()
        return r.json()

    def reset(self, task_id: str | None = None) -> dict:
        payload: dict[str, Any] = {}
        if task_id:
            payload["task_id"] = task_id
        r = self.session.post(f"{self.base_url}/reset", json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    def step(self, action_type: str, target: str, parameters: dict | None = None) -> dict:
        payload = {
            "action": {
                "action_type": action_type,
                "target": target,
                "parameters": parameters or {},
            }
        }
        r = self.session.post(f"{self.base_url}/step", json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    def state(self) -> dict:
        r = self.session.get(f"{self.base_url}/state", timeout=15)
        r.raise_for_status()
        return r.json()

    def grade(self, task_id: str) -> dict:
        payload = {"task_id": task_id}
        r = self.session.post(f"{self.base_url}/grader", json=payload, timeout=15)
        r.raise_for_status()
        return r.json()


# ──────────────────────────────────────────────
# Playbooks — rule-based optimal strategies
# ──────────────────────────────────────────────

# Each step: (action_type, target, parameters, rationale)
PLAYBOOKS: list[dict[str, Any]] = [
    {
        "task_id": "task_1_oom",
        "label": "Task 1 — Easy: OOM Killer",
        "steps": [
            ("read_logs",       "api-server", {}, "Read api-server logs to identify root cause"),
            ("restart_service", "api-server", {}, "api-server was killed by OOM killer → restart it"),
        ],
    },
    {
        "task_id": "task_2_leak",
        "label": "Task 2 — Medium: Memory Leak",
        "steps": [
            ("check_metrics", "worker",     {}, "Check metrics — worker memory is at 94%"),
            ("read_logs",     "worker",     {}, "Read worker logs — leak started after v2.4.1 deploy"),
            ("rollback",      "worker",     {}, "Rollback worker to v2.4.0 to fix the leak"),
        ],
    },
    {
        "task_id": "task_3_cascade",
        "label": "Task 3 — Hard: Cascading Failure",
        "steps": [
            ("check_metrics", "postgres",  {}, "Postgres at max_connections=25 — connection exhaustion"),
            ("read_logs",     "postgres",  {}, "Logs confirm: FATAL too many clients, max_connections=25"),
            (
                "exec_command",
                "ALTER SYSTEM SET max_connections = 200; SELECT pg_reload_conf();",
                {},
                "Raise max_connections to 200 and reload postgres config",
            ),
        ],
    },
]


# ──────────────────────────────────────────────
# Pretty-print helpers
# ──────────────────────────────────────────────

def _print_services(services: dict[str, Any]) -> None:
    if not services:
        return
    print(f"\n  {'Service':<15} {'Status':<12} {'CPU%':>6} {'Mem%':>6} {'Errors':>7}")
    print(f"  {'-'*15} {'-'*12} {'-'*6} {'-'*6} {'-'*7}")
    for name, info in services.items():
        status = info.get("status", "?")
        cpu    = info.get("cpu", "-")
        mem    = info.get("memory", "-")
        errs   = info.get("error_count", "-")
        if status == "healthy":
            status_str = _green(f"{status:<12}")
        elif status == "degraded":
            status_str = _yellow(f"{status:<12}")
        else:
            status_str = _red(f"{status:<12}")
        cpu_str = f"{cpu:>5.1f}%" if isinstance(cpu, (int, float)) else f"{str(cpu):>6}"
        mem_str = f"{mem:>5.1f}%" if isinstance(mem, (int, float)) else f"{str(mem):>6}"
        print(f"  {name:<15} {status_str} {cpu_str} {mem_str} {str(errs):>7}")


def _print_observation(obs: dict[str, Any], step_num: int) -> None:
    reward = obs.get("reward")
    done   = obs.get("done", obs.get("observation", {}).get("done", False))

    # Handle nested structure from OpenEnv step response
    if "observation" in obs:
        inner = obs["observation"]
        output   = inner.get("output", "")
        services = inner.get("services", {})
        success  = inner.get("success", True)
        error    = inner.get("error", "")
        done     = obs.get("done", inner.get("done", False))
    else:
        output   = obs.get("output", "")
        services = obs.get("services", {})
        success  = obs.get("success", True)
        error    = obs.get("error", "")

    reward_label = (
        f"reward={_green(f'{reward:.3f}')}" if reward is not None else "reward=N/A"
    )

    print(f"\n{DIVIDER_STEP}")
    print(f"  Step {step_num}  |  {reward_label}  |  done={done}")
    print(DIVIDER_STEP)

    if not success and error:
        print(f"\n  {_red('ERROR:')} {error}")
        return

    # Print output (wrapped nicely)
    if output:
        for line in output.splitlines():
            wrapped = textwrap.wrap(line, width=68)
            if wrapped:
                for wl in wrapped:
                    print(f"  {wl}")
            else:
                print()

    _print_services(services)


# ──────────────────────────────────────────────
# Run a single task
# ──────────────────────────────────────────────

def run_task(client: EnvClient, playbook: dict[str, Any]) -> dict[str, Any]:
    task_id = playbook["task_id"]
    label   = playbook["label"]
    steps   = playbook["steps"]

    print(f"\n{DIVIDER_WIDE}")
    print(_bold(f"  {label}"))
    print(DIVIDER_WIDE)

    # Reset
    print(f"\n{_cyan('[RESET]')}  Starting new episode for {task_id!r} ...")
    reset_resp = client.reset(task_id=task_id)

    if "observation" in reset_resp:
        obs_data = reset_resp["observation"]
    else:
        obs_data = reset_resp

    output   = obs_data.get("output", "")
    services = obs_data.get("services", {})

    print(f"\n{DIVIDER_THIN}")
    print("  Initial observation:")
    print(DIVIDER_THIN)
    if output:
        for line in output.splitlines():
            wrapped = textwrap.wrap(line, width=68)
            for wl in (wrapped or [""]):
                print(f"  {wl}")
    _print_services(services)

    # Execute each step in the playbook
    cumulative_reward = 0.0
    for step_num, (action_type, target, parameters, rationale) in enumerate(steps, start=1):
        short_target = target if len(target) <= 40 else target[:37] + "..."
        print(f"\n{_cyan(f'[STEP {step_num}]')}  action={action_type!r}  target={short_target!r}")
        print(f"  Rationale: {rationale}")

        result = client.step(action_type, target, parameters)

        reward = result.get("reward")
        if reward is not None:
            cumulative_reward += reward

        _print_observation(result, step_num)

        if result.get("done", False):
            print(f"\n  {_green('Episode complete!')} (done=True returned)")
            break

    # Grade the episode
    print(f"\n{DIVIDER_THIN}")
    print(f"  {_cyan('[GRADER]')}  Evaluating episode ...")
    print(DIVIDER_THIN)

    try:
        grade_result = client.grade(task_id)
        score = grade_result.get("score", grade_result.get("total_score", 0.0))
        details = grade_result.get("details", grade_result)
        print(f"\n  Final score : {_bold(_green(str(score)))}")
        print(f"\n  Grader breakdown:")
        for key, val in details.items():
            if key not in ("task_id", "episode_id"):
                print(f"    {key:<30} {val}")
    except Exception as exc:
        score = 0.0
        print(f"  {_yellow('Grader unavailable:')} {exc}")

    return {
        "task_id": task_id,
        "label":   label,
        "score":   score,
        "cumulative_reward": round(cumulative_reward, 4),
        "steps":   len(steps),
    }


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo: walk through all 3 incident-response tasks using the optimal strategy."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of the running environment server (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--task",
        choices=["task_1_oom", "task_2_leak", "task_3_cascade"],
        help="Run only a specific task (default: run all three)",
    )
    args = parser.parse_args()

    client = EnvClient(args.url)

    # Health check
    print(f"\n{DIVIDER_WIDE}")
    print(_bold("  Incident Response Environment — Demo"))
    print(DIVIDER_WIDE)
    print(f"\n  Server : {args.url}")

    try:
        health = client.health()
        print(f"  Status : {_green(health.get('status', 'ok'))}")
    except Exception as exc:
        print(f"  {_red('ERROR: Cannot reach server')} — {exc}")
        print(f"\n  Make sure the server is running:")
        print(f"    uvicorn incident_response_env.server.app:app --port 7860")
        print(f"  Or use the live HF Space:")
        print(f"    python demo.py --url {DEFAULT_BASE_URL}")
        sys.exit(1)

    # Show available tasks
    try:
        tasks_info = client.tasks()
        tasks_list = tasks_info.get("tasks", [])
        print(f"\n  Available tasks ({len(tasks_list)}):")
        for t in tasks_list:
            diff_colors = {"easy": _green, "medium": _yellow, "hard": _red}
            diff = t.get("difficulty", "?")
            color_fn = diff_colors.get(diff, str)
            print(f"    [{color_fn(diff.upper())}]  {t['task_id']}  —  {t['title']}")
    except Exception:
        pass  # non-fatal

    # Run playbooks
    playbooks = PLAYBOOKS
    if args.task:
        playbooks = [p for p in PLAYBOOKS if p["task_id"] == args.task]

    results = []
    for playbook in playbooks:
        result = run_task(client, playbook)
        results.append(result)

    # Summary table
    print(f"\n\n{DIVIDER_WIDE}")
    print(_bold("  RESULTS SUMMARY"))
    print(DIVIDER_WIDE)
    print(f"\n  {'Task':<35} {'Difficulty':<12} {'Steps':>5} {'Score':>7}")
    print(f"  {'-'*35} {'-'*12} {'-'*5} {'-'*7}")

    difficulties = {
        "task_1_oom": ("easy",   _green),
        "task_2_leak": ("medium", _yellow),
        "task_3_cascade": ("hard",   _red),
    }

    for r in results:
        diff, color_fn = difficulties.get(r["task_id"], ("?", str))
        score_str = f"{r['score']:.3f}" if isinstance(r["score"], float) else str(r["score"])
        score_colored = _green(score_str) if r["score"] >= 0.8 else _yellow(score_str) if r["score"] >= 0.4 else _red(score_str)
        print(
            f"  {r['label']:<35} {color_fn(diff):<12} "
            f"{r['steps']:>5} {score_colored:>7}"
        )

    if len(results) == 3:
        avg = sum(r["score"] for r in results) / 3
        avg_str = f"{avg:.3f}"
        avg_colored = _green(avg_str) if avg >= 0.8 else _yellow(avg_str)
        print(f"\n  {'Average score':<35} {'':12} {'':5} {avg_colored:>7}")

    print(f"\n{DIVIDER_WIDE}")
    print()


if __name__ == "__main__":
    main()
