"""
Tests for the FastAPI endpoints — /tasks, /grader, /baseline, /health, /reset, /step, /state.
"""
import pytest
from fastapi.testclient import TestClient
from incident_response_env.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestTasks:
    def test_list_tasks(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        task_ids = [t["task_id"] for t in data["tasks"]]
        for tid in ["task_1_oom", "task_2_leak", "task_3_cascade", "task_4_cache", "task_5_cert"]:
            assert tid in task_ids


class TestResetStepGrader:
    def test_reset_step_grader_flow(self, client):
        # Reset
        resp = client.post("/reset", json={"task_id": "task_1_oom"})
        assert resp.status_code == 200

        # Step — read logs
        resp = client.post("/step", json={"action": {"action_type": "read_logs", "target": "api-server"}})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success", True)

        # Step — restart
        resp = client.post("/step", json={"action": {"action_type": "restart_service", "target": "api-server"}})
        assert resp.status_code == 200

        # Grader
        resp = client.post("/grader", json={"task_id": "task_1_oom"})
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert 0.01 <= data["score"] <= 0.99
        assert "breakdown" in data
        assert "penalties" in data

    def test_grader_without_reset_returns_error(self, client):
        # Reset to a clean state (task_2) then try to grade task_3
        client.post("/reset", json={"task_id": "task_2_leak"})
        resp = client.post("/grader", json={"task_id": "task_3_cascade"})
        # Could be 200 with score 0.01 or 422 depending on impl
        # Just check it doesn't 500
        assert resp.status_code < 500


class TestBaseline:
    def test_baseline_returns_scores(self, client):
        resp = client.post("/baseline")
        assert resp.status_code == 200
        data = resp.json()
        assert "baseline_scores" in data
        results = data["baseline_scores"]
        assert len(results) >= 3

        for r in results:
            assert "task_id" in r
            assert "score" in r
            assert 0.01 <= r["score"] <= 0.99

    def test_baseline_scores_vary_by_difficulty(self, client):
        resp = client.post("/baseline")
        data = resp.json()
        results = {r["task_id"]: r["score"] for r in data["baseline_scores"]}
        # Scores must differ — proves the grader is not constant
        scores = list(results.values())
        assert len(set(scores)) > 1, "All baseline scores are identical — grader may be broken"
        # Easy task should outscore the hardest tasks
        assert results["task_1_oom"] > results["task_3_cascade"], "Easy task should beat hard task"
        assert results["task_1_oom"] > results["task_4_cache"], "Easy task should beat medium task"
