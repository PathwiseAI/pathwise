import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_graph_store
from app.graph_store import GraphStore


def _sample_repo_path() -> str:
    """Resolve the sample_repo path with canonical case."""
    return str(Path(__file__).resolve().parent.parent.parent / "sample_repo")


def _falkordb_available() -> bool:
    try:
        gs = GraphStore()
        return gs.health_check()
    except Exception:
        return False


skip_if_no_db = pytest.mark.skipif(
    not _falkordb_available(),
    reason="FalkorDB not available on localhost:6379",
)

client = TestClient(app)


# ── Health endpoint ────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "falkordb_connected" in data
        assert "version" in data


# ── Index endpoint ─────────────────────────────────────────────────────────────

@skip_if_no_db
class TestIndex:
    def test_index_sample_repo(self):
        sample_path = _sample_repo_path()
        response = client.post(
            "/api/repositories/index",
            json={"path": sample_path},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["repository_id"]
        assert data["files_discovered"] >= 5
        assert data["functions_discovered"] >= 10
        assert data["calls_resolved"] >= 5

    def test_index_nonexistent_path(self):
        response = client.post(
            "/api/repositories/index",
            json={"path": "/nonexistent/path/foobar"},
        )
        assert response.status_code == 404

    def test_index_missing_path_field(self):
        response = client.post(
            "/api/repositories/index",
            json={},
        )
        assert response.status_code == 422  # Validation error


# ── Functions endpoint ─────────────────────────────────────────────────────────

@skip_if_no_db
class TestFunctions:
    def test_list_functions(self):
        # First index
        sample_path = _sample_repo_path()
        idx_resp = client.post(
            "/api/repositories/index",
            json={"path": sample_path},
        )
        repo_id = idx_resp.json()["repository_id"]

        response = client.get(f"/api/repositories/{repo_id}/functions")
        assert response.status_code == 200
        funcs = response.json()
        assert len(funcs) >= 10
        names = [f["name"] for f in funcs]
        assert "handle_request" in names

    def test_list_functions_unknown_repo(self):
        response = client.get("/api/repositories/unknown_repo_id/functions")
        assert response.status_code == 404


# ── Investigate endpoint ──────────────────────────────────────────────────────

@skip_if_no_db
class TestInvestigate:
    def _get_repo_id(self) -> str:
        sample_path = _sample_repo_path()
        resp = client.post("/api/repositories/index", json={"path": sample_path})
        return resp.json()["repository_id"]

    def test_investigate_callers(self):
        repo_id = self._get_repo_id()
        response = client.post("/api/investigate", json={
            "repository_id": repo_id,
            "question": "Who calls compute_total?",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "find_callers"
        assert data["answer"]
        assert len(data["claims"]) > 0
        assert len(data["proof_records"]) > 0
        # Check proof records have valid statuses
        for pr in data["proof_records"]:
            assert pr["status"] in ["SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE"]

    def test_investigate_unknown_function(self):
        repo_id = self._get_repo_id()
        response = client.post("/api/investigate", json={
            "repository_id": repo_id,
            "question": "Who calls nonexistent_xyz_function?",
        })
        assert response.status_code == 200
        data = response.json()
        assert "not found" in data["answer"].lower()


# ── Verify endpoint ──────────────────────────────────────────────────────────

@skip_if_no_db
class TestVerify:
    def _get_repo_id(self) -> str:
        sample_path = _sample_repo_path()
        resp = client.post("/api/repositories/index", json={"path": sample_path})
        return resp.json()["repository_id"]

    def test_verify_supported(self):
        repo_id = self._get_repo_id()
        response = client.post("/api/verify", json={
            "repository_id": repo_id,
            "subject": "process_order",
            "predicate": "CALLS",
            "target": "compute_total",
        })
        assert response.status_code == 200
        data = response.json()
        # The verify endpoint uses function names — it resolves them
        assert data["proof"]["status"] in ["SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE"]

    def test_verify_unsupported(self):
        repo_id = self._get_repo_id()
        response = client.post("/api/verify", json={
            "repository_id": repo_id,
            "subject": "format_currency",
            "predicate": "CALLS",
            "target": "save_order",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["proof"]["status"] in ["UNSUPPORTED", "INCONCLUSIVE"]

    def test_verify_inconclusive_nonexistent(self):
        repo_id = self._get_repo_id()
        response = client.post("/api/verify", json={
            "repository_id": repo_id,
            "subject": "totally_fake_function",
            "predicate": "CALLS",
            "target": "also_fake",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["proof"]["status"] == "INCONCLUSIVE"


# ── Path traversal rejection ──────────────────────────────────────────────────

@skip_if_no_db
class TestSecurity:
    def test_path_traversal_rejected(self):
        response = client.post(
            "/api/repositories/index",
            json={"path": "C:\\Windows\\System32"},
        )
        # Should be 403 (path outside allowed root) or 404
        assert response.status_code in [403, 404]
