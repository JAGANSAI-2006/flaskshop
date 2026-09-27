"""
main.py — FastAPI application entry point.

Exposes:
  GET  /                  → redirect to /health
  GET  /health            → status check (always available, no credentials needed)
  POST /ingest            → clone repo + parse requirements, return file index
  POST /verify            → run full verification pipeline, return per-req verdicts
  GET  /report/{job_id}   → retrieve stored result for a completed job
"""

from __future__ import annotations

import logging
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

import config
import repo_ingestor
from pipeline import verify_requirement
from requirement_parser import parse_requirements

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=config.APP_TITLE,
    version=config.APP_VERSION,
    description=(
        "Automatically verify that software requirements are satisfied by code — "
        "with evidence, not opinions."
    ),
)

# ── In-memory job store ───────────────────────────────────────────────────────
# Maps job_id → serialised VerifyResponse dict.
# Cleared when the process restarts; sufficient for the MVP / hackathon demo.
_job_store: Dict[str, dict] = {}


# ── Request / response models ────────────────────────────────────────────────


class IngestRequest(BaseModel):
    repo_url: str = Field(..., description="Public Git repository URL to clone")
    requirements_text: str = Field(
        ..., min_length=1, description="Raw requirements text (numbered, bullets, or plain lines)"
    )


class IngestResponse(BaseModel):
    job_id: str
    requirements: list
    file_index: dict
    repo_path: str
    file_count: int


class VerifyRequest(BaseModel):
    repo_url: str = Field(..., description="Public Git repository URL to verify against")
    requirements: List[str] = Field(
        ..., min_length=1, description="List of plain-text requirements to verify"
    )

    @field_validator("repo_url")
    @classmethod
    def repo_url_must_have_scheme(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("repo_url must not be empty")
        if not (v.startswith("https://") or v.startswith("http://") or v.startswith("git@")):
            raise ValueError(
                "repo_url must start with https://, http://, or git@ — "
                f"got: {v!r}"
            )
        return v

    @field_validator("requirements")
    @classmethod
    def requirements_must_be_non_empty_strings(cls, v: List[str]) -> List[str]:
        cleaned = [r.strip() for r in v if r.strip()]
        if not cleaned:
            raise ValueError("requirements must contain at least one non-blank string")
        return cleaned


class VerifySummary(BaseModel):
    proven: int
    failed: int
    unproven: int
    total: int


class VerifyResponse(BaseModel):
    job_id: str
    results: list          # list of RequirementResult dicts
    summary: VerifySummary


# ── Routes ───────────────────────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/health")


@app.get("/health")
async def health() -> JSONResponse:
    """
    Always returns 200.  Reports credentials and pipeline availability.
    pipeline_ready is True when the pipeline modules are importable — it does
    NOT require IBM credentials to be set.
    """
    creds_ok = config.credentials_available()
    try:
        from pipeline import verify_requirement as _vr  # noqa: F401
        pipeline_ready = True
    except Exception:
        pipeline_ready = False

    return JSONResponse(
        content={
            "status": "ok",
            "app": config.APP_TITLE,
            "version": config.APP_VERSION,
            "model": config.GRANITE_MODEL_ID,
            "watsonx_credentials_configured": creds_ok,
            "pipeline_ready": pipeline_ready,
        }
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest) -> IngestResponse:
    """
    Clone a public Git repository and parse requirements text.

    1. Validates the repo URL format.
    2. Parses requirements_text into structured Requirement objects.
    3. Clones the repo (shallow, depth=1) into a per-job temp directory.
    4. Builds a Python symbol index (file → [function/class names]).
    5. Returns the job_id, parsed requirements, and file index.

    The job_id is used by later pipeline endpoints (/analyse, /status, /report).
    """
    # Parse requirements first — fast, no I/O, fails early on bad input
    requirements = parse_requirements(body.requirements_text)
    if not requirements:
        raise HTTPException(
            status_code=422,
            detail="requirements_text produced no parseable requirements. "
                   "Ensure the text contains at least one non-blank line.",
        )

    job_id = repo_ingestor.new_job_id()

    try:
        repo_path = repo_ingestor.clone_repo(body.repo_url, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        file_index = repo_ingestor.build_file_index(repo_path)
    except RuntimeError as exc:
        repo_ingestor.cleanup_repo(job_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Ingest complete: job=%s reqs=%d files=%d",
        job_id, len(requirements), len(file_index),
    )

    return IngestResponse(
        job_id=job_id,
        requirements=[r.model_dump() for r in requirements],
        file_index=file_index,
        repo_path=str(repo_path),
        file_count=len(file_index),
    )


@app.post("/verify", response_model=VerifyResponse)
async def verify(body: VerifyRequest) -> VerifyResponse:
    """
    Run the full verification pipeline against a public Git repository.

    Steps:
      1. Clone the repository (shallow, depth=1).
      2. Build the Python symbol index.
      3. Parse each requirement string into a Requirement object.
      4. Run verify_requirement() for every requirement sequentially.
         The repo is cloned only once; all requirements share the same clone.
      5. Store the result by job_id.
      6. Return the result immediately (synchronous, no SSE).

    The repository clone is kept in TEMP_BASE_DIR/<job_id>/ and reused across
    all requirements in this job.  It is not deleted at the end of the request
    so that GET /report/{job_id} can still reference the paths.
    """
    job_id = repo_ingestor.new_job_id()

    # ── Clone repo ──────────────────────────────────────────────────────────
    try:
        repo_path = repo_ingestor.clone_repo(body.repo_url, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ── Build file index (once, shared across all requirements) ─────────────
    try:
        file_index = repo_ingestor.build_file_index(repo_path)
    except RuntimeError as exc:
        repo_ingestor.cleanup_repo(job_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "verify: job=%s url=%s files=%d reqs=%d",
        job_id, body.repo_url, len(file_index), len(body.requirements),
    )

    # ── Parse requirement strings into Requirement objects ───────────────────
    # Accept raw strings directly — assign sequential IDs.
    from models.intent_contract import Requirement
    requirements = [
        Requirement(id=f"R{i+1:02d}", raw_text=text)
        for i, text in enumerate(body.requirements)
    ]

    # ── Run pipeline for each requirement ────────────────────────────────────
    results = []
    for req in requirements:
        result = verify_requirement(req, repo_path, job_id, file_index)
        results.append(result.model_dump())

    # ── Build summary ────────────────────────────────────────────────────────
    proven   = sum(1 for r in results if r["verdict"] == "PROVEN")
    failed   = sum(1 for r in results if r["verdict"] == "FAILED")
    unproven = sum(1 for r in results if r["verdict"] == "UNPROVEN")

    response = VerifyResponse(
        job_id=job_id,
        results=results,
        summary=VerifySummary(
            proven=proven,
            failed=failed,
            unproven=unproven,
            total=len(results),
        ),
    )

    # ── Store for GET /report/{job_id} ───────────────────────────────────────
    _job_store[job_id] = response.model_dump()

    logger.info(
        "verify: job=%s done — proven=%d failed=%d unproven=%d",
        job_id, proven, failed, unproven,
    )
    return response


@app.get("/report/{job_id}")
async def report(job_id: str) -> JSONResponse:
    """
    Return the stored verification result for *job_id*.

    Returns 404 if the job_id is unknown (e.g. the server was restarted
    or the job_id was never created).
    """
    stored = _job_store.get(job_id)
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail=f"No report found for job_id '{job_id}'. "
                   "The server may have been restarted, or the job_id is invalid.",
        )
    return JSONResponse(content=stored)


# ── Dev entry-point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
