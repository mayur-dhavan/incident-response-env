"""
Deterministic graders for each task.  Graders ONLY read the episode state
and action history — they never modify anything.

All graders return a float in [0.0, 1.0].
The ``grade()`` dispatcher clamps to (0.01, 0.99) for hackathon compliance.
"""

from __future__ import annotations
from typing import Any, TYPE_CHECKING

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

def _grade_task1_detailed(state: "IncidentState") -> dict[str, Any]:
    actions = state.actions_taken
    breakdown: dict[str, float] = {}
    penalties: list[dict[str, Any]] = []

    breakdown["investigation_any_logs"] = 0.20 if _actions_contain(actions, "read_logs") else 0.0
    breakdown["investigation_api_server_logs"] = 0.20 if _actions_contain(actions, "read_logs", "api-server") else 0.0
    breakdown["fix_restart_api_server"] = 0.30 if _actions_contain(actions, "restart_service", "api-server") else 0.0
    breakdown["system_restored"] = 0.30 if state.system_restored else 0.0

    raw = round(min(sum(breakdown.values()), 1.0), 4)
    return {"raw_score": raw, "breakdown": breakdown, "penalties": penalties}


def grade_task1(state: "IncidentState") -> float:
    return _grade_task1_detailed(state)["raw_score"]


# ─────────────────────────────────────────────
# Task 2 — Memory Leak (Medium)
# ─────────────────────────────────────────────

def _grade_task2_detailed(state: "IncidentState") -> dict[str, Any]:
    actions = state.actions_taken
    breakdown: dict[str, float] = {}
    penalties: list[dict[str, Any]] = []

    breakdown["investigation_any"] = 0.15 if (
        _actions_contain(actions, "read_logs") or _actions_contain(actions, "check_metrics")
    ) else 0.0
    breakdown["investigation_worker"] = 0.20 if (
        _actions_contain(actions, "read_logs", "worker") or _actions_contain(actions, "check_metrics", "worker")
    ) else 0.0
    breakdown["diagnosis_worker_metrics"] = 0.15 if _actions_contain(actions, "check_metrics", "worker") else 0.0
    breakdown["fix_rollback_worker"] = 0.20 if _actions_contain(actions, "rollback", "worker") else 0.0
    breakdown["system_restored"] = 0.30 if state.system_restored else 0.0

    penalty_total = 0.0
    if _actions_contain(actions, "restart_service", "api-server"):
        p = -0.15
        penalty_total += p
        penalties.append({"type": "wrong_service_restart", "target": "api-server", "amount": p,
                          "reason": "Restarted api-server instead of fixing worker"})
    if _actions_contain(actions, "restart_service", "worker"):
        p = -0.10
        penalty_total += p
        penalties.append({"type": "wrong_action_type", "target": "worker", "amount": p,
                          "reason": "Restarted worker instead of rollback — leak recurs"})

    raw = round(max(0.0, min(sum(breakdown.values()) + penalty_total, 1.0)), 4)
    return {"raw_score": raw, "breakdown": breakdown, "penalties": penalties}


def grade_task2(state: "IncidentState") -> float:
    return _grade_task2_detailed(state)["raw_score"]


# ─────────────────────────────────────────────
# Task 3 — Cascading Failure (Hard)
# ─────────────────────────────────────────────

def _grade_task3_detailed(state: "IncidentState") -> dict[str, Any]:
    actions = state.actions_taken
    breakdown: dict[str, float] = {}
    penalties: list[dict[str, Any]] = []

    breakdown["investigation_any"] = 0.10 if actions else 0.0

    postgres_investigated = (
        _actions_contain(actions, "read_logs", "postgres")
        or _actions_contain(actions, "check_metrics", "postgres")
    )
    breakdown["investigation_postgres"] = 0.20 if postgres_investigated else 0.0
    breakdown["root_cause_identified"] = 0.20 if state.root_cause_identified else 0.0
    breakdown["fix_applied"] = 0.20 if state.fix_applied else 0.0
    breakdown["system_restored"] = 0.30 if state.system_restored else 0.0

    # Penalty: blind restarts before root cause
    penalty_total = 0.0
    blind_restarts = 0
    rc_found = False
    for a in actions:
        if a.get("_root_cause_found"):
            rc_found = True
        if not rc_found and a.get("action_type") == "restart_service":
            blind_restarts += 1
    if blind_restarts:
        p = -min(blind_restarts * 0.10, 0.20)
        penalty_total += p
        penalties.append({"type": "blind_restart", "count": blind_restarts, "amount": p,
                          "reason": f"{blind_restarts} restart(s) before root cause identified"})

    # Penalty: disk space red herring
    disk_chases = sum(
        1 for a in actions
        if a.get("action_type") == "exec_command" and
        any(cmd in a.get("target", "").lower() for cmd in ["df -h", "du -sh", "fdisk", "lsblk"])
    )
    if disk_chases:
        p = -min(disk_chases * 0.05, 0.10)
        penalty_total += p
        penalties.append({"type": "red_herring_disk", "count": disk_chases, "amount": p,
                          "reason": "Investigated disk space (red herring from old nginx log)"})

    raw = round(max(0.0, min(sum(breakdown.values()) + penalty_total, 1.0)), 4)
    return {"raw_score": raw, "breakdown": breakdown, "penalties": penalties}


def grade_task3(state: "IncidentState") -> float:
    return _grade_task3_detailed(state)["raw_score"]


# ─────────────────────────────────────────────
# Task 4 — Redis Cache Poisoning (Medium)
# ─────────────────────────────────────────────

def _grade_task4_detailed(state: "IncidentState") -> dict[str, Any]:
    actions = state.actions_taken
    breakdown: dict[str, float] = {}
    penalties: list[dict[str, Any]] = []

    breakdown["investigation_any"] = 0.10 if (
        _actions_contain(actions, "read_logs") or _actions_contain(actions, "check_metrics")
    ) else 0.0
    breakdown["investigation_redis"] = 0.20 if (
        _actions_contain(actions, "read_logs", "redis") or _actions_contain(actions, "check_metrics", "redis")
    ) else 0.0
    breakdown["diagnosis_redis_metrics"] = 0.15 if _actions_contain(actions, "check_metrics", "redis") else 0.0
    breakdown["fix_flush_cache"] = 0.25 if (
        _actions_contain(actions, "exec_command", "flushall") or _actions_contain(actions, "exec_command", "flushdb")
    ) else 0.0
    breakdown["system_restored"] = 0.30 if state.system_restored else 0.0

    penalty_total = 0.0
    if _actions_contain(actions, "restart_service", "api-server"):
        p = -0.10
        penalty_total += p
        penalties.append({"type": "wrong_service_restart", "target": "api-server", "amount": p,
                          "reason": "Restarted api-server — symptom, not cause"})
    if _actions_contain(actions, "restart_service", "redis"):
        p = -0.10
        penalty_total += p
        penalties.append({"type": "wrong_action_type", "target": "redis", "amount": p,
                          "reason": "Restarted redis — poisoned keys still present until FLUSHALL"})

    raw = round(max(0.0, min(sum(breakdown.values()) + penalty_total, 1.0)), 4)
    return {"raw_score": raw, "breakdown": breakdown, "penalties": penalties}


def grade_task4(state: "IncidentState") -> float:
    return _grade_task4_detailed(state)["raw_score"]


# ─────────────────────────────────────────────
# Task 5 — TLS Certificate Expiry (Hard)
# ─────────────────────────────────────────────

def _grade_task5_detailed(state: "IncidentState") -> dict[str, Any]:
    actions = state.actions_taken
    breakdown: dict[str, float] = {}
    penalties: list[dict[str, Any]] = []

    breakdown["investigation_any"] = 0.10 if actions else 0.0
    breakdown["investigation_nginx"] = 0.15 if (
        _actions_contain(actions, "read_logs", "nginx") or _actions_contain(actions, "check_metrics", "nginx")
    ) else 0.0
    breakdown["diagnosis_cert_check"] = 0.20 if (
        _actions_contain(actions, "exec_command", "openssl")
        or _actions_contain(actions, "exec_command", "ssl")
    ) else 0.0
    breakdown["fix_renew_cert"] = 0.25 if (
        _actions_contain(actions, "exec_command", "certbot renew")
        or _actions_contain(actions, "exec_command", "renew")
    ) else 0.0
    breakdown["system_restored"] = 0.30 if state.system_restored else 0.0

    penalty_total = 0.0
    # Blind restarts before diagnosis
    blind_restarts = 0
    rc_found = False
    for a in actions:
        if a.get("_root_cause_found"):
            rc_found = True
        if not rc_found and a.get("action_type") == "restart_service":
            blind_restarts += 1
    if blind_restarts:
        p = -min(blind_restarts * 0.10, 0.20)
        penalty_total += p
        penalties.append({"type": "blind_restart", "count": blind_restarts, "amount": p,
                          "reason": f"{blind_restarts} restart(s) before identifying cert expiry"})

    # Red herring: investigating DDoS (high connection count)
    if _actions_contain(actions, "exec_command", "iptables") or _actions_contain(actions, "exec_command", "fail2ban"):
        p = -0.10
        penalty_total += p
        penalties.append({"type": "red_herring_ddos", "amount": p,
                          "reason": "Investigated DDoS mitigation — high connections caused by TLS retries, not attack"})

    raw = round(max(0.0, min(sum(breakdown.values()) + penalty_total, 1.0)), 4)
    return {"raw_score": raw, "breakdown": breakdown, "penalties": penalties}


def grade_task5(state: "IncidentState") -> float:
    return _grade_task5_detailed(state)["raw_score"]


# ─────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────

GRADER_MAP = {
    "task_1_oom":     grade_task1,
    "task_2_leak":    grade_task2,
    "task_3_cascade": grade_task3,
    "task_4_cache":   grade_task4,
    "task_5_cert":    grade_task5,
}

_DETAILED_MAP = {
    "task_1_oom":     _grade_task1_detailed,
    "task_2_leak":    _grade_task2_detailed,
    "task_3_cascade": _grade_task3_detailed,
    "task_4_cache":   _grade_task4_detailed,
    "task_5_cert":    _grade_task5_detailed,
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


def grade_detailed(state: "IncidentState") -> dict[str, Any]:
    """Grade with full breakdown: score, per-rubric items, and penalties."""
    detail_fn = _DETAILED_MAP.get(state.task_id)
    if detail_fn is None:
        raise ValueError(f"Unknown task_id: {state.task_id!r}")
    result = detail_fn(state)
    result["score"] = round(max(0.01, min(result["raw_score"], 0.99)), 4)
    return result
