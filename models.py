from typing import Any, Dict, List, Literal, Optional

from openenv.core.env_server import Action, Observation, State
from pydantic import Field

ACTION_TYPES = Literal[
    "read_logs",
    "check_metrics",
    "restart_service",
    "rollback",
    "exec_command",
    "check_network",
]


class IncidentAction(Action):
    """
    Action an agent can take in the incident response environment.

    action_type: one of
        "read_logs"       - read recent logs for a service
        "check_metrics"   - check CPU/memory/connection metrics for a service
        "restart_service" - restart a service
        "rollback"        - rollback a service to previous deployment
        "exec_command"    - run a diagnostic/repair SQL or shell command
        "check_network"   - check connectivity between two services
    target: service name or command string
    parameters: optional extra kwargs (e.g. {"lines": 50} for read_logs)
    """

    action_type: ACTION_TYPES = "read_logs"
    target: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)


class IncidentObservation(Observation):
    """
    What the agent sees after each action.

    output:          Human-readable result of the action (log snippet, metric table, etc.)
    services:        Current health snapshot of all services (status, cpu, memory, connections, error_count)
    success:         False only if the action itself was invalid/errored
    error:           Populated when success=False
    steps_remaining: Steps left in the episode budget (None before first step)
    partial_score:   Running grader score after this step — lets the agent see if it's making progress
    done:            True when episode is over (fix verified or max_steps reached)
    reward:          Per-step reward = delta in grader score (positive = progress, negative = mistake)
    """

    output: str = ""
    services: Dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error: str = ""
    steps_remaining: Optional[int] = None
    partial_score: float = 0.0
    # Note: 'done' and 'reward' are already defined in the parent Observation class


class IncidentState(State):
    """
    Episode-level tracking used by graders.

    task_id:               which of the 3 tasks is running
    actions_taken:         ordered list of actions (for grader replay)
    root_cause_identified: agent issued the correct diagnostic action
    fix_applied:           correct repair action was taken
    system_restored:       final system health check passed
    current_score:         rolling partial-credit score
    """

    task_id: str = ""
    actions_taken: List[Dict[str, Any]] = Field(default_factory=list)
    root_cause_identified: bool = False
    fix_applied: bool = False
    system_restored: bool = False
    current_score: float = 0.0
    # Note: 'episode_id' and 'step_count' are already defined in the parent State class
