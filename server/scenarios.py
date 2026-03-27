"""
Scenario definitions for the three incident tasks.

Each scenario is a frozen dict that seed the environment state on reset().
Modify ONLY the data in this file to change task difficulty/flavor —
the environment engine in environment.py stays the same.
"""

from typing import Any

# ─────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────

_HEALTHY_SERVICES: dict[str, Any] = {
    "api-server":  {"status": "healthy", "cpu": 12.0, "memory": 34.0, "connections": 18, "error_count": 0},
    "postgres":    {"status": "healthy", "cpu":  5.0, "memory": 41.0, "connections":  8, "error_count": 0},
    "redis":       {"status": "healthy", "cpu":  1.0, "memory": 12.0, "connections":  3, "error_count": 0},
    "worker":      {"status": "healthy", "cpu":  8.0, "memory": 28.0, "connections":  5, "error_count": 0},
    "nginx":       {"status": "healthy", "cpu":  2.0, "memory":  8.0, "connections": 42, "error_count": 0},
}


# ─────────────────────────────────────────────
# TASK 1 — Easy: OOM Killer
# ─────────────────────────────────────────────
# api-server was killed by the Linux OOM killer.  Logs are unambiguous.
# Fix: restart_service("api-server")
# ─────────────────────────────────────────────

TASK1: dict[str, Any] = {
    "task_id": "task_1_oom",
    "title": "OOM Killer — API Server Down",
    "difficulty": "easy",
    "description": (
        "The api-server is DOWN and not responding to health checks. "
        "Investigate and restore service."
    ),
    "max_steps": 10,
    "services": {
        "api-server":  {"status": "down",    "cpu":  0.0, "memory":  0.0, "connections": 0, "error_count": 47},
        "postgres":    {"status": "healthy", "cpu":  5.1, "memory": 41.2, "connections":  8, "error_count": 0},
        "redis":       {"status": "healthy", "cpu":  1.0, "memory": 12.0, "connections":  3, "error_count": 0},
        "worker":      {"status": "healthy", "cpu":  9.0, "memory": 31.0, "connections":  5, "error_count": 0},
        "nginx":       {"status": "degraded","cpu":  3.0, "memory":  8.0, "connections": 42, "error_count": 15},
    },
    "logs": {
        "api-server": [
            "2026-03-26T02:11:04Z INFO  [api-server] Handling 1842 req/s",
            "2026-03-26T02:11:19Z WARN  [api-server] Memory usage at 87% of limit",
            "2026-03-26T02:11:31Z WARN  [api-server] Memory usage at 94% of limit",
            "2026-03-26T02:11:44Z WARN  [api-server] Memory usage at 98% of limit",
            "2026-03-26T02:11:51Z ERROR [kernel] Out of memory: Kill process 14821 (api-server) score 912 or sacrifice child",
            "2026-03-26T02:11:51Z ERROR [kernel] Killed process 14821 (api-server) total-vm:2097152kB, anon-rss:1966080kB",
            "2026-03-26T02:11:52Z INFO  [systemd] api-server.service: Main process exited, code=killed, status=9/KILL",
            "2026-03-26T02:11:52Z ERROR [systemd] api-server.service: Failed with result 'oom-kill'.",
        ],
        "nginx": [
            "2026-03-26T02:11:53Z ERROR [nginx] connect() failed (111: Connection refused) while connecting to upstream api-server",
            "2026-03-26T02:11:54Z ERROR [nginx] upstream timed out (110: Connection timed out) /api/v1/health",
            "2026-03-26T02:12:10Z ERROR [nginx] no live upstreams while connecting to upstream api-server",
        ],
        "postgres":    ["2026-03-26T02:11:00Z INFO  [postgres] checkpoint complete: wrote 18 buffers"],
        "redis":       ["2026-03-26T02:11:00Z INFO  [redis] 3 clients connected"],
        "worker":      ["2026-03-26T02:11:00Z INFO  [worker] processed 120 jobs in last 60s"],
    },
    "metrics": {
        "api-server": {"request_rate": 0, "p95_latency_ms": None, "error_rate": 1.0},
        "postgres":   {"query_rate": 42, "p95_latency_ms": 4.2,   "error_rate": 0.0},
        "redis":      {"ops_per_sec": 310, "hit_rate": 0.97},
        "worker":     {"jobs_per_min": 120, "queue_depth": 88},
        "nginx":      {"requests_per_sec": 210, "5xx_rate": 0.87},
    },
    # Grader config — which actions give partial credit
    "grader": {
        "root_cause_actions": [
            {"action_type": "read_logs", "target": "api-server"},
        ],
        "fix_actions": [
            {"action_type": "restart_service", "target": "api-server"},
        ],
        "trap_actions": [],          # no traps on easy task
        "restored_service": "api-server",
    },
}


# ─────────────────────────────────────────────
# TASK 2 — Medium: Memory Leak in Worker
# ─────────────────────────────────────────────
# worker has a memory leak (bad deployment 6h ago). Memory at 94%.
# api-server response times also high — distracts naive agents.
# Fix: rollback("worker"), NOT restart (restart doesn't fix the leak).
# ─────────────────────────────────────────────

TASK2: dict[str, Any] = {
    "task_id": "task_2_leak",
    "title": "Memory Leak — Degraded API Performance",
    "difficulty": "medium",
    "description": (
        "Users are reporting slow API responses (p95 > 8s). "
        "All services appear UP. Identify the root cause and restore normal performance."
    ),
    "max_steps": 15,
    "services": {
        "api-server":  {"status": "degraded", "cpu": 68.0, "memory": 61.0, "connections": 18, "error_count": 312},
        "postgres":    {"status": "healthy",  "cpu":  5.0, "memory": 42.0, "connections":  9, "error_count": 0},
        "redis":       {"status": "healthy",  "cpu":  1.0, "memory": 12.0, "connections":  3, "error_count": 0},
        "worker":      {"status": "degraded", "cpu": 21.0, "memory": 94.0, "connections":  5, "error_count": 28},
        "nginx":       {"status": "degraded", "cpu":  4.0, "memory":  8.0, "connections": 42, "error_count": 89},
    },
    "logs": {
        "worker": [
            "2026-03-26T08:00:01Z INFO  [worker] Deployment v2.4.1 started",
            "2026-03-26T08:00:04Z INFO  [worker] v2.4.1 healthy, replacing v2.4.0",
            "2026-03-26T09:14:22Z WARN  [worker] Heap size 512MB (threshold 450MB)",
            "2026-03-26T10:28:51Z WARN  [worker] Heap size 768MB — GC pressure increasing",
            "2026-03-26T11:43:17Z WARN  [worker] Heap size 1024MB — job processing slowing",
            "2026-03-26T12:58:44Z WARN  [worker] Heap size 1280MB — consider restarting",
            "2026-03-26T14:01:05Z WARN  [worker] Heap size 1472MB — RSS at 94% of container limit (1536MB)",
            "2026-03-26T14:01:05Z WARN  [worker] Job queue backup: 3841 pending",
        ],
        "api-server": [
            "2026-03-26T14:00:10Z WARN  [api-server] Worker job results taking >6000ms",
            "2026-03-26T14:00:41Z WARN  [api-server] p95 latency 8221ms (SLA: 500ms)",
            "2026-03-26T14:01:00Z ERROR [api-server] Worker timeout after 10000ms on /api/v1/process",
            "2026-03-26T14:01:15Z ERROR [api-server] 502 Bad Gateway — worker pool exhausted",
        ],
        "nginx": [
            "2026-03-26T14:00:45Z WARN  [nginx] upstream response time 8.4s for /api/v1/process",
            "2026-03-26T14:01:10Z ERROR [nginx] upstream sent invalid header while reading response header from upstream",
        ],
        "postgres": ["2026-03-26T14:00:00Z INFO  [postgres] checkpoint complete: wrote 22 buffers"],
        "redis":    ["2026-03-26T14:00:00Z INFO  [redis] 3 clients connected, used_memory: 128MB"],
    },
    "metrics": {
        "api-server": {"request_rate": 210, "p95_latency_ms": 8221, "error_rate": 0.34},
        "postgres":   {"query_rate": 40,  "p95_latency_ms": 4.1,   "error_rate": 0.0},
        "redis":      {"ops_per_sec": 290, "hit_rate": 0.96},
        "worker":     {"jobs_per_min": 12, "queue_depth": 3841, "heap_mb": 1472, "memory_trend": "steadily_increasing_since_v2.4.1_deploy"},
        "nginx":      {"requests_per_sec": 210, "5xx_rate": 0.34},
    },
    "grader": {
        "root_cause_actions": [
            {"action_type": "check_metrics", "target": "worker"},
            {"action_type": "read_logs",     "target": "worker"},
        ],
        "fix_actions": [
            {"action_type": "rollback", "target": "worker"},      # correct
        ],
        "wrong_fix_actions": [
            {"action_type": "restart_service", "target": "worker"},  # wrong: leak recurs
            {"action_type": "restart_service", "target": "api-server"},  # wrong service
        ],
        "restored_service": "worker",
    },
}


# ─────────────────────────────────────────────
# TASK 3 — Hard: Cascading Failure (Postgres Connection Exhaustion)
# ─────────────────────────────────────────────
# Root cause: postgres max_connections=25, hit under load.
# Everything is failing. Misleading "disk write error" in nginx logs (old entry).
# api-server has "connection refused" — symptom, not cause.
# Fix: exec_command("ALTER SYSTEM SET max_connections = 200; SELECT pg_reload_conf();")
# Penalty for blind restarts before root cause identified.
# ─────────────────────────────────────────────

TASK3: dict[str, Any] = {
    "task_id": "task_3_cascade",
    "title": "Cascading Failure — Full Outage",
    "difficulty": "hard",
    "description": (
        "Complete service outage. Multiple services are DOWN or DEGRADED. "
        "Users cannot reach the application. Find the single root cause and restore service."
    ),
    "max_steps": 20,
    "services": {
        "api-server":  {"status": "down",    "cpu":  2.0, "memory": 38.0, "connections":  0, "error_count": 1847},
        "postgres":    {"status": "degraded", "cpu": 91.0, "memory": 78.0, "connections": 25, "error_count": 203},
        "redis":       {"status": "healthy",  "cpu":  1.0, "memory": 12.0, "connections":  3, "error_count": 0},
        "worker":      {"status": "down",    "cpu":  1.0, "memory": 22.0, "connections":  0, "error_count": 891},
        "nginx":       {"status": "degraded", "cpu":  6.0, "memory":  9.0, "connections": 42, "error_count": 1923},
    },
    "logs": {
        "nginx": [
            # MISLEADING: old disk write error from 3 weeks ago (different incident)
            "2026-03-05T22:41:00Z ERROR [nginx] write() to '/var/log/nginx/access.log' failed (28: No space left on device)",
            "2026-03-05T22:41:00Z ERROR [nginx] open() '/var/cache/nginx/tmp/0000000001' failed (28: No space left on device)",
            # Current: upstream failing
            "2026-03-26T15:30:01Z ERROR [nginx] upstream timed out (110) while reading response header from upstream api-server",
            "2026-03-26T15:30:04Z ERROR [nginx] connect() failed (111: Connection refused) upstream api-server",
            "2026-03-26T15:30:22Z ERROR [nginx] no live upstreams while connecting to upstream",
        ],
        "api-server": [
            "2026-03-26T15:28:00Z INFO  [api-server] Handling 1800 req/s",
            "2026-03-26T15:28:41Z ERROR [api-server] pq: sorry, too many clients already",
            "2026-03-26T15:28:42Z ERROR [api-server] pq: sorry, too many clients already",
            "2026-03-26T15:28:43Z ERROR [api-server] FATAL: remaining connection slots are reserved for non-replication superuser connections",
            "2026-03-26T15:28:50Z ERROR [api-server] database connection pool exhausted — all 25 slots taken",
            "2026-03-26T15:28:51Z ERROR [api-server] health check failed: unable to acquire DB connection",
            "2026-03-26T15:28:52Z INFO  [systemd] api-server.service: Main process exited (unhealthy)",
        ],
        "postgres": [
            "2026-03-26T15:27:00Z INFO  [postgres] connections: 18/25",
            "2026-03-26T15:27:40Z WARN  [postgres] connections: 23/25 — approaching limit",
            "2026-03-26T15:28:01Z WARN  [postgres] connections: 25/25 — at max_connections limit",
            "2026-03-26T15:28:41Z ERROR [postgres] FATAL: sorry, too many clients already",
            "2026-03-26T15:28:42Z ERROR [postgres] FATAL: remaining connection slots are reserved for non-replication superuser connections",
            "2026-03-26T15:28:43Z INFO  [postgres] max_connections = 25 (current setting)",
        ],
        "worker": [
            "2026-03-26T15:28:44Z ERROR [worker] pq: sorry, too many clients already — job processing halted",
            "2026-03-26T15:28:50Z ERROR [worker] Failed to acquire DB connection after 5 retries",
            "2026-03-26T15:28:51Z INFO  [systemd] worker.service: Main process exited (unhealthy)",
        ],
        "redis": ["2026-03-26T15:28:00Z INFO  [redis] 3 clients connected, no issues"],
    },
    "metrics": {
        "api-server":  {"request_rate": 0,    "p95_latency_ms": None, "error_rate": 1.0},
        "postgres":    {"query_rate": 0,  "p95_latency_ms": None, "active_connections": 25, "max_connections": 25, "error_rate": 1.0, "connection_wait_queue": 847},
        "redis":       {"ops_per_sec": 310, "hit_rate": 0.97},
        "worker":      {"jobs_per_min": 0, "queue_depth": 9441},
        "nginx":       {"requests_per_sec": 840, "5xx_rate": 0.99},
        # Disk is FINE — the nginx error was from 3 weeks ago
        "system":      {"disk_usage_percent": 23, "disk_free_gb": 38},
    },
    "grader": {
        "root_cause_actions": [
            {"action_type": "read_logs",     "target": "postgres"},
            {"action_type": "check_metrics", "target": "postgres"},
        ],
        "fix_actions": [
            # Must exec the correct postgres command
            {"action_type": "exec_command", "target": "ALTER SYSTEM SET max_connections = 200"},
            {"action_type": "exec_command", "target": "pg_reload_conf"},
        ],
        "trap_actions": [
            # Blind restarts before root cause — penalize
            {"action_type": "restart_service", "target": "api-server"},
            {"action_type": "restart_service", "target": "worker"},
            # Disk investigation — wrong path (misleading log)
            {"action_type": "exec_command", "target": "df -h"},
            {"action_type": "exec_command", "target": "du -sh"},
        ],
        "restored_service": "postgres",
    },
}

# Ordered list for easy iteration
ALL_TASKS: list[dict[str, Any]] = [TASK1, TASK2, TASK3]

TASK_MAP: dict[str, dict[str, Any]] = {t["task_id"]: t for t in ALL_TASKS}
