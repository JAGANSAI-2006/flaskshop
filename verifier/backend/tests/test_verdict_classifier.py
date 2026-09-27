"""
tests/test_verdict_classifier.py — Unit tests for verdict_classifier.py.

Tests every branch of the decision table.
No network, no LLM, no credentials required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from evidence_collector import Evidence
from models.intent_contract import EvidenceStrategy, IntentContract
from test_executor import TestExecutionResult
from test_generator import GeneratedTest
from verdict_classifier import (
    VERDICT_FAILED,
    VERDICT_PROVEN,
    VERDICT_UNPROVEN,
    classify_verdict,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_contract(strategy: EvidenceStrategy = EvidenceStrategy.unit_test) -> IntentContract:
    return IntentContract(
        requirement_id="R01",
        summary="Token TTL",
        acceptance_criteria=["token.expires_in == 900"],
        evidence_strategy=strategy,
        keywords=["token"],
        test_hint="",
    )


def make_valid_test(path: Path = None) -> GeneratedTest:
    p = path or Path("/tmp/test_r01.py")
    return GeneratedTest(req_id="R01", source="def test_r01(): assert True",
                         path=p, is_valid=True, skip_reason="")


def make_invalid_test(reason: str = "no_credentials") -> GeneratedTest:
    return GeneratedTest(req_id="R01", is_valid=False, skip_reason=reason)


def make_passed_exec() -> TestExecutionResult:
    return TestExecutionResult(
        passed=True, return_code=0, stdout="1 passed", stderr="",
        duration_seconds=0.05, timed_out=False,
    )


def make_failed_exec() -> TestExecutionResult:
    return TestExecutionResult(
        passed=False, return_code=1, stdout="1 failed", stderr="",
        duration_seconds=0.05, timed_out=False,
    )


def make_timeout_exec() -> TestExecutionResult:
    return TestExecutionResult(
        passed=False, return_code=-1, stdout="", stderr="",
        duration_seconds=30.0, timed_out=True, error="timeout after 30s",
    )


def make_error_exec(error: str = "subprocess_error: oops") -> TestExecutionResult:
    return TestExecutionResult(
        passed=False, return_code=-1, stdout="", stderr="",
        duration_seconds=0.0, timed_out=False, error=error,
    )


def make_collection_error_exec() -> TestExecutionResult:
    return TestExecutionResult(
        passed=False, return_code=2, stdout="ERROR collecting", stderr="",
        duration_seconds=0.01, timed_out=False,
    )


def make_evidence(passed: bool = None) -> Evidence:
    return Evidence(
        requirement_id="R01",
        evidence_type="test_execution" if passed is not None else "not_executed",
        summary="stub evidence",
        passed=passed,
        return_code=0 if passed else (1 if passed is False else None),
    )


# ---------------------------------------------------------------------------
# Rule 1: invalid generated test → UNPROVEN
# ---------------------------------------------------------------------------

class TestInvalidTest:
    def test_no_credentials_unproven(self):
        assert classify_verdict(
            make_contract(), make_invalid_test("no_credentials"),
            make_passed_exec(), make_evidence(),
        ) == VERDICT_UNPROVEN

    def test_syntax_error_unproven(self):
        assert classify_verdict(
            make_contract(), make_invalid_test("syntax_error: line 3"),
            make_passed_exec(), make_evidence(),
        ) == VERDICT_UNPROVEN

    def test_no_assertion_unproven(self):
        assert classify_verdict(
            make_contract(), make_invalid_test("no_assertion"),
            make_passed_exec(), make_evidence(),
        ) == VERDICT_UNPROVEN

    def test_not_attempted_unproven(self):
        assert classify_verdict(
            make_contract(), make_invalid_test("not_attempted"),
            make_error_exec("test_not_valid"), make_evidence(),
        ) == VERDICT_UNPROVEN


# ---------------------------------------------------------------------------
# Rule 2: timeout → UNPROVEN
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_timeout_unproven(self):
        assert classify_verdict(
            make_contract(), make_valid_test(),
            make_timeout_exec(), make_evidence(),
        ) == VERDICT_UNPROVEN

    def test_timeout_overrides_contract_strategy(self):
        # Even with unit_test strategy, timeout must still be UNPROVEN
        assert classify_verdict(
            make_contract(EvidenceStrategy.unit_test), make_valid_test(),
            make_timeout_exec(), make_evidence(),
        ) == VERDICT_UNPROVEN


# ---------------------------------------------------------------------------
# Rule 3: execution infrastructure error → UNPROVEN
# ---------------------------------------------------------------------------

class TestExecutionError:
    def test_subprocess_error_unproven(self):
        assert classify_verdict(
            make_contract(), make_valid_test(),
            make_error_exec("subprocess_error: No such file"),
            make_evidence(),
        ) == VERDICT_UNPROVEN

    def test_executor_exception_unproven(self):
        assert classify_verdict(
            make_contract(), make_valid_test(),
            make_error_exec("executor_exception: unexpected"),
            make_evidence(),
        ) == VERDICT_UNPROVEN


# ---------------------------------------------------------------------------
# Rule 4: unknown evidence strategy → UNPROVEN
# ---------------------------------------------------------------------------

class TestUnknownStrategy:
    def test_unknown_strategy_with_passing_exec_is_proven(self):
        assert classify_verdict(
            make_contract(EvidenceStrategy.unknown), make_valid_test(),
            make_passed_exec(), make_evidence(passed=True),
        ) == VERDICT_PROVEN

    def test_unknown_strategy_with_failing_exec_is_failed(self):
        assert classify_verdict(
            make_contract(EvidenceStrategy.unknown), make_valid_test(),
            make_failed_exec(), make_evidence(passed=False),
        ) == VERDICT_FAILED
# ---------------------------------------------------------------------------
# Rule 5: valid passing test → PROVEN
# ---------------------------------------------------------------------------

class TestProven:
    def test_passing_test_proven(self):
        assert classify_verdict(
            make_contract(), make_valid_test(),
            make_passed_exec(), make_evidence(passed=True),
        ) == VERDICT_PROVEN

    def test_unit_test_strategy_proven(self):
        assert classify_verdict(
            make_contract(EvidenceStrategy.unit_test), make_valid_test(),
            make_passed_exec(), make_evidence(passed=True),
        ) == VERDICT_PROVEN

    def test_both_strategy_proven(self):
        assert classify_verdict(
            make_contract(EvidenceStrategy.both), make_valid_test(),
            make_passed_exec(), make_evidence(passed=True),
        ) == VERDICT_PROVEN


# ---------------------------------------------------------------------------
# Rule 6: valid failing test → FAILED
# ---------------------------------------------------------------------------

class TestFailed:
    def test_failing_test_failed(self):
        assert classify_verdict(
            make_contract(), make_valid_test(),
            make_failed_exec(), make_evidence(passed=False),
        ) == VERDICT_FAILED

    def test_return_code_1_failed(self):
        assert classify_verdict(
            make_contract(), make_valid_test(),
            make_failed_exec(), make_evidence(passed=False),
        ) == VERDICT_FAILED


# ---------------------------------------------------------------------------
# Rule 7: unexpected return code → UNPROVEN
# ---------------------------------------------------------------------------

class TestUnexpectedReturnCode:
    def test_collection_error_unproven(self):
        # rc=2 = pytest internal / collection error
        assert classify_verdict(
            make_contract(), make_valid_test(),
            make_collection_error_exec(), make_evidence(),
        ) == VERDICT_UNPROVEN

    def test_rc_5_no_tests_collected_unproven(self):
        # rc=5 = no tests collected
        exec_no_tests = TestExecutionResult(
            passed=False, return_code=5, stdout="no tests ran", stderr="",
            duration_seconds=0.01, timed_out=False,
        )
        assert classify_verdict(
            make_contract(), make_valid_test(),
            exec_no_tests, make_evidence(),
        ) == VERDICT_UNPROVEN


# ---------------------------------------------------------------------------
# Verdict constants
# ---------------------------------------------------------------------------

class TestVerdictConstants:
    def test_proven_is_string(self):
        assert VERDICT_PROVEN == "PROVEN"

    def test_failed_is_string(self):
        assert VERDICT_FAILED == "FAILED"

    def test_unproven_is_string(self):
        assert VERDICT_UNPROVEN == "UNPROVEN"

    def test_classify_returns_string(self):
        result = classify_verdict(
            make_contract(), make_valid_test(),
            make_passed_exec(), make_evidence(passed=True),
        )
        assert isinstance(result, str)
        assert result in (VERDICT_PROVEN, VERDICT_FAILED, VERDICT_UNPROVEN)
