"""
tests/test_test_executor.py — Unit tests for test_executor.py.

All tests use real tiny Python files written to tmp_path.
No network, no LLM, no credentials required.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from test_executor import TestExecutionResult, execute_test, _not_run
from test_generator import GeneratedTest


# ---------------------------------------------------------------------------
# Helpers — build GeneratedTest fixtures backed by real files
# ---------------------------------------------------------------------------

def _write_test(tmp_path: Path, name: str, source: str) -> GeneratedTest:
    """Write *source* to a .py file and return a valid GeneratedTest."""
    repo_path_repr = repr(str(tmp_path))
    full = f"import sys\nsys.path.insert(0, {repo_path_repr})\n\n" + source
    test_file = tmp_path / f"{name}.py"
    test_file.write_text(full, encoding="utf-8")
    return GeneratedTest(
        req_id="R01",
        source=full,
        path=test_file,
        is_valid=True,
        skip_reason="",
    )


PASSING_SOURCE = textwrap.dedent("""\
    def test_always_passes():
        assert 1 + 1 == 2
""")

FAILING_SOURCE = textwrap.dedent("""\
    def test_always_fails():
        assert 1 == 2, "intentional failure"
""")

STDOUT_SOURCE = textwrap.dedent("""\
    def test_with_output():
        print("hello from test")
        assert True
""")

ERROR_SOURCE = textwrap.dedent("""\
    import this_module_does_not_exist_xyz
    def test_import_error():
        assert True
""")

SLOW_SOURCE = textwrap.dedent("""\
    import time
    def test_slow():
        time.sleep(60)
        assert True
""")


# ---------------------------------------------------------------------------
# TestExecutionResult — _not_run sentinel
# ---------------------------------------------------------------------------

class TestNotRun:
    def test_not_run_fields(self):
        r = _not_run("some_reason")
        assert r.passed is False
        assert r.return_code == -1
        assert r.error == "some_reason"
        assert r.timed_out is False
        assert r.duration_seconds == 0.0


# ---------------------------------------------------------------------------
# execute_test — invalid / not-generated test
# ---------------------------------------------------------------------------

class TestInvalidTest:
    def test_invalid_test_not_executed(self, tmp_path):
        invalid = GeneratedTest(req_id="R01", is_valid=False, skip_reason="no_credentials")
        result = execute_test(invalid, tmp_path)
        assert isinstance(result, TestExecutionResult)
        assert result.passed is False
        assert result.return_code == -1
        assert "no_credentials" in result.error

    def test_none_path_not_executed(self, tmp_path):
        invalid = GeneratedTest(req_id="R01", is_valid=True, path=None)
        result = execute_test(invalid, tmp_path)
        assert result.passed is False
        assert result.error != ""

    def test_missing_file_not_executed(self, tmp_path):
        gt = GeneratedTest(
            req_id="R01", is_valid=True,
            path=tmp_path / "does_not_exist.py",
        )
        result = execute_test(gt, tmp_path)
        assert result.passed is False
        assert "test_file_missing" in result.error


# ---------------------------------------------------------------------------
# execute_test — passing test
# ---------------------------------------------------------------------------

class TestPassingTest:
    def test_passing_test_returns_passed_true(self, tmp_path):
        gt = _write_test(tmp_path, "test_pass", PASSING_SOURCE)
        result = execute_test(gt, tmp_path)
        assert result.passed is True

    def test_passing_test_return_code_zero(self, tmp_path):
        gt = _write_test(tmp_path, "test_pass2", PASSING_SOURCE)
        result = execute_test(gt, tmp_path)
        assert result.return_code == 0

    def test_passing_test_duration_positive(self, tmp_path):
        gt = _write_test(tmp_path, "test_pass3", PASSING_SOURCE)
        result = execute_test(gt, tmp_path)
        assert result.duration_seconds >= 0.0

    def test_passing_test_timed_out_false(self, tmp_path):
        gt = _write_test(tmp_path, "test_pass4", PASSING_SOURCE)
        result = execute_test(gt, tmp_path)
        assert result.timed_out is False

    def test_passing_test_no_error(self, tmp_path):
        gt = _write_test(tmp_path, "test_pass5", PASSING_SOURCE)
        result = execute_test(gt, tmp_path)
        assert result.error == ""


# ---------------------------------------------------------------------------
# execute_test — failing test
# ---------------------------------------------------------------------------

class TestFailingTest:
    def test_failing_test_returns_passed_false(self, tmp_path):
        gt = _write_test(tmp_path, "test_fail", FAILING_SOURCE)
        result = execute_test(gt, tmp_path)
        assert result.passed is False

    def test_failing_test_return_code_one(self, tmp_path):
        gt = _write_test(tmp_path, "test_fail2", FAILING_SOURCE)
        result = execute_test(gt, tmp_path)
        assert result.return_code == 1

    def test_failing_test_stderr_or_stdout_captured(self, tmp_path):
        gt = _write_test(tmp_path, "test_fail3", FAILING_SOURCE)
        result = execute_test(gt, tmp_path)
        # pytest outputs failure info to stdout in -q mode
        combined = result.stdout + result.stderr
        assert len(combined) > 0

    def test_failing_test_timed_out_false(self, tmp_path):
        gt = _write_test(tmp_path, "test_fail4", FAILING_SOURCE)
        result = execute_test(gt, tmp_path)
        assert result.timed_out is False


# ---------------------------------------------------------------------------
# execute_test — stdout/stderr captured
# ---------------------------------------------------------------------------

class TestOutputCapture:
    def test_stdout_captured(self, tmp_path):
        gt = _write_test(tmp_path, "test_stdout", STDOUT_SOURCE)
        result = execute_test(gt, tmp_path)
        # pytest -q suppresses print by default, but stdout/stderr are strings
        assert isinstance(result.stdout, str)
        assert isinstance(result.stderr, str)

    def test_import_error_captured(self, tmp_path):
        gt = _write_test(tmp_path, "test_import_err", ERROR_SOURCE)
        result = execute_test(gt, tmp_path)
        # Import error causes collection error (rc=2) or failure (rc=1)
        assert result.passed is False
        combined = result.stdout + result.stderr
        assert len(combined) > 0


# ---------------------------------------------------------------------------
# execute_test — timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_timeout_returns_timed_out_true(self, tmp_path):
        gt = _write_test(tmp_path, "test_slow", SLOW_SOURCE)
        result = execute_test(gt, tmp_path, timeout_seconds=1)
        assert result.timed_out is True

    def test_timeout_passed_is_false(self, tmp_path):
        gt = _write_test(tmp_path, "test_slow2", SLOW_SOURCE)
        result = execute_test(gt, tmp_path, timeout_seconds=1)
        assert result.passed is False

    def test_timeout_error_message_set(self, tmp_path):
        gt = _write_test(tmp_path, "test_slow3", SLOW_SOURCE)
        result = execute_test(gt, tmp_path, timeout_seconds=1)
        assert "timeout" in result.error.lower()


# ---------------------------------------------------------------------------
# execute_test — shell=True never used (structural test)
# ---------------------------------------------------------------------------

class TestNoShell:
    def test_shell_never_true(self, tmp_path):
        """Verify subprocess.run is called without shell=True."""
        gt = _write_test(tmp_path, "test_noshell", PASSING_SOURCE)
        calls = []

        original_run = __import__("subprocess").run

        def mock_run(cmd, **kwargs):
            calls.append(kwargs)
            return original_run(cmd, **kwargs)

        with patch("subprocess.run", side_effect=mock_run):
            execute_test(gt, tmp_path)

        assert len(calls) >= 1
        for kw in calls:
            assert kw.get("shell", False) is False, "shell=True must never be used"


# ---------------------------------------------------------------------------
# execute_test — subprocess OSError handled gracefully
# ---------------------------------------------------------------------------

class TestSubprocessError:
    def test_oserror_handled(self, tmp_path):
        gt = _write_test(tmp_path, "test_oserr", PASSING_SOURCE)
        with patch("subprocess.run", side_effect=OSError("binary not found")):
            result = execute_test(gt, tmp_path)
        assert result.passed is False
        assert "subprocess_error" in result.error

    def test_pipeline_does_not_crash_on_oserror(self, tmp_path):
        gt = _write_test(tmp_path, "test_oserr2", PASSING_SOURCE)
        with patch("subprocess.run", side_effect=OSError("binary not found")):
            result = execute_test(gt, tmp_path)
        # Must return a valid dataclass, not raise
        assert isinstance(result, TestExecutionResult)
