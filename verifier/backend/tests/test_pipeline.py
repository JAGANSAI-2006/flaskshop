"""
tests/test_pipeline.py — Integration tests for pipeline.verify_requirement().

Uses real tiny Python repos in tmp_path and mock LLM clients.
No network, no credentials required for default tests.
Live-LLM test gated behind credentials check.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from models.intent_contract import (
    EvidenceStrategy, IntentContract, Requirement, RequirementResult
)
from pipeline import verify_requirement
from verdict_classifier import VERDICT_FAILED, VERDICT_PROVEN, VERDICT_UNPROVEN


# ---------------------------------------------------------------------------
# Helpers — build a minimal repo that tests can run against
# ---------------------------------------------------------------------------

def _build_repo(tmp_path: Path) -> tuple[Path, dict]:
    """
    Create a minimal Python repo and return (repo_path, file_index).

    tokens.py has generate_reset_token() that returns expires_in=900.
    products/routes.py has create_product() that accepts negative prices (bug).
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth").mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth" / "__init__.py").write_text("")
    (tmp_path / "auth" / "tokens.py").write_text(textwrap.dedent("""\
        EXPIRY = 900

        def generate_reset_token(user_id):
            return {"user_id": user_id, "expires_in": EXPIRY}
    """))

    (tmp_path / "products").mkdir(parents=True, exist_ok=True)
    (tmp_path / "products" / "__init__.py").write_text("")
    (tmp_path / "products" / "routes.py").write_text(textwrap.dedent("""\
        _products = []

        def create_product(name, price):
            # BUG: no price validation
            _products.append({"name": name, "price": price})
            return {"name": name, "price": price}
    """))

    file_index = {
        "auth/tokens.py": ["generate_reset_token"],
        "products/routes.py": ["create_product"],
        "auth/__init__.py": [],
        "products/__init__.py": [],
    }
    return tmp_path, file_index


def _make_req(req_id: str, text: str) -> Requirement:
    return Requirement(id=req_id, raw_text=text)


def _make_contract(req_id: str, strategy: EvidenceStrategy = EvidenceStrategy.unit_test) -> IntentContract:
    return IntentContract(
        requirement_id=req_id,
        summary="stub",
        acceptance_criteria=["stub criterion"],
        evidence_strategy=strategy,
        keywords=["token", "reset", "expire"],
        test_hint="assert token['expires_in'] == 900",
    )


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_requirement_result(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job001", index)
        assert isinstance(result, RequirementResult)

    def test_id_matches_requirement(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job002", index)
        assert result.id == "R01"

    def test_raw_text_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job003", index)
        assert result.raw == req.raw_text

    def test_verdict_is_valid_string(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job004", index)
        assert result.verdict in (VERDICT_PROVEN, VERDICT_FAILED, VERDICT_UNPROVEN)


# ---------------------------------------------------------------------------
# No credentials → graceful UNPROVEN
# ---------------------------------------------------------------------------

class TestNoCredentials:
    def test_no_creds_returns_unproven(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job010", index)
        assert result.verdict == VERDICT_UNPROVEN

    def test_no_creds_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire after 15 minutes.")
        # Must complete without raising
        result = verify_requirement(req, repo, "job011", index)
        assert result is not None

    def test_no_creds_evidence_summary_set(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job012", index)
        assert result.evidence_summary != ""

    def test_no_creds_contract_is_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job013", index)
        assert result.contract is not None
        assert result.contract.evidence_strategy == EvidenceStrategy.unknown


# ---------------------------------------------------------------------------
# Mock client — passing pipeline
# ---------------------------------------------------------------------------

PASSING_TEST_BODY = textwrap.dedent("""\
    def test_r01():
        from auth.tokens import generate_reset_token
        token = generate_reset_token(1)
        assert token["expires_in"] == 900
""")


class TestPassingPipeline:
    def _make_mock_client(self, req_id: str = "R01") -> MagicMock:
        client = MagicMock()
        # generate_json → valid contract
        client.generate_json.return_value = {
            "requirement_id": req_id,
            "summary": "Token TTL",
            "acceptance_criteria": ["token.expires_in == 900"],
            "evidence_strategy": "unit_test",
            "keywords": ["token", "reset", "expire"],
            "test_hint": "assert token['expires_in'] == 900",
        }
        # generate → valid test body
        client.generate.return_value = PASSING_TEST_BODY
        return client

    def test_passing_pipeline_proven(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "temp")
        repo, index = _build_repo(tmp_path / "repo")
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job020", index,
                                    client=self._make_mock_client())
        assert result.verdict == VERDICT_PROVEN

    def test_passing_pipeline_contract_populated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "temp")
        repo, index = _build_repo(tmp_path / "repo")
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job021", index,
                                    client=self._make_mock_client())
        assert result.contract is not None
        assert result.contract.requirement_id == "R01"

    def test_passing_pipeline_traced_code_populated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "temp")
        repo, index = _build_repo(tmp_path / "repo")
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job022", index,
                                    client=self._make_mock_client())
        assert len(result.traced_code) > 0

    def test_passing_pipeline_generated_test_non_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "temp")
        repo, index = _build_repo(tmp_path / "repo")
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job023", index,
                                    client=self._make_mock_client())
        assert result.generated_test != ""

    def test_passing_pipeline_evidence_summary_non_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "temp")
        repo, index = _build_repo(tmp_path / "repo")
        req = _make_req("R01", "Token must expire after 15 minutes.")
        result = verify_requirement(req, repo, "job024", index,
                                    client=self._make_mock_client())
        assert result.evidence_summary != ""


# ---------------------------------------------------------------------------
# Mock client — failing pipeline (seeded bug)
# ---------------------------------------------------------------------------

FAILING_TEST_BODY = textwrap.dedent("""\
    def test_r04():
        from products.routes import create_product
        result = create_product("widget", -1)
        assert result["price"] >= 0, f"Expected non-negative price, got {result['price']}"
""")


class TestFailingPipeline:
    def _make_mock_client(self) -> MagicMock:
        client = MagicMock()
        client.generate_json.return_value = {
            "requirement_id": "R04",
            "summary": "Price validation",
            "acceptance_criteria": ["price >= 0"],
            "evidence_strategy": "unit_test",
            "keywords": ["price", "negative", "product"],
            "test_hint": "assert price >= 0",
        }
        client.generate.return_value = FAILING_TEST_BODY
        return client

    def test_failing_pipeline_verdict_failed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "temp")
        repo, index = _build_repo(tmp_path / "repo")
        req = _make_req("R04", "Product prices must never be negative.")
        result = verify_requirement(req, repo, "job030", index,
                                    client=self._make_mock_client())
        assert result.verdict == VERDICT_FAILED

    def test_failing_pipeline_execution_output_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "temp")
        repo, index = _build_repo(tmp_path / "repo")
        req = _make_req("R04", "Product prices must never be negative.")
        result = verify_requirement(req, repo, "job031", index,
                                    client=self._make_mock_client())
        assert result.execution_output != ""


# ---------------------------------------------------------------------------
# Stage-level exception resilience
# ---------------------------------------------------------------------------

class TestStageResilience:
    def test_contract_stage_exception_yields_unproven(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire.")

        with patch("pipeline.generate_contract", side_effect=RuntimeError("boom")):
            result = verify_requirement(req, repo, "job040", index)
        assert result.verdict == VERDICT_UNPROVEN
        assert "contract_error" in result.error

    def test_trace_stage_exception_yields_unproven(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire.")

        with patch("pipeline.trace", side_effect=RuntimeError("trace boom")):
            result = verify_requirement(req, repo, "job041", index)
        assert result.verdict == VERDICT_UNPROVEN

    def test_executor_exception_yields_unproven(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire.")

        with patch("pipeline.execute_test", side_effect=RuntimeError("exec boom")):
            result = verify_requirement(req, repo, "job042", index)
        assert result.verdict == VERDICT_UNPROVEN
        assert "executor_error" in result.error

    def test_pipeline_never_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        repo, index = _build_repo(tmp_path)
        req = _make_req("R01", "Token must expire.")

        # Blow up every stage
        with patch("pipeline.generate_contract", side_effect=Exception("contract boom")), \
             patch("pipeline.trace", side_effect=Exception("trace boom")), \
             patch("pipeline.generate_test", side_effect=Exception("gen boom")), \
             patch("pipeline.execute_test", side_effect=Exception("exec boom")):
            result = verify_requirement(req, repo, "job043", index)

        # Must not raise; must return a valid RequirementResult
        assert isinstance(result, RequirementResult)
        assert result.verdict == VERDICT_UNPROVEN

    def test_invalid_generated_test_yields_unproven(self, tmp_path, monkeypatch):
        """When the LLM produces a syntactically invalid test, verdict is UNPROVEN."""
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "temp")
        repo, index = _build_repo(tmp_path / "repo")
        req = _make_req("R01", "Token must expire after 15 minutes.")

        client = MagicMock()
        client.generate_json.return_value = {
            "requirement_id": "R01",
            "summary": "Token TTL",
            "acceptance_criteria": ["token.expires_in == 900"],
            "evidence_strategy": "unit_test",
            "keywords": ["token"],
            "test_hint": "",
        }
        # Deliberately broken Python
        client.generate.return_value = "def test_r01(\n    # unclosed paren\n"

        result = verify_requirement(req, repo, "job044", index, client=client)
        assert result.verdict == VERDICT_UNPROVEN
