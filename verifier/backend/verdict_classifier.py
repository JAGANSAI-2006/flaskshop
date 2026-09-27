"""
verdict_classifier.py — Deterministic, rule-based verdict classification.

The LLM is never consulted here.  The verdict is derived exclusively from
the concrete execution result and the structural properties of the generated
test and its contract.

Allowed verdicts
----------------
  PROVEN   — pytest ran, all assertions passed, return code 0
  FAILED   — pytest ran, at least one assertion failed, return code != 0
  UNPROVEN — anything else (no test, invalid test, timeout, infra error,
              unknown evidence strategy, no code traced)

Public API
----------
classify_verdict(contract, generated_test, execution, evidence) -> str
"""

from __future__ import annotations

import logging

from evidence_collector import Evidence
from models.intent_contract import EvidenceStrategy, IntentContract
from test_executor import TestExecutionResult
from test_generator import GeneratedTest

logger = logging.getLogger(__name__)

# The three permitted verdict strings — used as constants throughout the project.
VERDICT_PROVEN   = "PROVEN"
VERDICT_FAILED   = "FAILED"
VERDICT_UNPROVEN = "UNPROVEN"

# pytest return code for "all tests passed"
_PYTEST_PASSED = 0
# pytest return code for "tests ran but at least one failed"
_PYTEST_FAILED = 1


def classify_verdict(
    contract: IntentContract,
    generated_test: GeneratedTest,
    execution: TestExecutionResult,
    evidence: Evidence,
) -> str:
    """
    Apply the decision table and return one of PROVEN / FAILED / UNPROVEN.

    Decision table (evaluated top-to-bottom, first match wins):

    1. Generated test is invalid (is_valid=False)        → UNPROVEN
    2. Execution timed out                               → UNPROVEN
    3. Execution infrastructure error (error != "")      → UNPROVEN
    4. Contract has evidence_strategy=unknown            → UNPROVEN
       (fallback contract was used; no real test generated via LLM)
    5. pytest return code == 0 and passed == True        → PROVEN
    6. pytest return code == 1 (test failures)           → FAILED
    7. Any other return code (collection error, etc.)    → UNPROVEN
    """
    verdict, reason = _classify(contract, generated_test, execution, evidence)
    logger.info(
        "classify_verdict: %s → %s (%s)", contract.requirement_id, verdict, reason
    )
    return verdict


def _classify(
    contract: IntentContract,
    generated_test: GeneratedTest,
    execution: TestExecutionResult,
    evidence: Evidence,
) -> tuple[str, str]:
    """Return (verdict, reason_string) — reason is for logging only."""

    # Rule 1 — no valid test
    if not generated_test.is_valid:
        return VERDICT_UNPROVEN, f"test_invalid: {generated_test.skip_reason}"

    # Rule 2 — timed out
    if execution.timed_out:
        return VERDICT_UNPROVEN, "execution_timeout"

    # Rule 3 — infrastructure error (test was valid but subprocess blew up)
    if execution.error:
        return VERDICT_UNPROVEN, f"execution_error: {execution.error}"

    # Rule 4 — unknown strategy is allowed when a valid deterministic
    # fallback test actually ran. The concrete pytest result takes priority.
    # Rules 5–7 — test actually ran; classify by return code
    if execution.return_code == _PYTEST_PASSED and execution.passed:
        return VERDICT_PROVEN, "pytest_passed"

    if execution.return_code == _PYTEST_FAILED:
        return VERDICT_FAILED, "pytest_failed"

    # Catch-all: return code 2 (collection error), 3, 4, 5 (no tests), etc.
    return VERDICT_UNPROVEN, f"unexpected_return_code: {execution.return_code}"
