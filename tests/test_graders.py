"""
Tests for graders — verify scoring rubrics for all 5 tasks.
"""
import pytest
from incident_response_env.models import IncidentState
from incident_response_env.server.graders import (
    grade, grade_detailed,
    grade_task1, grade_task2, grade_task3, grade_task4, grade_task5,
    GRADER_MAP,
)


def _make_state(task_id: str, **kwargs) -> IncidentState:
    return IncidentState(
        task_id=task_id,
        episode_id="test-ep",
        actions_taken=kwargs.get("actions", []),
        root_cause_identified=kwargs.get("root_cause_identified", False),
        fix_applied=kwargs.get("fix_applied", False),
        system_restored=kwargs.get("system_restored", False),
    )


# ─── Task 1 ───

class TestTask1:
    def test_perfect_score(self):
        state = _make_state("task_1_oom", actions=[
            {"action_type": "read_logs", "target": "api-server"},
            {"action_type": "restart_service", "target": "api-server"},
        ], system_restored=True)
        score = grade_task1(state)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_no_actions(self):
        state = _make_state("task_1_oom")
        assert grade_task1(state) == 0.0

    def test_partial_read_logs_only(self):
        state = _make_state("task_1_oom", actions=[
            {"action_type": "read_logs", "target": "api-server"},
        ])
        score = grade_task1(state)
        assert 0.3 < score < 0.5  # investigation credit only


# ─── Task 2 ───

class TestTask2:
    def test_perfect_score(self):
        state = _make_state("task_2_leak", actions=[
            {"action_type": "check_metrics", "target": "worker"},
            {"action_type": "read_logs", "target": "worker"},
            {"action_type": "rollback", "target": "worker"},
        ], system_restored=True)
        score = grade_task2(state)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_restart_penalty(self):
        state = _make_state("task_2_leak", actions=[
            {"action_type": "check_metrics", "target": "worker"},
            {"action_type": "restart_service", "target": "api-server"},
            {"action_type": "rollback", "target": "worker"},
        ], system_restored=True)
        score = grade_task2(state)
        # Should have -0.15 penalty for wrong restart
        assert score < 0.9

    def test_no_actions(self):
        state = _make_state("task_2_leak")
        assert grade_task2(state) == 0.0


# ─── Task 3 ───

class TestTask3:
    def test_perfect_score(self):
        state = _make_state("task_3_cascade", actions=[
            {"action_type": "check_metrics", "target": "postgres"},
            {"action_type": "read_logs", "target": "postgres"},
            {"action_type": "exec_command", "target": "ALTER SYSTEM SET max_connections = 200"},
            {"action_type": "exec_command", "target": "SELECT pg_reload_conf()"},
        ], root_cause_identified=True, fix_applied=True, system_restored=True)
        score = grade_task3(state)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_blind_restart_penalty(self):
        state = _make_state("task_3_cascade", actions=[
            {"action_type": "restart_service", "target": "nginx"},
            {"action_type": "check_metrics", "target": "postgres", "_root_cause_found": True},
        ], root_cause_identified=True)
        score = grade_task3(state)
        # Has penalty for blind restart, but still gets investigation + root cause
        assert score > 0.0

    def test_disk_red_herring_penalty(self):
        state = _make_state("task_3_cascade", actions=[
            {"action_type": "exec_command", "target": "df -h"},
            {"action_type": "read_logs", "target": "postgres"},
        ], root_cause_identified=True)
        detail = grade_detailed(state)
        assert any(p["type"] == "red_herring_disk" for p in detail["penalties"])


# ─── Task 4 ───

class TestTask4:
    def test_perfect_score(self):
        state = _make_state("task_4_cache", actions=[
            {"action_type": "check_metrics", "target": "redis"},
            {"action_type": "read_logs", "target": "redis"},
            {"action_type": "exec_command", "target": "redis-cli FLUSHALL"},
        ], system_restored=True)
        score = grade_task4(state)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_restart_redis_penalty(self):
        state = _make_state("task_4_cache", actions=[
            {"action_type": "check_metrics", "target": "redis"},
            {"action_type": "restart_service", "target": "redis"},
            {"action_type": "exec_command", "target": "redis-cli FLUSHALL"},
        ], system_restored=True)
        score = grade_task4(state)
        assert score < 0.95  # -0.10 penalty

    def test_no_actions(self):
        state = _make_state("task_4_cache")
        assert grade_task4(state) == 0.0


# ─── Task 5 ───

class TestTask5:
    def test_perfect_score(self):
        state = _make_state("task_5_cert", actions=[
            {"action_type": "read_logs", "target": "nginx"},
            {"action_type": "exec_command", "target": "openssl s_client -connect api-server:8443"},
            {"action_type": "exec_command", "target": "certbot renew --force-renewal", "_root_cause_found": True},
            {"action_type": "restart_service", "target": "nginx", "_root_cause_found": True},
        ], system_restored=True)
        score = grade_task5(state)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_ddos_red_herring_penalty(self):
        state = _make_state("task_5_cert", actions=[
            {"action_type": "read_logs", "target": "nginx"},
            {"action_type": "exec_command", "target": "iptables -L"},
        ])
        detail = grade_detailed(state)
        assert any(p["type"] == "red_herring_ddos" for p in detail["penalties"])

    def test_no_actions(self):
        state = _make_state("task_5_cert")
        assert grade_task5(state) == 0.0


# ─── Dispatch & Clamping ───

class TestGradeDispatch:
    def test_all_tasks_registered(self):
        expected = {"task_1_oom", "task_2_leak", "task_3_cascade", "task_4_cache", "task_5_cert"}
        assert set(GRADER_MAP.keys()) == expected

    def test_unknown_task_raises(self):
        state = _make_state("task_99_bogus")
        with pytest.raises(ValueError, match="Unknown task_id"):
            grade(state)

    def test_clamping_zero_to_0_01(self):
        state = _make_state("task_1_oom")  # no actions → raw = 0.0
        assert grade(state) == 0.01

    def test_clamping_perfect_to_0_99(self):
        state = _make_state("task_1_oom", actions=[
            {"action_type": "read_logs", "target": "api-server"},
            {"action_type": "restart_service", "target": "api-server"},
        ], system_restored=True)
        assert grade(state) == 0.99


class TestGradeDetailed:
    def test_returns_breakdown_and_penalties(self):
        state = _make_state("task_1_oom", actions=[
            {"action_type": "read_logs", "target": "api-server"},
        ])
        result = grade_detailed(state)
        assert "score" in result
        assert "raw_score" in result
        assert "breakdown" in result
        assert "penalties" in result
        assert 0.01 <= result["score"] <= 0.99

    def test_all_tasks_have_detailed(self):
        for task_id in GRADER_MAP:
            state = _make_state(task_id)
            result = grade_detailed(state)
            assert isinstance(result["breakdown"], dict)
            assert isinstance(result["penalties"], list)
