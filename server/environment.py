"""
Core environment logic.  Handles action dispatch, state mutation, and
episode boundaries.  No HTTP code lives here.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from openenv.core.env_server import Environment

from ..models import IncidentAction, IncidentObservation, IncidentState
from .scenarios import TASK_MAP, ALL_TASKS, TASK1


class IncidentEnvironment(Environment):
    """
    Production Incident Response environment.

    Episode flow
    ────────────
    1. reset(task_id?)  → loads scenario, returns initial observation
    2. step(action)     → updates simulated system state, returns observation
    3. state()          → returns IncidentState for grader inspection

    Episode ends when:
    - agent calls restart/fix that restores the system  →  done=True
    - step_count reaches scenario max_steps            →  done=True (timed out)
    """

    def __init__(self) -> None:
        super().__init__()
        self._state: IncidentState = IncidentState()
        self._scenario: dict[str, Any] = {}
        self._services: dict[str, Any] = {}
        self._logs: dict[str, list[str]] = {}
        self._metrics: dict[str, Any] = {}

    # ──────────────────────────────────────────────
    # OpenEnv spec: reset / step / state
    # ──────────────────────────────────────────────

    def reset(
        self,
        seed: int | None = None,
        episode_id: str | None = None,
        task_id: str | None = None,
        **kwargs: Any,
    ) -> IncidentObservation:
        """
        Start a new episode.  Loads TASK1 by default.
        Pass task_id="task_1_oom" | "task_2_leak" | "task_3_cascade" to choose.
        """
        if task_id and task_id not in TASK_MAP:
            raise ValueError(f"Unknown task_id: {task_id!r}.  Valid: {list(TASK_MAP)}")

        scenario = TASK_MAP[task_id] if task_id else TASK1

        self._scenario = scenario
        self._services = copy.deepcopy(scenario["services"])
        self._logs = copy.deepcopy(scenario["logs"])
        self._metrics = copy.deepcopy(scenario["metrics"])

        self._state = IncidentState(
            episode_id=episode_id or str(uuid.uuid4()),
            task_id=scenario["task_id"],
            step_count=0,
            actions_taken=[],
            root_cause_identified=False,
            fix_applied=False,
            system_restored=False,
            current_score=0.0,
        )

        return IncidentObservation(
            output=(
                f"Incident Response Environment — Task: {scenario['title']}\n\n"
                f"Difficulty: {scenario['difficulty'].upper()}\n\n"
                f"{scenario['description']}\n\n"
                f"Available actions: read_logs, check_metrics, restart_service, "
                f"rollback, exec_command, check_network\n\n"
                f"System snapshot:\n{self._format_services()}"
            ),
            services=copy.deepcopy(self._services),
            done=False,
            success=True,
        )  # type: ignore[call-arg]

    def step(
        self,
        action: IncidentAction,
        timeout_s: float | None = None,
        **kwargs: Any,
    ) -> IncidentObservation:
        """Execute one agent action and return the resulting observation."""
        if not self._scenario:
            return IncidentObservation(
                output="Call reset() first to start an episode.",
                services={},
                done=False,
                success=False,
                error="No active episode.",
            )

        self._state.step_count += 1
        max_steps: int = self._scenario.get("max_steps", 15)

        # Record action (with root_cause sentinel for grader)
        action_record: dict[str, Any] = {
            "step": self._state.step_count,
            "action_type": action.action_type,
            "target": action.target,
            "parameters": action.parameters,
            "_root_cause_found": self._state.root_cause_identified,
        }
        self._state.actions_taken.append(action_record)

        # Dispatch
        try:
            obs = self._dispatch(action)
        except Exception as exc:
            obs = IncidentObservation(
                output=f"Action failed: {exc}",
                services=copy.deepcopy(self._services),
                done=False,
                success=False,
                error=str(exc),
            )

        # Check episode end conditions
        if self._state.system_restored:
            obs.done = True
            obs.output += "\n\n✓ System fully restored. Episode complete."
        elif self._state.step_count >= max_steps:
            obs.done = True
            obs.output += f"\n\n✗ Max steps ({max_steps}) reached without restoring system."

        # Update rolling score and set per-step reward
        from .graders import grade
        prev_score = self._state.current_score
        self._state.current_score = grade(self._state)
        # Reward = delta in score: positive for progress, negative for mistakes
        obs.reward = round(self._state.current_score - prev_score, 4)

        obs.services = copy.deepcopy(self._services)
        return obs

    @property
    def state(self) -> IncidentState:
        return self._state

    # ──────────────────────────────────────────────
    # Action handlers
    # ──────────────────────────────────────────────

    def _dispatch(self, action: IncidentAction) -> IncidentObservation:
        handlers = {
            "read_logs":       self._handle_read_logs,
            "check_metrics":   self._handle_check_metrics,
            "restart_service": self._handle_restart_service,
            "rollback":        self._handle_rollback,
            "exec_command":    self._handle_exec_command,
            "check_network":   self._handle_check_network,
        }
        handler = handlers.get(action.action_type)
        if handler is None:
            return IncidentObservation(
                output=(
                    f"Unknown action_type: {action.action_type!r}.\n"
                    f"Valid: {', '.join(handlers)}"
                ),
                services=copy.deepcopy(self._services),
                success=False,
                error=f"Unknown action_type: {action.action_type!r}",
            )
        return handler(action)

    def _handle_read_logs(self, action: IncidentAction) -> IncidentObservation:
        svc = action.target
        if svc not in self._logs:
            return IncidentObservation(
                output=f"No service named '{svc}'. Available: {', '.join(self._logs)}",
                services=copy.deepcopy(self._services),
                success=False,
                error=f"Service not found: {svc}",
            )
        lines = action.parameters.get("lines", 20)
        log_lines = self._logs[svc][-int(lines):]
        output = f"=== Logs: {svc} (last {len(log_lines)} lines) ===\n" + "\n".join(log_lines)

        # Check if this reveals root cause
        self._check_root_cause_revealed(action)

        return IncidentObservation(output=output, services=copy.deepcopy(self._services))

    def _handle_check_metrics(self, action: IncidentAction) -> IncidentObservation:
        svc = action.target
        if svc == "all":
            metrics_str = "\n".join(
                f"  {s}: {m}" for s, m in self._metrics.items()
            )
            output = f"=== All Metrics ===\n{metrics_str}"
        elif svc in self._metrics:
            output = f"=== Metrics: {svc} ===\n{self._metrics[svc]}"
        else:
            return IncidentObservation(
                output=f"No metrics for '{svc}'. Available: {', '.join(self._metrics)}, all",
                services=copy.deepcopy(self._services),
                success=False,
                error=f"Service not found: {svc}",
            )

        self._check_root_cause_revealed(action)
        return IncidentObservation(output=output, services=copy.deepcopy(self._services))

    def _handle_restart_service(self, action: IncidentAction) -> IncidentObservation:
        svc = action.target
        if svc not in self._services:
            return IncidentObservation(
                output=f"No service named '{svc}'.",
                services=copy.deepcopy(self._services),
                success=False,
                error=f"Service not found: {svc}",
            )

        task_id = self._state.task_id
        grader_cfg = self._scenario["grader"]

        output_lines = [f"Restarting {svc}..."]

        if task_id == "task_1_oom" and svc == "api-server":
            # Correct fix for task 1
            self._services["api-server"]["status"] = "healthy"
            self._services["api-server"]["cpu"] = 14.0
            self._services["api-server"]["memory"] = 38.0
            self._services["api-server"]["error_count"] = 0
            self._services["nginx"]["status"] = "healthy"
            self._services["nginx"]["error_count"] = 0
            self._state.fix_applied = True
            self._state.system_restored = True
            output_lines.append(f"✓ {svc} started successfully — PID 15042")
            output_lines.append("✓ nginx upstreams healthy")

        elif task_id == "task_3_cascade" and svc in ("api-server", "worker"):
            # Blind restart of symptom services — they come up but immediately fail again
            output_lines.append(f"✓ {svc} started — PID {18000 + hash(svc) % 1000}")
            output_lines.append(f"  ... {svc} health check: FAILED (DB connection refused)")
            output_lines.append(f"  {svc} re-entering crash loop. Root cause not fixed.")
            # Service stays down
            self._services[svc]["status"] = "down"

        elif task_id == "task_4_cache" and svc in ("api-server", "redis"):
            # Restarting doesn't help — poisoned cache keys persist
            if svc == "api-server":
                output_lines.append(f"✓ {svc} restarted — PID 16044")
                output_lines.append("  ... api-server reading cache → same corrupt keys → 500s continue")
                output_lines.append("  Cache poisoning persists. Restart does not clear Redis data.")
                self._services["api-server"]["error_count"] = 4218  # errors continue
            elif svc == "redis":
                output_lines.append(f"✓ {svc} restarted — PID 16100")
                output_lines.append("  ... redis loaded RDB snapshot from disk → poisoned keys restored")
                output_lines.append("  Cache data persisted through restart. Use FLUSHALL to clear.")

        elif task_id == "task_5_cert" and svc == "nginx":
            # Restarting nginx without renewing cert doesn't help
            output_lines.append(f"✓ {svc} restarted — PID 17050")
            if self._state.fix_applied:
                # Cert was renewed, now nginx picks up new cert
                self._services["nginx"]["status"] = "healthy"
                self._services["nginx"]["error_count"] = 0
                self._services["nginx"]["cpu"] = 3.0
                self._services["nginx"]["connections"] = 42
                self._state.system_restored = True
                output_lines.append("✓ nginx loaded new TLS certificate")
                output_lines.append("✓ SSL handshakes succeeding — upstream connections restored")
            else:
                output_lines.append("  ... nginx still cannot establish SSL to api-server:8443")
                output_lines.append("  SSL certificate still expired. Renew certificate first.")

        elif task_id == "task_5_cert" and svc == "api-server":
            output_lines.append(f"✓ {svc} restarted — PID 17080")
            output_lines.append("  api-server was already healthy. Problem is in the TLS certificate, not the server.")

        else:
            # Generic restart — service comes up healthy
            self._services[svc]["status"] = "healthy"
            self._services[svc]["error_count"] = 0
            self._state.fix_applied = True
            self._check_system_restored()
            output_lines.append(f"✓ {svc} restarted — status: healthy")

        return IncidentObservation(
            output="\n".join(output_lines),
            services=copy.deepcopy(self._services),
        )

    def _handle_rollback(self, action: IncidentAction) -> IncidentObservation:
        svc = action.target
        if svc not in self._services:
            return IncidentObservation(
                output=f"No service named '{svc}'.",
                services=copy.deepcopy(self._services),
                success=False,
                error=f"Service not found: {svc}",
            )

        task_id = self._state.task_id
        output_lines = [f"Rolling back {svc} to previous deployment..."]

        if task_id == "task_2_leak" and svc == "worker":
            # Correct fix for task 2
            self._services["worker"]["status"] = "healthy"
            self._services["worker"]["memory"] = 28.0
            self._services["worker"]["cpu"] = 8.0
            self._services["worker"]["error_count"] = 0
            self._services["api-server"]["status"] = "healthy"
            self._services["api-server"]["error_count"] = 0
            self._metrics["worker"]["heap_mb"] = 245
            self._metrics["worker"]["memory_trend"] = "stable"
            self._metrics["worker"]["jobs_per_min"] = 118
            self._metrics["api-server"]["p95_latency_ms"] = 84
            self._metrics["api-server"]["error_rate"] = 0.0
            self._state.fix_applied = True
            self._state.system_restored = True
            output_lines.append("✓ Rolled back worker to v2.4.0")
            output_lines.append("✓ Worker heap memory stabilising: 245MB")
            output_lines.append("✓ API p95 latency recovering: 84ms")
        else:
            output_lines.append(f"✓ {svc} rolled back to previous version.")
            self._services[svc]["status"] = "healthy"
            self._services[svc]["error_count"] = 0
            self._state.fix_applied = True
            self._check_system_restored()

        return IncidentObservation(
            output="\n".join(output_lines),
            services=copy.deepcopy(self._services),
        )

    def _handle_exec_command(self, action: IncidentAction) -> IncidentObservation:
        cmd = action.target.strip()
        task_id = self._state.task_id
        output_lines = [f"$ {cmd}"]

        # Task 3 correct fixes
        if task_id == "task_3_cascade":
            if "max_connections" in cmd.lower() and ("200" in cmd or "500" in cmd):
                self._state.fix_applied = True
                output_lines.append("ALTER SYSTEM")
                output_lines.append("-- Setting will take effect after pg_reload_conf()")

            elif "pg_reload_conf" in cmd.lower():
                if self._state.fix_applied:
                    # Full cascade recovery
                    self._services["postgres"]["status"] = "healthy"
                    self._services["postgres"]["connections"] = 5
                    self._services["postgres"]["cpu"] = 6.0
                    self._services["postgres"]["error_count"] = 0
                    self._services["api-server"]["status"] = "healthy"
                    self._services["api-server"]["error_count"] = 0
                    self._services["worker"]["status"] = "healthy"
                    self._services["worker"]["error_count"] = 0
                    self._services["nginx"]["status"] = "healthy"
                    self._services["nginx"]["error_count"] = 0
                    self._metrics["postgres"]["active_connections"] = 5
                    self._metrics["postgres"]["max_connections"] = 200
                    self._metrics["postgres"]["error_rate"] = 0.0
                    self._state.system_restored = True
                    output_lines.append(" pg_reload_conf")
                    output_lines.append("-----------------")
                    output_lines.append(" t")
                    output_lines.append("(1 row)")
                    output_lines.append("")
                    output_lines.append("✓ Postgres reloaded: max_connections now 200")
                    output_lines.append("✓ Cascade recovered — all services healthy")
                else:
                    output_lines.append(" pg_reload_conf")
                    output_lines.append("-----------------")
                    output_lines.append(" t")
                    output_lines.append("(1 row)")
                    output_lines.append("Note: max_connections still 25 — pg_reload_conf only flushes pending ALTER SYSTEM")

            elif any(d in cmd for d in ["df -h", "df -ah", "du -sh", "fdisk", "lsblk"]):
                output_lines.extend([
                    "Filesystem      Size  Used Avail Use% Mounted on",
                    "/dev/sda1        50G   12G   38G  23% /",
                    "/dev/sda2       100G   41G   59G  41% /data",
                    "",
                    "(Disk usage appears normal.)",
                ])
            else:
                output_lines.append(f"Command executed: {cmd}")

        # Task 4: Redis cache poisoning
        elif task_id == "task_4_cache":
            if "flushall" in cmd.lower() or "flushdb" in cmd.lower():
                self._state.fix_applied = True
                self._services["api-server"]["status"] = "healthy"
                self._services["api-server"]["cpu"] = 14.0
                self._services["api-server"]["error_count"] = 0
                self._services["nginx"]["status"] = "healthy"
                self._services["nginx"]["error_count"] = 0
                self._metrics["redis"]["used_memory_mb"] = 12
                self._metrics["redis"]["keyspace_keys"] = 0
                self._metrics["redis"]["corrupted_keys_estimate"] = "0"
                self._metrics["api-server"]["error_rate"] = 0.0
                self._metrics["api-server"]["cache_error_rate"] = 0.0
                self._state.system_restored = True
                output_lines.append("OK")
                output_lines.append("✓ All Redis keys flushed — 184210 keys removed")
                output_lines.append("✓ Cache rebuilding from database (clean entries)")
                output_lines.append("✓ API error rate dropping to 0%")
            elif "keys" in cmd.lower() or "scan" in cmd.lower():
                output_lines.extend([
                    "user:profile:8812 → (binary/corrupt msgpack v1 data)",
                    "product:detail:441 → (binary/corrupt msgpack v1 data)",
                    "user:profile:1204 → (binary/corrupt msgpack v1 data)",
                    "... 184207 more keys",
                    "(Most keys contain v1 msgpack format; api-server v3.1.0 expects v2)",
                ])
            else:
                output_lines.append(f"Command executed: {cmd}")

        # Task 5: TLS certificate expiry
        elif task_id == "task_5_cert":
            if "certbot" in cmd.lower() and "renew" in cmd.lower():
                self._state.fix_applied = True
                self._metrics["api-server"]["tls_cert_expiry"] = "VALID (renewed)"
                self._metrics["api-server"]["tls_cert_not_after"] = "2026-06-24T13:30:00Z"
                output_lines.extend([
                    "Saving debug log to /var/log/letsencrypt/letsencrypt.log",
                    "Renewing an existing certificate for api-server.internal",
                    "",
                    "Successfully received certificate.",
                    "Certificate is saved at: /etc/letsencrypt/live/api-server.internal/fullchain.pem",
                    "Key is saved at:         /etc/letsencrypt/live/api-server.internal/privkey.pem",
                    "",
                    "✓ Certificate renewed — valid until 2026-06-24T13:30:00Z",
                    "Note: Restart nginx to load the new certificate.",
                ])
            elif "openssl" in cmd.lower() or "ssl" in cmd.lower():
                output_lines.extend([
                    "Connecting to api-server:8443...",
                    "subject=CN = api-server.internal",
                    "issuer=CN = Let's Encrypt Authority X3",
                    "notBefore=Mar 26 13:30:00 2025 GMT",
                    "notAfter=Mar 26 13:30:00 2026 GMT",
                    "",
                    "verify error:num=10:certificate has expired",
                    "Verify return code: 10 (certificate has expired)",
                    "",
                    "★ Certificate expired 45 minutes ago.",
                ])
            elif any(d in cmd.lower() for d in ["iptables", "fail2ban", "ufw"]):
                output_lines.extend([
                    "Chain INPUT (policy ACCEPT 0 packets, 0 bytes)",
                    "Chain FORWARD (policy ACCEPT 0 packets, 0 bytes)",
                    "Chain OUTPUT (policy ACCEPT 0 packets, 0 bytes)",
                    "",
                    "(No firewall rules configured. No evidence of DDoS — high connections caused by TLS retry storm.)",
                ])
            else:
                output_lines.append(f"Command executed: {cmd}")

        else:
            output_lines.append(f"Command executed: {cmd}")
            output_lines.append("(No specific simulation for this command in current task)")

        return IncidentObservation(
            output="\n".join(output_lines),
            services=copy.deepcopy(self._services),
        )

    def _handle_check_network(self, action: IncidentAction) -> IncidentObservation:
        target = action.target  # e.g. "api-server->postgres"
        task_id = self._state.task_id

        if task_id == "task_3_cascade" and "postgres" in target:
            output = (
                f"Network check: {target}\n"
                f"  TCP connection: ESTABLISHED (port 5432 reachable)\n"
                f"  But postgres rejecting connections: 'sorry, too many clients already'\n"
                f"  → Network is fine; postgres itself is the bottleneck."
            )
            # Hints at postgres — counts toward root cause discovery
            self._state.root_cause_identified = True
        elif task_id == "task_5_cert" and ("api-server" in target or "nginx" in target):
            output = (
                f"Network check: {target}\n"
                f"  TCP connection: ESTABLISHED (port 8443 reachable)\n"
                f"  SSL handshake: FAILED — certificate verify failed\n"
                f"  → Network is fine; TLS certificate on api-server has expired."
            )
        elif task_id == "task_4_cache" and "redis" in target:
            output = (
                f"Network check: {target}\n"
                f"  TCP connection: ESTABLISHED (port 6379 reachable)\n"
                f"  PING → PONG (redis responsive)\n"
                f"  → Network is fine; redis is reachable but serving corrupt cache data."
            )
        else:
            svc = action.target.split("->")[-1] if "->" in action.target else action.target
            status = self._services.get(svc, {}).get("status", "unknown")
            output = (
                f"Network check: {target}\n"
                f"  Target service status: {status}\n"
                f"  TCP: {'ESTABLISHED' if status == 'healthy' else 'REFUSED / TIMEOUT'}"
            )

        return IncidentObservation(output=output, services=copy.deepcopy(self._services))

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _check_root_cause_revealed(self, action: IncidentAction) -> None:
        """
        Mark root_cause_identified when the agent reads the right logs/metrics.
        Each task has defined root_cause_actions in the grader config.
        """
        if self._state.root_cause_identified:
            return
        rc_actions = self._scenario.get("grader", {}).get("root_cause_actions", [])
        for rc in rc_actions:
            if (
                action.action_type == rc["action_type"]
                and rc["target"].lower() in action.target.lower()
            ):
                self._state.root_cause_identified = True
                return

    def _check_system_restored(self) -> None:
        """Mark system_restored if all services are healthy after an action."""
        if all(s["status"] == "healthy" for s in self._services.values()):
            self._state.system_restored = True

    def _format_services(self) -> str:
        lines = []
        for name, info in self._services.items():
            status_icon = {"healthy": "✓", "degraded": "⚠", "down": "✗"}.get(info["status"], "?")
            lines.append(
                f"  {status_icon} {name:<14} status={info['status']:<9} "
                f"cpu={info['cpu']:>5.1f}%  mem={info['memory']:>5.1f}%  "
                f"errors={info['error_count']}"
            )
        return "\n".join(lines)
