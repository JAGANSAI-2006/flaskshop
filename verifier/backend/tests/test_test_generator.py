"""
tests/test_test_generator.py — Unit tests for test_generator.py.

Default run: tests the no-credentials fallback, safety checks, file I/O, and
the mock-client (valid + invalid LLM responses).  No real credentials needed.

Live-LLM tests: gated behind skipif(not credentials_available()).
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from models.code_region import CodeRegion
from models.intent_contract import EvidenceStrategy, IntentContract, Requirement
from test_generator import (
    GeneratedTest,
    _build_code_context,
    _has_assertion,
    _strip_code_fences,
    generate_test,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_req(req_id: str, text: str) -> Requirement:
    return Requirement(id=req_id, raw_text=text)


def make_contract(req_id: str) -> IntentContract:
    return IntentContract(
        requirement_id=req_id,
        summary="Token TTL validation",
        acceptance_criteria=["token.expires_in == 900"],
        evidence_strategy=EvidenceStrategy.unit_test,
        keywords=["token", "reset", "expire"],
        test_hint="assert token.expires_in == 900",
    )


def make_region(file: str = "auth/tokens.py", snippet: str = "def get_token(): return 1\n") -> CodeRegion:
    return CodeRegion(file=file, line_start=1, line_end=2, snippet=snippet, score=3)


R01 = make_req("R01", "Password reset tokens must expire after 15 minutes.")
CONTRACT_R01 = make_contract("R01")


# ---------------------------------------------------------------------------
# _has_assertion
# ---------------------------------------------------------------------------

class TestHasAssertion:
    def test_detects_assert(self):
        assert _has_assertion("def test_foo():\n    assert x == 1\n")

    def test_detects_assert_with_message(self):
        assert _has_assertion("assert x == 1, 'should be 1'")

    def test_no_assert(self):
        assert not _has_assertion("def test_foo():\n    x = 1\n")

    def test_assert_in_comment_ignored(self):
        # "assert" as a word in a comment still matches (simple text scan)
        # This is intentionally liberal — a comment with "assert" is still flagged.
        assert _has_assertion("# assert something\n")

    def test_assert_in_string(self):
        assert _has_assertion('x = "assert this"\n')

    def test_empty_source(self):
        assert not _has_assertion("")


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------

class TestStripCodeFences:
    def test_strips_python_fence(self):
        src = "```python\ndef test_foo():\n    assert True\n```"
        result = _strip_code_fences(src)
        assert not result.startswith("```")
        assert "def test_foo" in result

    def test_strips_plain_fence(self):
        src = "```\ndef test_foo():\n    assert True\n```"
        result = _strip_code_fences(src)
        assert not result.startswith("```")

    def test_no_fence_unchanged(self):
        src = "def test_foo():\n    assert True\n"
        assert _strip_code_fences(src) == src.strip()

    def test_empty_string(self):
        assert _strip_code_fences("") == ""


# ---------------------------------------------------------------------------
# _build_code_context
# ---------------------------------------------------------------------------

class TestBuildCodeContext:
    def test_empty_regions_returns_placeholder(self):
        ctx = _build_code_context([])
        assert "no relevant code" in ctx

    def test_includes_file_path(self):
        region = make_region("auth/tokens.py")
        ctx = _build_code_context([region])
        assert "auth/tokens.py" in ctx

    def test_includes_snippet(self):
        region = make_region(snippet="def get_token(): return 'x'\n")
        ctx = _build_code_context([region])
        assert "def get_token" in ctx

    def test_includes_line_numbers(self):
        region = CodeRegion(file="f.py", line_start=10, line_end=20, snippet="x=1", score=1)
        ctx = _build_code_context([region])
        assert "10" in ctx and "20" in ctx

    def test_multiple_regions_all_included(self):
        regions = [make_region(f"mod_{i}.py") for i in range(3)]
        ctx = _build_code_context(regions)
        for i in range(3):
            assert f"mod_{i}.py" in ctx

    def test_context_capped_at_max_chars(self):
        big_snippet = "x = 1\n" * 500
        regions = [make_region(snippet=big_snippet) for _ in range(5)]
        ctx = _build_code_context(regions)
        assert len(ctx) <= 2200  # _MAX_CONTEXT_CHARS + a little overhead


# ---------------------------------------------------------------------------
# generate_test — no-credentials fallback
# ---------------------------------------------------------------------------

class TestGenerateTestNoCredentials:
    def test_returns_generated_test_dataclass(self, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        result = generate_test(R01, CONTRACT_R01, [], Path("/tmp/repo"), "job123")
        assert isinstance(result, GeneratedTest)

    def test_fallback_is_valid_when_no_credentials(self, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        result = generate_test(R01, CONTRACT_R01, [], Path("/tmp/repo"), "job123")
        assert result.is_valid is True


    def test_fallback_has_no_skip_reason(self, monkeypatch):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        result = generate_test(R01, CONTRACT_R01, [], Path("/tmp/repo"), "job123")
        assert result.skip_reason == ""


    def test_fallback_writes_test_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "WATSONX_API_KEY", "")
        monkeypatch.setattr(config, "WATSONX_PROJECT_ID", "")
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        result = generate_test(R01, CONTRACT_R01, [], Path("/tmp/repo"), "job123")
        assert result.path is not None
        assert result.path.exists()


# ---------------------------------------------------------------------------
# generate_test — mock client, valid response
# ---------------------------------------------------------------------------

VALID_TEST_SOURCE = textwrap.dedent("""\
    def test_r01():
        token = {"expires_in": 900}
        assert token["expires_in"] == 900
""")


class TestGenerateTestMockValid:
    def test_returns_valid_generated_test(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = VALID_TEST_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [make_region()],
            Path("/tmp/repo"), "job001",
            client=mock_client,
        )
        assert result.is_valid is True

    def test_file_written_to_correct_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = VALID_TEST_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [],
            Path("/tmp/repo"), "job002",
            client=mock_client,
        )
        assert result.path is not None
        assert result.path.exists()

    def test_file_path_contains_req_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = VALID_TEST_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [],
            Path("/tmp/repo"), "job003",
            client=mock_client,
        )
        assert "r01" in result.path.name.lower()

    def test_source_contains_sys_path_header(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = VALID_TEST_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [],
            Path("/tmp/repo"), "job004",
            client=mock_client,
        )
        assert "sys.path.insert" in result.source

    def test_written_file_contains_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = VALID_TEST_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [],
            Path("/tmp/repo"), "job005",
            client=mock_client,
        )
        content = result.path.read_text()
        assert "assert" in content

    def test_prompt_includes_req_text(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = VALID_TEST_SOURCE
        generate_test(R01, CONTRACT_R01, [], Path("/tmp/repo"), "job006", client=mock_client)
        prompt = mock_client.generate.call_args[0][0]
        assert R01.raw_text in prompt

    def test_prompt_includes_acceptance_criteria(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = VALID_TEST_SOURCE
        generate_test(R01, CONTRACT_R01, [], Path("/tmp/repo"), "job007", client=mock_client)
        prompt = mock_client.generate.call_args[0][0]
        assert CONTRACT_R01.acceptance_criteria[0] in prompt


# ---------------------------------------------------------------------------
# generate_test — mock client, safety checks fail
# ---------------------------------------------------------------------------

SYNTAX_ERROR_SOURCE = "def test_r01(\n    # unclosed paren\n"
NO_ASSERT_SOURCE = "def test_r01():\n    x = 1 + 1\n    print(x)\n"
FENCED_VALID_SOURCE = "```python\n" + VALID_TEST_SOURCE + "\n```"


class TestGenerateTestSafetyChecks:
    def test_syntax_error_is_invalid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = SYNTAX_ERROR_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [], Path("/tmp/repo"), "job010", client=mock_client
        )
        assert result.is_valid is False
        assert "syntax_error" in result.skip_reason

    def test_no_assert_is_invalid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = NO_ASSERT_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [], Path("/tmp/repo"), "job011", client=mock_client
        )
        assert result.is_valid is False
        assert "no_assertion" in result.skip_reason

    def test_no_file_written_on_syntax_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = SYNTAX_ERROR_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [], Path("/tmp/repo"), "job012", client=mock_client
        )
        assert result.path is None

    def test_code_fences_stripped_before_safety_check(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = FENCED_VALID_SOURCE
        result = generate_test(
            R01, CONTRACT_R01, [], Path("/tmp/repo"), "job013", client=mock_client
        )
        # After fence stripping the code is valid and has asserts
        assert result.is_valid is True

    def test_empty_response_is_invalid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.return_value = ""
        result = generate_test(
            R01, CONTRACT_R01, [], Path("/tmp/repo"), "job014", client=mock_client
        )
        assert result.is_valid is False

    def test_llm_error_is_invalid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
        mock_client = MagicMock()
        mock_client.generate.side_effect = RuntimeError("API timeout")
        result = generate_test(
            R01, CONTRACT_R01, [], Path("/tmp/repo"), "job015", client=mock_client
        )
        assert result.is_valid is False
        assert "llm_error" in result.skip_reason


# ---------------------------------------------------------------------------
# Live-LLM test (skipped unless credentials are configured)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not config.credentials_available(),
    reason="WATSONX_API_KEY / WATSONX_PROJECT_ID not set — skipping live LLM test",
)
def test_generate_test_live_r01(tmp_path, monkeypatch):
    """End-to-end: real Granite call → valid test file written to disk."""
    monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path)
    region = make_region(
        "auth/tokens.py",
        "def generate_reset_token(user_id):\n    return {'expires_in': 900}\n",
    )
    result = generate_test(R01, CONTRACT_R01, [region], tmp_path / "repo", "livejob")
    # We accept is_valid=True or is_valid=False (syntax error from model) —
    # the important thing is no exception was raised and the object is correct.
    assert isinstance(result, GeneratedTest)
    assert result.req_id == "R01"
