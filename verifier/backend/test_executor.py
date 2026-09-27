"""
test_executor.py — Run a GeneratedTest file under pytest in a sandboxed
subprocess and return structured execution results.

Security guarantees
-------------------
- shell=True is never used.
- The only command executed is [sys.executable, "-m", "pytest", <test_file_path>].
- The test file path is an absolute Path on disk written by test_generator.py;
  it is never constructed from LLM output directly.
- Arbitrary commands supplied by the LLM cannot be injected here.

Public API
----------
execute_test(test, repo_path, timeout_seconds) -> TestExecutionResult
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import config
from test_generator import GeneratedTest

logger = logging.getLogger(__name__)

# Pytest exit codes we treat as "test infrastructure ran" (passed or failed)
# vs. exit codes indicating collection errors / no tests found.
_PYTEST_PASSED   = 0
_PYTEST_FAILED   = 1
_PYTEST_ERROR    = 2   # internal error / collection error
_PYTEST_NO_TESTS = 5   # no tests collected


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TestExecutionResult:
    # __test__ = False prevents pytest from trying to collect this dataclass
    # as a test class (its name begins with "Test").
    __test__ = False

    passed: bool
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    error: str = ""


# ---------------------------------------------------------------------------
# Sentinel for "test was not run"
# ---------------------------------------------------------------------------

def _not_run(reason: str) -> TestExecutionResult:
    return TestExecutionResult(
        passed=False,
        return_code=-1,
        stdout="",
        stderr="",
        duration_seconds=0.0,
        timed_out=False,
        error=reason,
    )


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def execute_test(
    test: GeneratedTest,
    repo_path: Path,
    timeout_seconds: int = config.TEST_EXECUTION_TIMEOUT,
) -> TestExecutionResult:
    """
    Execute *test* under pytest and return a TestExecutionResult.

    If *test.is_valid* is False the test is not executed and the result has
    error set to the GeneratedTest.skip_reason.

    The working directory for pytest is *repo_path* so that imports relative
    to the repository root resolve correctly.
    """
    # Guard 1: only run valid, written tests
    if not test.is_valid or test.path is None:
        reason = test.skip_reason or "test_not_valid"
        logger.info("execute_test: skipping %s — %s", test.req_id, reason)
        return _not_run(reason)

    # Guard 2: the file must exist on disk
    test_file = Path(test.path)
    if not test_file.is_file():
        reason = f"test_file_missing: {test_file}"
        logger.warning("execute_test: %s", reason)
        return _not_run(reason)

    cmd = [
        sys.executable,       # exact Python interpreter running this process
        "-m", "pytest",
        str(test_file),       # absolute path — no shell expansion possible
        "--tb=short",
        "-q",
        "--no-header",
    ]

    logger.info(
        "execute_test: running %s in %s (timeout=%ds)",
        test_file.name, repo_path, timeout_seconds,
    )

    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            # shell=True is intentionally NEVER used
        )
        duration = time.monotonic() - start

        passed = result.returncode == _PYTEST_PASSED
        logger.info(
            "execute_test: %s completed in %.2fs — returncode=%d passed=%s",
            test_file.name, duration, result.returncode, passed,
        )
        return TestExecutionResult(
            passed=passed,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=round(duration, 3),
            timed_out=False,
        )

    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        logger.warning(
            "execute_test: %s timed out after %.1fs", test_file.name, duration
        )
        stdout = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return TestExecutionResult(
            passed=False,
            return_code=-1,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(duration, 3),
            timed_out=True,
            error=f"timeout after {timeout_seconds}s",
        )

    except OSError as exc:
        duration = time.monotonic() - start
        logger.error("execute_test: subprocess failed for %s: %s", test_file.name, exc)
        return TestExecutionResult(
            passed=False,
            return_code=-1,
            stdout="",
            stderr="",
            duration_seconds=round(duration, 3),
            timed_out=False,
            error=f"subprocess_error: {exc}",
        )

    except Exception as exc:
        duration = time.monotonic() - start
        logger.error(
            "execute_test: unexpected error for %s: %s", test_file.name, exc
        )
        return TestExecutionResult(
            passed=False,
            return_code=-1,
            stdout="",
            stderr="",
            duration_seconds=round(duration, 3),
            timed_out=False,
            error=f"unexpected_error: {exc}",
        )
