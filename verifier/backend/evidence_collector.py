"""
evidence_collector.py — Assemble an Evidence record from the concrete
outputs of each pipeline stage.

Every field in Evidence is derived directly from the inputs: no facts are
invented, inferred, or fabricated.  The only computation done here is
building a human-readable summary sentence from those same inputs.

Public API
----------
collect_evidence(requirement, contract, traced_code, generated_test, execution)
    -> Evidence
"""

from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from models.code_region import CodeRegion
from models.intent_contract import IntentContract, Requirement
from test_executor import TestExecutionResult
from test_generator import GeneratedTest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evidence model
# ---------------------------------------------------------------------------

class Evidence(BaseModel):
    """Concrete evidence collected for a single requirement."""

    requirement_id: str = Field(..., description="Requirement identifier, e.g. 'R01'")

    evidence_type: str = Field(
        ...,
        description=(
            "One of: 'test_execution' (test ran), "
            "'not_executed' (test invalid/skipped), "
            "'no_test' (no test was generated)"
        ),
    )

    summary: str = Field(
        ..., description="One-sentence human-readable description of the evidence"
    )

    test_file: str = Field(
        default="",
        description="Path to the generated test file, or empty if none was written",
    )

    traced_files: List[str] = Field(
        default_factory=list,
        description="Relative paths of source files traced for this requirement",
    )

    stdout: str = Field(default="", description="pytest stdout (may be truncated)")
    stderr: str = Field(default="", description="pytest stderr (may be truncated)")

    return_code: Optional[int] = Field(
        default=None,
        description="pytest process return code, or None if test was not run",
    )

    passed: Optional[bool] = Field(
        default=None,
        description="True = all pytest tests passed, False = failures, None = not run",
    )


# ---------------------------------------------------------------------------
# Output truncation limit (keep evidence records manageable)
# ---------------------------------------------------------------------------

_MAX_OUTPUT_CHARS = 4000


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def collect_evidence(
    requirement: Requirement,
    contract: IntentContract,
    traced_code: List[CodeRegion],
    generated_test: GeneratedTest,
    execution: TestExecutionResult,
) -> Evidence:
    """
    Assemble an Evidence record from the concrete pipeline outputs.

    Behaviour by case:
    - Test was run and passed   → evidence_type='test_execution', passed=True
    - Test was run and failed   → evidence_type='test_execution', passed=False
    - Test was not run (invalid)→ evidence_type='not_executed'
    - No test was generated     → evidence_type='no_test'
    """
    traced_files = [r.file for r in traced_code]
    test_file_str = str(generated_test.path) if generated_test.path else ""

    # ── Case A: test was executed ──────────────────────────────────────────
    if generated_test.is_valid and not execution.error and not execution.timed_out:
        if execution.passed:
            summary = (
                f"Generated pytest test for {requirement.id} passed "
                f"(exit code 0, duration {execution.duration_seconds:.2f}s). "
                f"Traced {len(traced_files)} source file(s)."
            )
        else:
            summary = (
                f"Generated pytest test for {requirement.id} failed "
                f"(exit code {execution.return_code}, "
                f"duration {execution.duration_seconds:.2f}s). "
                f"Traced {len(traced_files)} source file(s)."
            )
        return Evidence(
            requirement_id=requirement.id,
            evidence_type="test_execution",
            summary=summary,
            test_file=test_file_str,
            traced_files=traced_files,
            stdout=execution.stdout[:_MAX_OUTPUT_CHARS],
            stderr=execution.stderr[:_MAX_OUTPUT_CHARS],
            return_code=execution.return_code,
            passed=execution.passed,
        )

    # ── Case B: test timed out ─────────────────────────────────────────────
    if execution.timed_out:
        summary = (
            f"Test execution for {requirement.id} timed out "
            f"({execution.error}). Cannot determine verdict."
        )
        return Evidence(
            requirement_id=requirement.id,
            evidence_type="not_executed",
            summary=summary,
            test_file=test_file_str,
            traced_files=traced_files,
            stdout=execution.stdout[:_MAX_OUTPUT_CHARS],
            stderr=execution.stderr[:_MAX_OUTPUT_CHARS],
            return_code=execution.return_code,
            passed=None,
        )

    # ── Case C: execution infrastructure error ─────────────────────────────
    if execution.error and generated_test.is_valid:
        summary = (
            f"Test file for {requirement.id} was generated but execution "
            f"failed: {execution.error}."
        )
        return Evidence(
            requirement_id=requirement.id,
            evidence_type="not_executed",
            summary=summary,
            test_file=test_file_str,
            traced_files=traced_files,
            stdout="",
            stderr="",
            return_code=None,
            passed=None,
        )

    # ── Case D: test was not valid / not generated ─────────────────────────
    if not generated_test.is_valid:
        skip = generated_test.skip_reason or "unknown"
        summary = (
            f"No valid test was produced for {requirement.id} "
            f"(reason: {skip}). "
            + (
                f"Traced {len(traced_files)} source file(s)."
                if traced_files
                else "No relevant source files found."
            )
        )
        evidence_type = "not_executed" if generated_test.source else "no_test"
        return Evidence(
            requirement_id=requirement.id,
            evidence_type=evidence_type,
            summary=summary,
            test_file="",
            traced_files=traced_files,
            stdout="",
            stderr="",
            return_code=None,
            passed=None,
        )

    # ── Fallback (should not normally be reached) ──────────────────────────
    logger.warning(
        "collect_evidence: unexpected state for %s — "
        "is_valid=%s error=%r timed_out=%s",
        requirement.id, generated_test.is_valid, execution.error, execution.timed_out,
    )
    return Evidence(
        requirement_id=requirement.id,
        evidence_type="not_executed",
        summary=f"Evidence collection reached unexpected state for {requirement.id}.",
        test_file=test_file_str,
        traced_files=traced_files,
        passed=None,
    )
