"""
pipeline.py — Orchestrate the full per-requirement verification pipeline.

Requirement → Contract → Trace → Test → Execute → Evidence → Verdict → Result

Each stage is wrapped in its own try/except so a failure at any single stage
degrades the result to UNPROVEN rather than crashing the whole pipeline.
The caller can safely iterate over many requirements and collect all results.

Public API
----------
verify_requirement(requirement, repo_path, job_id, file_index, client=None)
    -> RequirementResult
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from code_tracer import FileIndex, trace
from contract_generator import fallback_contract, generate_contract
from evidence_collector import Evidence, collect_evidence
from models.code_region import CodeRegion
from models.intent_contract import EvidenceStrategy, Requirement, RequirementResult
from test_executor import TestExecutionResult, execute_test, _not_run
from test_generator import GeneratedTest, generate_test
from verdict_classifier import (
    VERDICT_UNPROVEN,
    classify_verdict,
)

logger = logging.getLogger(__name__)


def verify_requirement(
    requirement: Requirement,
    repo_path: Path,
    job_id: str,
    file_index: FileIndex,
    client=None,  # WatsonxClient | None
) -> RequirementResult:
    """
    Run the full verification pipeline for a single *requirement*.

    Parameters
    ----------
    requirement  : parsed Requirement object
    repo_path    : absolute path to the cloned repository on disk
    job_id       : identifier for this verification run (used for temp paths)
    file_index   : FileIndex from repo_ingestor.build_file_index()
    client       : optional pre-built WatsonxClient; auto-resolved if None

    Returns
    -------
    RequirementResult with all fields populated.  Never raises.
    """
    req_id = requirement.id
    logger.info("pipeline: starting %s", req_id)

    # Initialise result with safe defaults so every early-exit still returns
    # a fully-populated object.
    result = RequirementResult(
        id=req_id,
        raw=requirement.raw_text,
        verdict=VERDICT_UNPROVEN,
    )

        # ── Stage 1: Intent Contract ───────────────────────────────────────────
    try:
        contract = generate_contract(requirement, client=client)
        result.contract = contract
        logger.info(
            "pipeline: contract generated for %s (strategy=%s)",
            req_id,
            contract.evidence_strategy,
        )
    except Exception as exc:
        logger.error(
            "pipeline: contract stage failed for %s: %s",
            req_id,
            exc,
        )
        result.error = f"contract_error: {exc}"
        result.verdict = VERDICT_UNPROVEN
        return result
    # ── Stage 2: Code Trace ────────────────────────────────────────────────
    traced_code: List[CodeRegion] = []
    try:
        traced_code = trace(contract, file_index, repo_path)
        result.traced_code = traced_code
        logger.info("pipeline: traced %d region(s) for %s", len(traced_code), req_id)
    except Exception as exc:
        logger.error("pipeline: trace stage failed for %s: %s", req_id, exc)
        result.error = (result.error + f" | trace_error: {exc}").lstrip(" | ")
        result.verdict = VERDICT_UNPROVEN
        return result
    # ── Stage 3: Test Generation ───────────────────────────────────────────
    generated_test = GeneratedTest(req_id=req_id, skip_reason="not_attempted")
    try:
        generated_test = generate_test(
            requirement, contract, traced_code, repo_path, job_id, client=client
        )
        result.generated_test = generated_test.source
        logger.info(
            "pipeline: test generation for %s — is_valid=%s skip=%s",
            req_id, generated_test.is_valid, generated_test.skip_reason,
        )
    except Exception as exc:
        logger.error("pipeline: test generation failed for %s: %s", req_id, exc)
        generated_test = GeneratedTest(req_id=req_id, skip_reason=f"generation_error: {exc}")
        result.error = (result.error + f" | test_gen_error: {exc}").lstrip(" | ")

    # ── Stage 4: Test Execution ────────────────────────────────────────────
    execution = _not_run("not_attempted")
    try:
        execution = execute_test(generated_test, repo_path)
        logger.info(
            "pipeline: execution for %s — passed=%s timed_out=%s rc=%s",
            req_id, execution.passed, execution.timed_out, execution.return_code,
        )
    except Exception as exc:
        logger.error("pipeline: executor failed for %s: %s", req_id, exc)
        execution = _not_run(f"executor_exception: {exc}")
        result.error = (result.error + f" | executor_error: {exc}").lstrip(" | ")

    # ── Stage 5: Evidence Collection ──────────────────────────────────────
    evidence: Optional[Evidence] = None
    try:
        evidence = collect_evidence(
            requirement, contract, traced_code, generated_test, execution
        )
        result.execution_output = (
            (evidence.stdout or "") + ("\n" + evidence.stderr if evidence.stderr else "")
        ).strip()
        logger.info("pipeline: evidence collected for %s — type=%s",
                    req_id, evidence.evidence_type)
    except Exception as exc:
        logger.error("pipeline: evidence stage failed for %s: %s", req_id, exc)
        result.error = (result.error + f" | evidence_error: {exc}").lstrip(" | ")
        # Build a minimal Evidence so the classifier can still run
        from evidence_collector import Evidence as _Ev
        evidence = _Ev(
            requirement_id=req_id,
            evidence_type="not_executed",
            summary=f"Evidence collection failed: {exc}",
        )

    # ── Stage 6: Verdict ───────────────────────────────────────────────────
    try:
        verdict = classify_verdict(contract, generated_test, execution, evidence)
        result.verdict = verdict
    except Exception as exc:
        logger.error("pipeline: verdict stage failed for %s: %s", req_id, exc)
        result.verdict = VERDICT_UNPROVEN
        result.error = (result.error + f" | verdict_error: {exc}").lstrip(" | ")

    # ── Populate summary ───────────────────────────────────────────────────
    result.evidence_summary = evidence.summary if evidence else (
        result.error or "Pipeline did not produce evidence."
    )

    logger.info("pipeline: %s → %s", req_id, result.verdict)
    return result
