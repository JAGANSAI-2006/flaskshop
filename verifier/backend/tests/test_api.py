"""
tests/test_api.py — FastAPI endpoint tests for main.py.

Uses fastapi.testclient.TestClient (synchronous, no running server required).
All Git, file-system, and LLM calls are patched — no real network I/O.

Endpoints covered:
  GET  /health
  POST /ingest
  POST /verify
  GET  /report/{job_id}
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the FastAPI app and the job-store so we can reset it between tests.
import main as _main
from fastapi.testclient import TestClient
from models.intent_contract import (
    EvidenceStrategy,
    IntentContract,
    Requirement,
    RequirementResult,
)

client = TestClient(_main.app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(req_id: str, verdict: str) -> RequirementResult:
    """Build a minimal RequirementResult for a given verdict."""
    contract = IntentContract(
        requirement_id=req_id,
        summary="stub",
        acceptance_criteria=["stub"],
        evidence_strategy=EvidenceStrategy.unit_test,
        keywords=["stub"],
    )
    return RequirementResult(
        id=req_id,
        raw=f"Requirement {req_id}",
        contract=contract,
        generated_test="def test_stub(): pass",
        execution_output="1 passed",
        verdict=verdict,
        evidence_summary=f"verdict={verdict}",
    )


def _clear_job_store():
    """Empty the in-memory job store before each test that uses /verify or /report."""
    _main._job_store.clear()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_200(self):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_status_ok(self):
        resp = client.get("/health")
        assert resp.json()["status"] == "ok"

    def test_has_pipeline_ready_field(self):
        resp = client.get("/health")
        assert "pipeline_ready" in resp.json()

    def test_pipeline_ready_is_bool(self):
        resp = client.get("/health")
        assert isinstance(resp.json()["pipeline_ready"], bool)

    def test_has_model_field(self):
        resp = client.get("/health")
        assert "model" in resp.json()

    def test_has_watsonx_credentials_configured(self):
        resp = client.get("/health")
        assert "watsonx_credentials_configured" in resp.json()

    def test_no_credentials_still_200(self, monkeypatch):
        """Health endpoint must never require credentials."""
        import config
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET / (redirect)
# ---------------------------------------------------------------------------

class TestRootRedirect:
    def test_root_redirects(self):
        # follow_redirects=False so we can inspect the 307
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (301, 302, 307, 308)
        assert "/health" in resp.headers["location"]


# ---------------------------------------------------------------------------
# POST /verify — validation errors
# ---------------------------------------------------------------------------

class TestVerifyValidation:
    def test_missing_repo_url_is_422(self):
        resp = client.post("/verify", json={"requirements": ["R01: must login"]})
        assert resp.status_code == 422

    def test_missing_requirements_is_422(self):
        resp = client.post("/verify", json={"repo_url": "https://github.com/x/y"})
        assert resp.status_code == 422

    def test_bad_url_scheme_is_422(self):
        resp = client.post(
            "/verify",
            json={"repo_url": "ftp://example.com/repo", "requirements": ["R01: must work"]},
        )
        assert resp.status_code == 422

    def test_empty_requirements_list_is_422(self):
        resp = client.post(
            "/verify",
            json={"repo_url": "https://github.com/x/y", "requirements": []},
        )
        assert resp.status_code == 422

    def test_blank_string_requirements_is_422(self):
        resp = client.post(
            "/verify",
            json={"repo_url": "https://github.com/x/y", "requirements": ["   ", ""]},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /verify — success (mocked pipeline)
# ---------------------------------------------------------------------------

_MOCK_REPO_URL = "https://github.com/example/flaskshop"
_MOCK_REPO_PATH = Path("/tmp/mock_repo")
_MOCK_FILE_INDEX: Dict[str, Any] = {"app.py": ["create_app"], "auth/tokens.py": ["generate_reset_token"]}


def _patch_verify(**kwargs):
    """
    Context-manager helper: patches clone_repo, build_file_index, and
    verify_requirement all at once.

    kwargs:
      results  – list of RequirementResult objects to return (one per call)
    """
    results = kwargs.get("results", [])
    result_iter = iter(results)

    return (
        patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH),
        patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX),
        patch("main.verify_requirement", side_effect=lambda *a, **kw: next(result_iter)),
    )


class TestVerifySuccess:
    def setup_method(self):
        _clear_job_store()

    def test_single_proven_returns_200(self):
        results = [_make_result("R01", "PROVEN")]
        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=results[0]):
            resp = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["Token must expire"]},
            )
        assert resp.status_code == 200

    def test_response_has_job_id(self):
        result = _make_result("R01", "PROVEN")
        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=result):
            resp = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["Token must expire"]},
            )
        assert "job_id" in resp.json()
        assert resp.json()["job_id"]  # non-empty

    def test_response_has_results_list(self):
        result = _make_result("R01", "PROVEN")
        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=result):
            resp = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["Token must expire"]},
            )
        assert isinstance(resp.json()["results"], list)
        assert len(resp.json()["results"]) == 1

    def test_summary_counts_proven(self):
        result = _make_result("R01", "PROVEN")
        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=result):
            resp = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["Token must expire"]},
            )
        summary = resp.json()["summary"]
        assert summary["proven"] == 1
        assert summary["failed"] == 0
        assert summary["unproven"] == 0
        assert summary["total"] == 1

    def test_multiple_requirements_all_verdicts(self):
        """Three requirements → one of each verdict."""
        r1 = _make_result("R01", "PROVEN")
        r2 = _make_result("R02", "FAILED")
        r3 = _make_result("R03", "UNPROVEN")
        side_effects = [r1, r2, r3]

        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", side_effect=side_effects):
            resp = client.post(
                "/verify",
                json={
                    "repo_url": _MOCK_REPO_URL,
                    "requirements": ["R1 text", "R2 text", "R3 text"],
                },
            )
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["proven"] == 1
        assert summary["failed"] == 1
        assert summary["unproven"] == 1
        assert summary["total"] == 3

    def test_clone_error_returns_400(self):
        with patch("main.repo_ingestor.clone_repo", side_effect=RuntimeError("git not found")):
            resp = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["R1: must work"]},
            )
        assert resp.status_code == 400

    def test_result_stored_in_job_store(self):
        result = _make_result("R01", "PROVEN")
        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=result):
            resp = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["Token must expire"]},
            )
        job_id = resp.json()["job_id"]
        assert job_id in _main._job_store

    def test_git_at_url_accepted(self):
        """git@ URLs should pass validation."""
        result = _make_result("R01", "PROVEN")
        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=result):
            resp = client.post(
                "/verify",
                json={"repo_url": "git@github.com:example/repo.git", "requirements": ["R1 text"]},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /report/{job_id}
# ---------------------------------------------------------------------------

class TestReportEndpoint:
    def setup_method(self):
        _clear_job_store()

    def test_unknown_job_id_returns_404(self):
        resp = client.get("/report/nonexistent-job-id-12345")
        assert resp.status_code == 404

    def test_known_job_id_returns_200(self):
        result = _make_result("R01", "PROVEN")
        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=result):
            post_resp = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["Token must expire"]},
            )
        job_id = post_resp.json()["job_id"]
        get_resp = client.get(f"/report/{job_id}")
        assert get_resp.status_code == 200

    def test_report_content_matches_verify_response(self):
        result = _make_result("R01", "PROVEN")
        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=result):
            post_resp = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["Token must expire"]},
            )
        job_id = post_resp.json()["job_id"]
        get_resp = client.get(f"/report/{job_id}")
        assert get_resp.json()["job_id"] == job_id
        assert get_resp.json()["summary"]["proven"] == 1

    def test_report_404_detail_contains_job_id(self):
        bad_id = "bad-job-xyz"
        resp = client.get(f"/report/{bad_id}")
        assert bad_id in resp.json()["detail"]

    def test_two_separate_jobs_stored_independently(self):
        r1 = _make_result("R01", "PROVEN")
        r2 = _make_result("R02", "FAILED")

        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=r1):
            resp1 = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["R1 text"]},
            )

        with patch("main.repo_ingestor.clone_repo", return_value=_MOCK_REPO_PATH), \
             patch("main.repo_ingestor.build_file_index", return_value=_MOCK_FILE_INDEX), \
             patch("main.verify_requirement", return_value=r2):
            resp2 = client.post(
                "/verify",
                json={"repo_url": _MOCK_REPO_URL, "requirements": ["R2 text"]},
            )

        jid1, jid2 = resp1.json()["job_id"], resp2.json()["job_id"]
        assert jid1 != jid2
        assert client.get(f"/report/{jid1}").json()["summary"]["proven"] == 1
        assert client.get(f"/report/{jid2}").json()["summary"]["failed"] == 1
