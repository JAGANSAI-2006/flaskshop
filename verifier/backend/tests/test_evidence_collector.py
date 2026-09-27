"""
tests/test_evidence_collector.py — Unit tests for evidence_collector.py.

No network, no LLM, no credentials required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from evidence_collector import Evidence, collect_evidence
from models.code_region import CodeRegion
from models.intent_contract import EvidenceStrategy, IntentContract, Requirement
from test_executor import TestExecutionResult
from test_generator import GeneratedTest


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def make_req(req_id: str = "R01") -> Requirement:
    return Requirement(id=req_id, raw_text="Prices must not be negative.")


def make_contract(strategy: EvidenceStrategy = EvidenceStrategy.unit_test) -> IntentContract:
    return IntentContract(
        requirement_id="R01",
        summary="Price validation",
        acceptance_criteria=["price >= 0"],
        evidence_strategy=strategy,
        keywords=["price", "negative"],
        test_hint="assert price >= 0",
    )


def make_region(file: str = "products/routes.py") -> CodeRegion:
    return CodeRegion(file=file, line_start=1, line_end=5, snippet="def foo(): pass", score=2)


def make_valid_test(path: Path) -> GeneratedTest:
    """Write a dummy test file and return a valid GeneratedTest."""
    path.write_text("def test_r01():\n    assert True\n")
    return GeneratedTest(req_id="R01", source="...", path=path, is_valid=True)


def make_invalid_test(reason: str = "no_credentials") -> GeneratedTest:
    return GeneratedTest(req_id="R01", is_valid=False, skip_reason=reason)


def make_passed_execution() -> TestExecutionResult:
    return TestExecutionResult(
        passed=True, return_code=0,
        stdout="1 passed in 0.01s", stderr="",
        duration_seconds=0.01, timed_out=False,
    )


def make_failed_execution() -> TestExecutionResult:
    return TestExecutionResult(
        passed=False, return_code=1,
        stdout="FAILED test_r01.py::test_r01\n1 failed in 0.02s", stderr="",
        duration_seconds=0.02, timed_out=False,
    )


def make_timeout_execution() -> TestExecutionResult:
    return TestExecutionResult(
        passed=False, return_code=-1,
        stdout="", stderr="",
        duration_seconds=30.0, timed_out=True,
        error="timeout after 30s",
    )


def make_infra_error_execution() -> TestExecutionResult:
    return TestExecutionResult(
        passed=False, return_code=-1,
        stdout="", stderr="",
        duration_seconds=0.0, timed_out=False,
        error="subprocess_error: No such file",
    )


# ---------------------------------------------------------------------------
# Basic return type
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_evidence_instance(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_passed_execution())
        assert isinstance(ev, Evidence)

    def test_requirement_id_matches(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req("R05"), make_contract(), [], gt, make_passed_execution())
        assert ev.requirement_id == "R05"


# ---------------------------------------------------------------------------
# Passing execution
# ---------------------------------------------------------------------------

class TestPassingExecution:
    def test_evidence_type_test_execution(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_passed_execution())
        assert ev.evidence_type == "test_execution"

    def test_passed_is_true(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_passed_execution())
        assert ev.passed is True

    def test_return_code_zero(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_passed_execution())
        assert ev.return_code == 0

    def test_stdout_preserved(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        execution = make_passed_execution()
        ev = collect_evidence(make_req(), make_contract(), [], gt, execution)
        assert ev.stdout == execution.stdout

    def test_summary_mentions_passed(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_passed_execution())
        assert "passed" in ev.summary.lower()

    def test_test_file_path_preserved(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_passed_execution())
        assert str(gt.path) in ev.test_file


# ---------------------------------------------------------------------------
# Failing execution
# ---------------------------------------------------------------------------

class TestFailingExecution:
    def test_evidence_type_test_execution(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_failed_execution())
        assert ev.evidence_type == "test_execution"

    def test_passed_is_false(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_failed_execution())
        assert ev.passed is False

    def test_return_code_one(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_failed_execution())
        assert ev.return_code == 1

    def test_stdout_preserved(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        execution = make_failed_execution()
        ev = collect_evidence(make_req(), make_contract(), [], gt, execution)
        assert ev.stdout == execution.stdout

    def test_summary_mentions_failed(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_failed_execution())
        assert "failed" in ev.summary.lower()


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestTimeoutExecution:
    def test_evidence_type_not_executed(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_timeout_execution())
        assert ev.evidence_type == "not_executed"

    def test_passed_is_none(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_timeout_execution())
        assert ev.passed is None

    def test_summary_mentions_timeout(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_timeout_execution())
        assert "timeout" in ev.summary.lower() or "timed" in ev.summary.lower()


# ---------------------------------------------------------------------------
# Infrastructure error
# ---------------------------------------------------------------------------

class TestInfraError:
    def test_evidence_type_not_executed(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_infra_error_execution())
        assert ev.evidence_type == "not_executed"

    def test_passed_is_none(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_infra_error_execution())
        assert ev.passed is None


# ---------------------------------------------------------------------------
# Invalid / missing test
# ---------------------------------------------------------------------------

class TestInvalidTest:
    def test_no_credentials_evidence_type(self):
        ev = collect_evidence(
            make_req(), make_contract(), [],
            make_invalid_test("no_credentials"),
            TestExecutionResult(passed=False, return_code=-1, stdout="", stderr="",
                                duration_seconds=0.0, timed_out=False,
                                error="test_not_valid"),
        )
        assert ev.evidence_type in ("not_executed", "no_test")

    def test_passed_is_none_for_invalid_test(self):
        ev = collect_evidence(
            make_req(), make_contract(), [],
            make_invalid_test("syntax_error: blah"),
            TestExecutionResult(passed=False, return_code=-1, stdout="", stderr="",
                                duration_seconds=0.0, timed_out=False,
                                error="test_not_valid"),
        )
        assert ev.passed is None

    def test_skip_reason_in_summary(self):
        ev = collect_evidence(
            make_req(), make_contract(), [],
            make_invalid_test("no_credentials"),
            TestExecutionResult(passed=False, return_code=-1, stdout="", stderr="",
                                duration_seconds=0.0, timed_out=False,
                                error="test_not_valid"),
        )
        assert "no_credentials" in ev.summary


# ---------------------------------------------------------------------------
# Traced files preserved
# ---------------------------------------------------------------------------

class TestTracedFiles:
    def test_traced_files_included(self, tmp_path):
        regions = [make_region("auth/tokens.py"), make_region("products/routes.py")]
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), regions, gt, make_passed_execution())
        assert "auth/tokens.py" in ev.traced_files
        assert "products/routes.py" in ev.traced_files

    def test_empty_traced_files(self, tmp_path):
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), [], gt, make_passed_execution())
        assert ev.traced_files == []

    def test_traced_files_not_fabricated(self, tmp_path):
        # Only 1 region supplied — must not appear as 2 in evidence
        regions = [make_region("auth/tokens.py")]
        gt = make_valid_test(tmp_path / "test_r01.py")
        ev = collect_evidence(make_req(), make_contract(), regions, gt, make_passed_execution())
        assert len(ev.traced_files) == 1


# ---------------------------------------------------------------------------
# No fabricated evidence
# ---------------------------------------------------------------------------

class TestNoFabrication:
    def test_passing_result_not_set_when_not_executed(self):
        """passed must be None when test was not run — never fabricated as True."""
        ev = collect_evidence(
            make_req(), make_contract(), [],
            make_invalid_test("no_credentials"),
            TestExecutionResult(passed=False, return_code=-1, stdout="", stderr="",
                                duration_seconds=0.0, timed_out=False,
                                error="test_not_valid"),
        )
        assert ev.passed is not True

    def test_stdout_empty_when_not_run(self):
        ev = collect_evidence(
            make_req(), make_contract(), [],
            make_invalid_test("no_credentials"),
            TestExecutionResult(passed=False, return_code=-1, stdout="", stderr="",
                                duration_seconds=0.0, timed_out=False,
                                error="test_not_valid"),
        )
        assert ev.stdout == ""
