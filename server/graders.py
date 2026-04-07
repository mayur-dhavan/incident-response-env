"""
Deterministic graders for each task.  Graders ONLY read the episode state
and action history — they never modify anything.

All graders return a float in [0.0, 1.0].
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import IncidentState


def _actions_contain(actions: list[dict], action_type: str, target_substr: str = "") -> bool:
    """Return True if any action matches the type and optionally contains target_substr."""
    for a in actions:
        if a.get("action_type") == action_type:
            if not target_substr or target_substr.lower() in a.get("target", "").lower():
                return True
    return False


# ─────────────────────────────────────────────
# Task 1 — OOM Killer (Easy)
# ─────────────────────────────────────────────
# Scoring rubric:
#   0.20  — read any logs at all (investigation started)
#   0.40  — read api-server logs specifically (correct direction)
#   0.30  — restarted api-server
#   0.10  — system_restored confirmed
# Total:  1.0
# ─────────────────────────────────────────────

def grade_task1(state: "IncidentState") -> float:
    actions = state.actions_taken
    score = 0.0

    # Some investigation happened
    if _actions_contain(actions, "read_logs"):
        score += 0.20

    # Zeroed in on the right service
    if _actions_contain(actions, "read_logs", "api-server"):
        score += 0.20

    # Applied the correct fix
    if _actions_contain(actions, "restart_service", "api-server"):
        score += 0.30

    # System actually healthy again
    if state.system_restored:
        score += 0.30

    return round(min(score, 1.0), 4)


# ─────────────────────────────────────────────
# Task 2 — Memory Leak (Medium)
# ─────────────────────────────────────────────
# Scoring rubric:
#   0.15  — any metrics/log investigation
#   0.20  — investigated worker (right service)
#   0.15  — identified memory trend (check_metrics worker)
#   0.20  — applied rollback to worker  (+0.20)
#   -0.20 — penalise restarting wrong service (api-server or worker restart instead of rollback)
#   0.10  — did NOT restart worker (restart is wrong, rollback is correct)
#   0.20  — system_restored
# Total cap: 1.0
# ─────────────────────────────────────────────

def grade_task2(state: "IncidentState") -> float:
    actions = state.actions_taken
    score = 0.0

    # Any investigation
    if _actions_contain(actions, "read_logs") or _actions_contain(actions, "check_metrics"):
        score += 0.15

    # Looked at worker
    if _actions_contain(actions, "read_logs", "worker") or _actions_contain(actions, "check_metrics", "worker"):
        score += 0.20

    # Checked worker metrics (memory trend key insight)
    if _actions_contain(actions, "check_metrics", "worker"):
        score += 0.15

    # Applied rollback (correct fix)
    if _actions_contain(actions, "rollback", "worker"):
        score += 0.20

    # Penalise restarting api-server (wrong service) or plain restart of worker
    if _actions_contain(actions, "restart_service", "api-server"):
        score -= 0.15
    if _actions_contain(actions, "restart_service", "worker"):
        score -= 0.10  # wrong action type even if right service

    # System restored
    if state.system_restored:
        score += 0.30

    return round(max(0.0, min(score, 1.0)), 4)


# ─────────────────────────────────────────────
# Task 3 — Cascading Failure (Hard)
# ─────────────────────────────────────────────
# Scoring rubric:
#   0.10  — any investigation happened
#   0.20  — investigated postgres (logs OR metrics)
#   0.20  — identified postgres connection exhaustion (root_cause_identified flag)
#   0.20  — executed correct postgres fix command
#   0.30  — system_restored
#
# Penalties (before root cause identified):
#   -0.10 each blind restart (api-server or worker) before root cause — max -0.20
#   -0.05 for chasing the disk space red herring
# ─────────────────────────────────────────────

def grade_task3(state: "IncidentState") -> float:
    actions = state.actions_taken
    score = 0.0

    # Any investigation
    if actions:
        score += 0.10

    # Looked at postgres
    postgres_investigated = (
        _actions_contain(actions, "read_logs", "postgres")
        or _actions_contain(actions, "check_metrics", "postgres")
    )
    if postgres_investigated:
        score += 0.20

    # Identified root cause (set by environment when postgres connection limit spotted)
    if state.root_cause_identified:
        score += 0.20

    # Correct fix applied (ALTER SYSTEM or pg_reload_conf)
    if state.fix_applied:
        score += 0.20

    # System actually restored
    if state.system_restored:
        score += 0.30

    # ── Penalties ───────────────────────────────────────────
    # Count blind restarts before root cause was identified
    blind_restarts = 0
    rc_found = False
    for a in actions:
        if a.get("_root_cause_found"):   # sentinel set by environment
            rc_found = True
        if not rc_found and a.get("action_type") == "restart_service":
            blind_restarts += 1
    score -= min(blind_restarts * 0.10, 0.20)

    # Chased disk space red-herring
    disk_chases = sum(
        1 for a in actions
        if a.get("action_type") == "exec_command" and
        any(cmd in a.get("target", "").lower() for cmd in ["df -h", "du -sh", "fdisk", "lsblk"])
    )
    score -= min(disk_chases * 0.05, 0.10)

    return round(max(0.0, min(score, 1.0)), 4)


# ─────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────

GRADER_MAP = {
    "task_1_oom":     grade_task1,
    "task_2_leak":    grade_task2,
    "task_3_cascade": grade_task3,
}


def grade(state: "IncidentState") -> float:
    """Grade the current episode and return score in (0.0, 1.0) exclusive.

    The hackathon evaluator requires scores strictly between 0 and 1 —
    not 0.0 and not 1.0.  We clamp to [0.01, 0.99] after grading.
    """
    grader_fn = GRADER_MAP.get(state.task_id)
    if grader_fn is None:
        raise ValueError(f"Unknown task_id: {state.task_id!r}")
    raw = grader_fn(state)
    return round(max(0.01, min(raw, 0.99)), 4)
