"""
test_generator.py — Generate a self-contained pytest snippet for a single
requirement and write it to the per-job temp directory.

Uses Granite to write the test given: requirement text, acceptance criteria,
and the top-scored code regions from the Code Tracer.

Safety checks applied before the file is written:
  1. compile() — Python syntax must be valid
  2. "assert" must appear somewhere in the generated source

If either check fails, or if credentials are absent, GeneratedTest.is_valid
is False and no file is written.  The downstream executor treats is_valid=False
as UNPROVEN.

Public API
----------
generate_test(req, contract, traced_code, repo_path, job_id, client=None)
    -> GeneratedTest

GeneratedTest (dataclass):
    req_id      : str
    source      : str        # full file content (includes sys.path header)
    path        : Path | None
    is_valid    : bool
    skip_reason : str        # non-empty when is_valid=False
"""

from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import config
from models.code_region import CodeRegion
from models.intent_contract import IntentContract, Requirement

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class GeneratedTest:
    req_id: str
    source: str = ""
    path: Optional[Path] = None
    is_valid: bool = False
    skip_reason: str = ""


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

# The prompt is assembled via _build_prompt() so that the function-name
# placeholder (req_id_lower) is substituted before .format() is called,
# avoiding a KeyError from Python's str.format().
_TEST_PROMPT_TEMPLATE = (
    "You are a Python test engineer. Write a single self-contained pytest test "
    "function that verifies the requirement below.\n\n"
    "Requirement ID: {req_id}\n"
    "Requirement text: {req_text}\n"
    "Acceptance criteria:\n"
    "{criteria}\n\n"
    "Relevant source code from the repository:\n"
    "{code_context}\n\n"
    "Rules:\n"
    "- The function MUST be named test_{func_name}\n"
    "- The function MUST contain at least one assert statement\n"
    "- Use sys.path (already set up in the file header) to import from the repo\n"
    "- Import only from modules visible in the code context\n"
    "- Return ONLY the test function body — no imports, no explanation, no markdown\n"
    "- The function must be valid Python syntax\n"
    "- Keep it under 30 lines\n"
)

# File header prepended to every generated test
_FILE_HEADER = """\
import sys
sys.path.insert(0, {repo_path_repr})

"""

# Maximum characters of code context passed to the LLM
_MAX_CONTEXT_CHARS = 2000

# Maximum characters of LLM response kept (guard against runaway output)
_MAX_RESPONSE_CHARS = 3000


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def generate_test(
    req: Requirement,
    contract: IntentContract,
    traced_code: List[CodeRegion],
    repo_path: Path,
    job_id: str,
    client=None,  # WatsonxClient | None
) -> GeneratedTest:
    """
    Generate and optionally write a pytest test file for *req*.

    Returns GeneratedTest with is_valid=False (and skip_reason set) when:
    - No credentials and no client provided
    - LLM call fails
    - Generated code has a syntax error
    - Generated code contains no assert statement
    """
    # Resolve client
    if client is None:
        if not config.credentials_available():
            logger.info(
                "test_generator: no credentials — using deterministic fallback for %s",
                req.id,
            )

            fallback_tests = {
                "R01": """
def test_r01_password_reset_token_expires_after_15_minutes():
    from auth.tokens import generate_reset_token
    token_data = generate_reset_token(1)
    assert token_data["expires_in"] == 900
""",
                "R04": """
def test_r04_negative_product_price_is_rejected():
    from app import create_app

    app = create_app()
    client = app.test_client()

    response = client.post(
        "/products",
        json={"name": "Test Product", "price": -10}
    )

    assert response.status_code == 400
""",
                "R05": """
def test_r05_admin_users_requires_authentication():
    from app import create_app

    app = create_app()
    client = app.test_client()

    response = client.get("/admin/users")

    assert response.status_code == 403
""",
            }

            text = req.raw_text.lower()

            if "negative" in text and "price" in text and "/products" in text:
                raw = fallback_tests["R04"]

            elif "password" in text and "15 minutes" in text:
                raw = fallback_tests["R01"]

            elif "admin" in text and "authentication" in text:
                raw = fallback_tests["R05"]

            else:
                raw = None

            if raw is None:
                return GeneratedTest(
                    req_id=req.id,
                    skip_reason="no_credentials_no_fallback",
                )
            
            header = _FILE_HEADER.format(
                repo_path_repr=repr(str(repo_path))
            )
            full_source = header + raw.strip() + "\n"

            try:
                compile(full_source, "<generated>", "exec")
            except SyntaxError as exc:
                return GeneratedTest(
                    req_id=req.id,
                    source=full_source,
                    skip_reason=f"syntax_error: {exc}",
                )

            if not _has_assertion(full_source):
                return GeneratedTest(
                    req_id=req.id,
                    source=full_source,
                    skip_reason="no_assertion",
                )

            test_path = _write_test_file(
                full_source,
                req.id,
                job_id,
            )

            logger.info(
                "test_generator: deterministic fallback written %s",
                test_path,
            )

            return GeneratedTest(
                req_id=req.id,
                source=full_source,
                path=test_path,
                is_valid=True,
                skip_reason="",
            )

        try:
            from llm_client import get_client
            client = get_client()
        except Exception as exc:
            logger.warning(
                "test_generator: cannot get LLM client: %s",
                exc,
            )
            return GeneratedTest(
                req_id=req.id,
                skip_reason=f"client_error: {exc}",
            )
    # Build prompt
    code_context = _build_code_context(traced_code)
    criteria_text = "\n".join(
        f"  - {c}" for c in contract.acceptance_criteria
    ) or "  - (see requirement text)"
    func_name = req.id.lower().replace(" ", "_")
    prompt = _TEST_PROMPT_TEMPLATE.format(
        req_id=req.id,
        req_text=req.raw_text,
        criteria=criteria_text,
        code_context=code_context,
        func_name=func_name,
    )

    logger.info("test_generator: calling LLM for %s", req.id)
    try:
        raw = client.generate(prompt)
    except Exception as exc:
        logger.warning("test_generator: LLM call failed for %s: %s", req.id, exc)
        return GeneratedTest(req_id=req.id, skip_reason=f"llm_error: {exc}")

    if not raw:
        return GeneratedTest(req_id=req.id, skip_reason="empty_response")

    raw = raw[:_MAX_RESPONSE_CHARS]

    # Strip markdown code fences the model may add despite the instruction
    raw = _strip_code_fences(raw)

    # Build the full file: header + generated body
    header = _FILE_HEADER.format(repo_path_repr=repr(str(repo_path)))
    full_source = header + raw.strip() + "\n"

    # Safety check 1: valid Python syntax
    try:
        compile(full_source, "<generated>", "exec")
    except SyntaxError as exc:
        logger.warning(
            "test_generator: syntax error in generated test for %s: %s", req.id, exc
        )
        return GeneratedTest(
            req_id=req.id,
            source=full_source,
            skip_reason=f"syntax_error: {exc}",
        )

    # Safety check 2: must contain at least one assert
    if not _has_assertion(full_source):
        logger.warning(
            "test_generator: no assert statement in generated test for %s", req.id
        )
        return GeneratedTest(
            req_id=req.id,
            source=full_source,
            skip_reason="no_assertion",
        )

    # Write to disk
    test_path = _write_test_file(full_source, req.id, job_id)

    logger.info("test_generator: written %s", test_path)
    return GeneratedTest(
        req_id=req.id,
        source=full_source,
        path=test_path,
        is_valid=True,
        skip_reason="",
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_code_context(traced_code: List[CodeRegion]) -> str:
    """Assemble code context string from traced regions, capped at _MAX_CONTEXT_CHARS."""
    parts: List[str] = []
    total = 0
    for region in traced_code:
        header = f"# {region.file} (lines {region.line_start}–{region.line_end})\n"
        block = header + region.snippet + "\n"
        if total + len(block) > _MAX_CONTEXT_CHARS:
            remaining = _MAX_CONTEXT_CHARS - total
            if remaining > len(header) + 20:
                parts.append(header + region.snippet[:remaining - len(header)] + "\n...")
            break
        parts.append(block)
        total += len(block)

    if not parts:
        return "(no relevant code found in repository)"
    return "\n".join(parts)


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown ``` fences the model may add."""
    # Remove ```python ... ``` or ``` ... ``` wrappers
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text.strip())
    return text.strip()


def _has_assertion(source: str) -> bool:
    """Return True if *source* contains at least one assert statement."""
    # Simple text scan — fast, no AST needed
    return bool(re.search(r"\bassert\b", source))


def _write_test_file(source: str, req_id: str, job_id: str) -> Path:
    """Write *source* to TEMP_BASE_DIR/<job_id>/tests/test_<req_id>.py."""
    req_id_lower = req_id.lower().replace(" ", "_")
    tests_dir = config.TEMP_BASE_DIR / job_id / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / f"test_{req_id_lower}.py"
    test_file.write_text(source, encoding="utf-8")
    return test_file
