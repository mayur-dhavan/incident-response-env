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


# ─────────────────────────────────────────────
# TASK 4 — Medium: Redis Cache Poisoning
# ─────────────────────────────────────────────
# A bad deployment wrote corrupted serialization to Redis.
# api-server reads stale/poisoned cache → 500 errors on every cache hit.
# Cache misses fall through to postgres (which is healthy).
# Naïve fix: restart api-server (doesn't help, cache still poisoned).
# Correct fix: exec_command("redis-cli FLUSHALL") to clear poisoned keys.
# Red herring: high CPU on api-server (it's busy re-serializing bad data).
# ─────────────────────────────────────────────

TASK4: dict[str, Any] = {
    "task_id": "task_4_cache",
    "title": "Cache Poisoning — Intermittent 500 Errors",
    "difficulty": "medium",
    "description": (
        "Users are reporting intermittent 500 Internal Server Errors on "
        "roughly 60% of requests. The errors started ~2 hours ago after "
        "a routine deployment. Investigate and restore service."
    ),
    "max_steps": 15,
    "services": {
        "api-server":  {"status": "degraded", "cpu": 78.0, "memory": 52.0, "connections": 24, "error_count": 4218},
        "postgres":    {"status": "healthy",  "cpu":  6.0, "memory": 42.0, "connections":  9, "error_count": 0},
        "redis":       {"status": "healthy",  "cpu":  3.0, "memory": 48.0, "connections":  8, "error_count": 0},
        "worker":      {"status": "healthy",  "cpu":  7.0, "memory": 29.0, "connections":  5, "error_count": 0},
        "nginx":       {"status": "degraded", "cpu":  4.0, "memory":  8.0, "connections": 42, "error_count": 2531},
    },
    "logs": {
        "api-server": [
            "2026-03-26T10:00:01Z INFO  [api-server] Deployment v3.1.0 started",
            "2026-03-26T10:00:04Z INFO  [api-server] v3.1.0 healthy, replacing v3.0.9",
            "2026-03-26T10:14:22Z ERROR [api-server] Failed to deserialize cache entry for key user:profile:8812 — InvalidJSON",
            "2026-03-26T10:14:22Z ERROR [api-server] HTTP 500 on GET /api/v1/users/8812 — cache deserialization error",
            "2026-03-26T10:28:51Z ERROR [api-server] Failed to deserialize cache entry for key product:detail:441 — InvalidJSON",
            "2026-03-26T10:28:51Z WARN  [api-server] Cache error rate 62% — most cache hits returning corrupt data",
            "2026-03-26T11:43:17Z ERROR [api-server] Serialization format mismatch: expected msgpack v2, got msgpack v1 in cache",
            "2026-03-26T12:01:05Z ERROR [api-server] 4218 cache-related 500s in last 2 hours",
        ],
        "redis": [
            "2026-03-26T10:00:00Z INFO  [redis] 8 clients connected, used_memory: 412MB",
            "2026-03-26T10:00:01Z INFO  [redis] keyspace: db0 keys=184210, expires=91200",
            "2026-03-26T10:14:00Z INFO  [redis] hit_rate: 0.62, miss_rate: 0.38",
            "2026-03-26T12:01:00Z INFO  [redis] used_memory: 418MB, peak: 420MB",
            "2026-03-26T12:01:00Z INFO  [redis] evicted_keys: 0, expired_keys: 412",
        ],
        "nginx": [
            "2026-03-26T10:14:30Z ERROR [nginx] upstream returned 500 for GET /api/v1/users/8812",
            "2026-03-26T10:14:31Z ERROR [nginx] upstream returned 500 for GET /api/v1/products/441",
            "2026-03-26T12:01:00Z WARN  [nginx] 5xx error rate at 62% over last 2 hours",
        ],
        "postgres": ["2026-03-26T12:00:00Z INFO  [postgres] checkpoint complete: wrote 24 buffers"],
        "worker":   ["2026-03-26T12:00:00Z INFO  [worker] processed 118 jobs in last 60s"],
    },
    "metrics": {
        "api-server": {"request_rate": 420, "p95_latency_ms": 1240, "error_rate": 0.62, "cache_error_rate": 0.62},
        "postgres":   {"query_rate": 168, "p95_latency_ms": 8.1, "error_rate": 0.0},
        "redis":      {"ops_per_sec": 4200, "hit_rate": 0.62, "used_memory_mb": 418, "keyspace_keys": 184210,
                       "corrupted_keys_estimate": "~114k (62% of keyspace)", "evicted_keys": 0},
        "worker":     {"jobs_per_min": 118, "queue_depth": 12},
        "nginx":      {"requests_per_sec": 420, "5xx_rate": 0.62},
    },
    "grader": {
        "root_cause_actions": [
            {"action_type": "read_logs",     "target": "redis"},
            {"action_type": "check_metrics", "target": "redis"},
            {"action_type": "read_logs",     "target": "api-server"},
        ],
        "fix_actions": [
            {"action_type": "exec_command", "target": "FLUSHALL"},
            {"action_type": "exec_command", "target": "flushdb"},
        ],
        "wrong_fix_actions": [
            {"action_type": "restart_service", "target": "api-server"},
            {"action_type": "restart_service", "target": "redis"},
        ],
        "restored_service": "redis",
    },
}


# ─────────────────────────────────────────────
# TASK 5 — Hard: TLS Certificate Expiry
# ─────────────────────────────────────────────
# The internal TLS certificate for the api-server expired 45 minutes ago.
# nginx (reverse proxy) can't establish TLS to backend → 502 Bad Gateway.
# Misleading: high connection count on nginx looks like a DDoS attack.
# api-server itself logs show it started fine (it listens, but TLS fails).
# Fix: exec_command("certbot renew --force-renewal") + restart_service nginx.
# ─────────────────────────────────────────────

TASK5: dict[str, Any] = {
    "task_id": "task_5_cert",
    "title": "TLS Certificate Expiry — 502 Bad Gateway",
    "difficulty": "hard",
    "description": (
        "Users are getting 502 Bad Gateway errors since ~45 minutes ago. "
        "The application was working fine yesterday. "
        "Multiple services show unusual behavior. Investigate the root cause."
    ),
    "max_steps": 20,
    "services": {
        "api-server":  {"status": "healthy",  "cpu": 4.0,  "memory": 32.0, "connections":  0, "error_count": 0},
        "postgres":    {"status": "healthy",  "cpu": 5.0,  "memory": 41.0, "connections":  8, "error_count": 0},
        "redis":       {"status": "healthy",  "cpu": 1.0,  "memory": 12.0, "connections":  3, "error_count": 0},
        "worker":      {"status": "healthy",  "cpu": 8.0,  "memory": 28.0, "connections":  5, "error_count": 0},
        "nginx":       {"status": "degraded", "cpu": 45.0, "memory": 18.0, "connections": 847, "error_count": 12841},
    },
    "logs": {
        "nginx": [
            "2026-03-26T14:15:00Z INFO  [nginx] reload: PID 4128",
            "2026-03-26T14:15:01Z ERROR [nginx] SSL_do_handshake() failed (SSL: error:0A000086:SSL routines::certificate verify failed)",
            "2026-03-26T14:15:01Z ERROR [nginx] upstream SSL certificate has expired while SSL handshaking to api-server:8443",
            "2026-03-26T14:15:02Z ERROR [nginx] 502 Bad Gateway — peer closed connection in SSL handshake",
            "2026-03-26T14:15:03Z WARN  [nginx] upstream connection retries exhausted for api-server:8443",
            "2026-03-26T14:30:00Z ERROR [nginx] 12841 failed SSL handshakes in last 15 minutes",
            # Misleading: high connections look like DDoS
            "2026-03-26T14:30:01Z WARN  [nginx] active connections: 847 (threshold: 500)",
            "2026-03-26T14:30:02Z WARN  [nginx] connection surge detected — possible SYN flood or client retry storm",
        ],
        "api-server": [
            "2026-03-26T14:10:00Z INFO  [api-server] Listening on 0.0.0.0:8443 (TLS)",
            "2026-03-26T14:10:01Z INFO  [api-server] Health check: OK (internal)",
            "2026-03-26T14:15:02Z WARN  [api-server] No incoming connections for 5 minutes — verify upstream proxy",
            "2026-03-26T14:30:00Z WARN  [api-server] No incoming connections for 20 minutes — upstream may be down",
        ],
        "postgres": ["2026-03-26T14:15:00Z INFO  [postgres] checkpoint complete: wrote 18 buffers"],
        "redis":    ["2026-03-26T14:15:00Z INFO  [redis] 3 clients connected, no issues"],
        "worker":   ["2026-03-26T14:15:00Z INFO  [worker] processed 120 jobs in last 60s"],
    },
    "metrics": {
        "api-server": {"request_rate": 0, "p95_latency_ms": None, "error_rate": 0.0, "tls_cert_expiry": "EXPIRED (45m ago)",
                       "tls_cert_not_after": "2026-03-26T13:30:00Z"},
        "postgres":   {"query_rate": 42,  "p95_latency_ms": 4.2, "error_rate": 0.0},
        "redis":      {"ops_per_sec": 310, "hit_rate": 0.97},
        "worker":     {"jobs_per_min": 120, "queue_depth": 88},
        "nginx":      {"requests_per_sec": 840, "5xx_rate": 0.98, "ssl_handshake_failures": 12841,
                       "active_connections": 847},
        "system":     {"disk_usage_percent": 18, "disk_free_gb": 42,
                       "iptables_drop_count": 0, "syn_flood_detected": False},
    },
    "grader": {
        "root_cause_actions": [
            {"action_type": "read_logs",     "target": "nginx"},
            {"action_type": "check_metrics", "target": "api-server"},
        ],
        "fix_actions": [
            {"action_type": "exec_command", "target": "certbot renew"},
        ],
        "trap_actions": [
            {"action_type": "restart_service", "target": "api-server"},
            {"action_type": "restart_service", "target": "nginx"},
            {"action_type": "exec_command", "target": "iptables"},
            {"action_type": "exec_command", "target": "fail2ban"},
        ],
        "restored_service": "nginx",
    },
}


# Ordered list for easy iteration
ALL_TASKS: list[dict[str, Any]] = [TASK1, TASK2, TASK3, TASK4, TASK5]

TASK_MAP: dict[str, dict[str, Any]] = {t["task_id"]: t for t in ALL_TASKS}
