"""
tests/test_contract_generator.py — Unit tests for contract_generator.py.

Default run: tests the fallback path exhaustively (no credentials needed).
Live-LLM tests: gated behind skipif(not credentials_available()).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from contract_generator import (
    _build_prompt,
    _extract_keywords,
    fallback_contract,
    generate_contract,
)
from models.intent_contract import EvidenceStrategy, IntentContract, Requirement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_req(req_id: str, text: str) -> Requirement:
    return Requirement(id=req_id, raw_text=text)


R01 = make_req("R01", "Password reset tokens must expire after 15 minutes.")
R04 = make_req("R04", "Product prices must never be negative.")
R05 = make_req(
    "R05",
    "Admin endpoints must require an admin role; regular users must receive HTTP 403.",
)


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_returns_list(self):
        result = _extract_keywords("Password reset tokens must expire after 15 minutes.")
        assert isinstance(result, list)

    def test_removes_stopwords(self):
        kws = _extract_keywords("A user must not be able to place an order with empty cart.")
        stopwords = {"must", "able", "with", "that", "this"}
        for kw in kws:
            assert kw not in stopwords

    def test_removes_short_tokens(self):
        kws = _extract_keywords("A or the is it be do")
        for kw in kws:
            assert len(kw) >= 4

    def test_capped_at_eight(self):
        long_text = " ".join(f"keyword{i}" for i in range(20))
        assert len(_extract_keywords(long_text)) <= 8

    def test_deduplicates(self):
        kws = _extract_keywords("token token token reset reset")
        assert kws.count("token") == 1
        assert kws.count("reset") == 1

    def test_r01_keywords_contain_meaningful_tokens(self):
        kws = _extract_keywords(R01.raw_text)
        # Should include tokens like "password", "reset", "token", "expire", "minutes"
        combined = " ".join(kws)
        assert any(k in combined for k in ["password", "reset", "token", "expire"])

    def test_r04_keywords(self):
        kws = _extract_keywords(R04.raw_text)
        combined = " ".join(kws)
        assert any(k in combined for k in ["product", "price", "negative"])

    def test_empty_text_returns_empty(self):
        assert _extract_keywords("") == []

    def test_preserves_order(self):
        kws = _extract_keywords("expire reset token")
        # Order should match first appearance
        assert kws.index("expire") < kws.index("reset") < kws.index("token")


# ---------------------------------------------------------------------------
# fallback_contract
# ---------------------------------------------------------------------------

class TestFallbackContract:
    def test_returns_intent_contract(self):
        result = fallback_contract(R01)
        assert isinstance(result, IntentContract)

    def test_requirement_id_matches(self):
        result = fallback_contract(R01)
        assert result.requirement_id == "R01"

    def test_evidence_strategy_is_unknown(self):
        result = fallback_contract(R01)
        assert result.evidence_strategy == EvidenceStrategy.unknown

    def test_keywords_non_empty(self):
        result = fallback_contract(R01)
        assert len(result.keywords) > 0

    def test_acceptance_criteria_contains_raw_text(self):
        result = fallback_contract(R01)
        assert R01.raw_text in result.acceptance_criteria

    def test_summary_is_non_empty(self):
        result = fallback_contract(R01)
        assert result.summary.strip() != ""

    def test_long_summary_truncated(self):
        long_req = make_req(
            "R99",
            "A" * 200,
        )
        result = fallback_contract(long_req)
        assert len(result.summary) <= 62  # 60 chars + "…"

    def test_short_summary_not_truncated(self):
        short_req = make_req("R02", "Prices must not be negative.")
        result = fallback_contract(short_req)
        assert "…" not in result.summary

    def test_r04_fallback_keywords(self):
        result = fallback_contract(R04)
        combined = " ".join(result.keywords)
        assert any(k in combined for k in ["product", "price", "negative"])


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_contains_req_id(self):
        prompt = _build_prompt(R01)
        assert "R01" in prompt

    def test_contains_req_text(self):
        prompt = _build_prompt(R01)
        assert R01.raw_text in prompt

    def test_lists_required_fields(self):
        prompt = _build_prompt(R01)
        for field in ["summary", "acceptance_criteria", "evidence_strategy",
                      "keywords", "test_hint"]:
            assert field in prompt

    def test_instructs_json_only(self):
        prompt = _build_prompt(R01)
        assert "json" in prompt.lower() or "JSON" in prompt


# ---------------------------------------------------------------------------
# generate_contract — fallback path (no credentials)
# ---------------------------------------------------------------------------

class TestGenerateContractFallback:
    def test_returns_fallback_when_no_credentials(self, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        result = generate_contract(R01)
        assert isinstance(result, IntentContract)
        assert result.evidence_strategy == EvidenceStrategy.unknown

    def test_returns_fallback_when_client_raises(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.generate_json.side_effect = RuntimeError("API down")
        result = generate_contract(R01, client=mock_client)
        assert isinstance(result, IntentContract)
        assert result.evidence_strategy == EvidenceStrategy.unknown

    def test_returns_fallback_when_empty_json(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = {}
        result = generate_contract(R01, client=mock_client)
        assert result.evidence_strategy == EvidenceStrategy.unknown

    def test_returns_fallback_when_invalid_json_shape(self, monkeypatch):
        mock_client = MagicMock()
        # Missing required fields
        mock_client.generate_json.return_value = {"requirement_id": "R01"}
        result = generate_contract(R01, client=mock_client)
        # Missing "summary" → Pydantic error → fallback
        assert result.evidence_strategy == EvidenceStrategy.unknown

    def test_fallback_requirement_id_correct(self, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        result = generate_contract(R01)
        assert result.requirement_id == "R01"


# ---------------------------------------------------------------------------
# generate_contract — mock client returns valid JSON
# ---------------------------------------------------------------------------

class TestGenerateContractWithMockClient:
    def _valid_response(self, req_id: str) -> dict:
        return {
            "requirement_id": req_id,
            "summary": "Token TTL validation",
            "acceptance_criteria": ["token.expires_in == 900"],
            "evidence_strategy": "unit_test",
            "keywords": ["token", "reset", "expire", "password"],
            "test_hint": "assert token.expires_in == 900",
        }

    def test_valid_response_returns_intent_contract(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = self._valid_response("R01")
        result = generate_contract(R01, client=mock_client)
        assert isinstance(result, IntentContract)

    def test_requirement_id_normalised(self):
        mock_client = MagicMock()
        resp = self._valid_response("wrong_id")  # generator overwrites this
        mock_client.generate_json.return_value = resp
        result = generate_contract(R01, client=mock_client)
        assert result.requirement_id == "R01"

    def test_keywords_populated(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = self._valid_response("R01")
        result = generate_contract(R01, client=mock_client)
        assert len(result.keywords) > 0

    def test_empty_keywords_filled_from_raw_text(self):
        mock_client = MagicMock()
        resp = self._valid_response("R01")
        resp["keywords"] = []  # LLM returned empty keywords
        mock_client.generate_json.return_value = resp
        result = generate_contract(R01, client=mock_client)
        assert len(result.keywords) > 0

    def test_evidence_strategy_set(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = self._valid_response("R01")
        result = generate_contract(R01, client=mock_client)
        assert result.evidence_strategy == EvidenceStrategy.unit_test

    def test_acceptance_criteria_present(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = self._valid_response("R01")
        result = generate_contract(R01, client=mock_client)
        assert len(result.acceptance_criteria) > 0

    def test_prompt_sent_to_client(self):
        mock_client = MagicMock()
        mock_client.generate_json.return_value = self._valid_response("R01")
        generate_contract(R01, client=mock_client)
        mock_client.generate_json.assert_called_once()
        prompt_arg = mock_client.generate_json.call_args[0][0]
        assert "R01" in prompt_arg
        assert R01.raw_text in prompt_arg


# ---------------------------------------------------------------------------
# Live-LLM test (skipped unless credentials are configured)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not config.credentials_available(),
    reason="WATSONX_API_KEY / WATSONX_PROJECT_ID not set — skipping live LLM test",
)
def test_generate_contract_live_r01():
    """End-to-end: call real Granite and validate the returned contract."""
    result = generate_contract(R01)
    assert isinstance(result, IntentContract)
    assert result.requirement_id == "R01"
    assert len(result.keywords) > 0
    assert len(result.acceptance_criteria) > 0
    assert result.evidence_strategy != EvidenceStrategy.unknown
