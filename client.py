from openenv.core import EnvClient
from openenv.core.client_types import StepResult

from .models import IncidentAction, IncidentObservation, IncidentState


class IncidentEnv(EnvClient[IncidentAction, IncidentObservation, IncidentState]):
    """
    Client for the Incident Response environment.

    Async usage (recommended):
        async with IncidentEnv(base_url="https://your-space.hf.space") as client:
            result = await client.reset()
            result = await client.step(IncidentAction(action_type="read_logs", target="api-server"))

    Sync usage:
        with IncidentEnv(base_url="...").sync() as client:
            result = client.reset()
    """

    def _step_payload(self, action: IncidentAction) -> dict:
        return {
            "action_type": action.action_type,
            "target":      action.target,
            "parameters":  action.parameters,
        }

    def _parse_result(self, payload: dict) -> StepResult[IncidentObservation]:
        obs = IncidentObservation(
            output=payload.get("output", ""),
            services=payload.get("services", {}),
            done=payload.get("done", False),
            success=payload.get("success", True),
            error=payload.get("error", ""),
        )
        return StepResult(
            observation=obs,
            reward=payload.get("reward"),
            done=obs.done,
        )

    def _parse_state(self, payload: dict) -> IncidentState:
        return IncidentState(
            episode_id=payload.get("episode_id", ""),
            task_id=payload.get("task_id", ""),
            step_count=payload.get("step_count", 0),
            actions_taken=payload.get("actions_taken", []),
            root_cause_identified=payload.get("root_cause_identified", False),
            fix_applied=payload.get("fix_applied", False),
            system_restored=payload.get("system_restored", False),
            current_score=payload.get("current_score", 0.0),
        )
