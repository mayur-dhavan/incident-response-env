"""
Tests for the environment — reset, step, and per-task behavior.
"""
import pytest
from incident_response_env.server.environment import IncidentEnvironment
from incident_response_env.models import IncidentAction


@pytest.fixture
def env():
    return IncidentEnvironment()


# ─── Reset ───

class TestReset:
    def test_reset_all_tasks(self, env):
        for task_id in ["task_1_oom", "task_2_leak", "task_3_cascade", "task_4_cache", "task_5_cert"]:
            obs = env.reset(task_id=task_id)
            state = env._state
            assert state.task_id == task_id
            assert state.step_count == 0
            assert obs.output != ""
            assert not state.system_restored
            assert not state.fix_applied

    def test_unknown_task_raises(self, env):
        with pytest.raises(ValueError, match="Unknown task_id"):
            env.reset(task_id="task_99_nope")

    def test_reset_clears_previous_state(self, env):
        env.reset(task_id="task_1_oom")
        env.step(IncidentAction(action_type="read_logs", target="api-server"))
        env.reset(task_id="task_2_leak")
        state = env._state
        assert state.task_id == "task_2_leak"
        assert state.step_count == 0
        assert len(state.actions_taken) == 0


# ─── Task 1 sanity (known-good from Phase 2) ───

class TestTask1Step:
    def test_read_logs_and_restart(self, env):
        env.reset(task_id="task_1_oom")
        obs = env.step(IncidentAction(action_type="read_logs", target="api-server"))
        assert obs.success
        assert "oom" in obs.output.lower() or "killed" in obs.output.lower() or "OOM" in obs.output

        obs = env.step(IncidentAction(action_type="restart_service", target="api-server"))
        assert obs.success
        assert env._state.system_restored


# ─── Task 2 sanity ───

class TestTask2Step:
    def test_rollback_fixes(self, env):
        env.reset(task_id="task_2_leak")
        env.step(IncidentAction(action_type="check_metrics", target="worker"))
        env.step(IncidentAction(action_type="read_logs", target="worker"))
        obs = env.step(IncidentAction(action_type="rollback", target="worker"))
        assert obs.success
        assert env._state.system_restored

    def test_restart_does_not_fix(self, env):
        env.reset(task_id="task_2_leak")
        obs = env.step(IncidentAction(action_type="restart_service", target="worker"))
        assert obs.success
        assert not env._state.system_restored


# ─── Task 3 sanity ───

class TestTask3Step:
    def test_full_fix(self, env):
        env.reset(task_id="task_3_cascade")
        env.step(IncidentAction(action_type="check_metrics", target="postgres"))
        env.step(IncidentAction(action_type="read_logs", target="postgres"))
        env.step(IncidentAction(action_type="exec_command", target="ALTER SYSTEM SET max_connections = 200"))
        obs = env.step(IncidentAction(action_type="exec_command", target="SELECT pg_reload_conf()"))
        assert env._state.system_restored


# ─── Task 4 ───

class TestTask4Step:
    def test_flushall_fixes(self, env):
        env.reset(task_id="task_4_cache")
        env.step(IncidentAction(action_type="check_metrics", target="redis"))
        env.step(IncidentAction(action_type="read_logs", target="api-server"))
        obs = env.step(IncidentAction(action_type="exec_command", target="redis-cli FLUSHALL"))
        assert obs.success
        assert env._state.system_restored

    def test_restart_redis_does_not_fix(self, env):
        env.reset(task_id="task_4_cache")
        obs = env.step(IncidentAction(action_type="restart_service", target="redis"))
        assert obs.success
        assert not env._state.system_restored

    def test_restart_api_server_does_not_fix(self, env):
        env.reset(task_id="task_4_cache")
        obs = env.step(IncidentAction(action_type="restart_service", target="api-server"))
        assert obs.success
        assert not env._state.system_restored


# ─── Task 5 ───

class TestTask5Step:
    def test_certbot_renew_then_nginx_restart(self, env):
        env.reset(task_id="task_5_cert")
        env.step(IncidentAction(action_type="read_logs", target="nginx"))
        env.step(IncidentAction(action_type="exec_command", target="openssl s_client -connect api-server:8443"))
        env.step(IncidentAction(action_type="exec_command", target="certbot renew --force-renewal"))
        obs = env.step(IncidentAction(action_type="restart_service", target="nginx"))
        assert env._state.system_restored

    def test_nginx_restart_without_renew_fails(self, env):
        env.reset(task_id="task_5_cert")
        obs = env.step(IncidentAction(action_type="restart_service", target="nginx"))
        assert not env._state.system_restored

    def test_api_server_restart_does_not_fix(self, env):
        env.reset(task_id="task_5_cert")
        obs = env.step(IncidentAction(action_type="restart_service", target="api-server"))
        assert not env._state.system_restored


# ─── Episode terminates at max_steps ───

class TestMaxSteps:
    def test_episode_done_at_max_steps(self, env):
        env.reset(task_id="task_1_oom")
        max_steps = env._scenario.get("max_steps", 15)
        for _ in range(max_steps + 2):
            obs = env.step(IncidentAction(action_type="read_logs", target="api-server"))
        assert obs.done
