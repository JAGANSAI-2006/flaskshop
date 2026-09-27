"""
contract_generator.py — Convert a single Requirement into a validated
IntentContract using an LLM call to Granite.

If credentials are absent, the LLM returns malformed JSON, or Pydantic
validation fails, a keyword-extracted fallback contract is returned so the
pipeline continues gracefully with an UNPROVEN verdict rather than crashing.

Public API
----------
generate_contract(req, client=None) -> IntentContract
    Returns a validated IntentContract (live) or a fallback contract (no creds).

fallback_contract(req) -> IntentContract
    Pure-Python fallback; always succeeds; no LLM call.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from pydantic import ValidationError

import config
from models.intent_contract import EvidenceStrategy, IntentContract, Requirement

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_CONTRACT_PROMPT = """\
You are a software quality engineer. Convert the requirement below into a \
structured JSON specification that will be used to generate and execute \
automated verification tests.

Requirement ID: {req_id}
Requirement text: {req_text}

Return ONLY a single JSON object with exactly these fields (no explanation, \
no markdown fences, no extra text):

{{
  "requirement_id": "{req_id}",
  "summary": "<10-word label>",
  "acceptance_criteria": ["<criterion 1>", "<criterion 2>"],
  "evidence_strategy": "<one of: unit_test | static_analysis | both>",
  "keywords": ["<search token 1>", "<search token 2>", "<search token 3>"],
  "test_hint": "<one sentence describing what a test should assert>"
}}

Rules:
- acceptance_criteria: 1–4 short, verifiable statements
- keywords: 3–8 lowercase tokens used to locate relevant code (function names, \
variable names, module names)
- evidence_strategy: choose "unit_test" unless the requirement is purely \
structural (then "static_analysis") or needs both
- test_hint: be concrete, e.g. "assert token.expires_in == 900"
- Output must be valid JSON parseable by json.loads()
"""

# ---------------------------------------------------------------------------
# Stopwords excluded from fallback keyword extraction
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would could should may might must shall can cannot able "
    "and or not but if in on at to of for with as by from that this it "
    "all any each every no nor so yet both either neither than then "
    "when where which who whom what how also only just never always "
    "after before during until while since "
    "user users system service api".split()
)

_MIN_KEYWORD_LEN = 4


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def generate_contract(
    req: Requirement,
    client=None,  # WatsonxClient | None — kept as Any to avoid import cycle
) -> IntentContract:
    """
    Generate an IntentContract for *req*.

    If *client* is None and credentials are not configured, or if any step
    of the LLM pipeline fails, returns fallback_contract(req) instead.

    The fallback contract has evidence_strategy=unknown and keywords derived
    from the requirement text by simple tokenisation.
    """
    # Use provided client or try to get the shared singleton
    if client is None:
        if not config.credentials_available():
            logger.info(
                "contract_generator: no credentials — using fallback for %s", req.id
            )
            return fallback_contract(req)
        try:
            from llm_client import get_client
            client = get_client()
        except Exception as exc:
            logger.warning("contract_generator: cannot get LLM client: %s", exc)
            return fallback_contract(req)

    prompt = _build_prompt(req)
    logger.info("contract_generator: calling LLM for %s", req.id)

    try:
        raw_json = client.generate_json(prompt)
    except Exception as exc:
        logger.warning("contract_generator: LLM call failed for %s: %s", req.id, exc)
        return fallback_contract(req)

    if not raw_json:
        logger.warning("contract_generator: empty JSON response for %s", req.id)
        return fallback_contract(req)

    # Normalise: ensure requirement_id matches what we sent
    raw_json["requirement_id"] = req.id

    try:
        contract = IntentContract.model_validate(raw_json)
        # Ensure at least some keywords were returned
        if not contract.keywords:
            contract = contract.model_copy(
                update={"keywords": _extract_keywords(req.raw_text)}
            )
        logger.info(
            "contract_generator: contract validated for %s (keywords=%s)",
            req.id, contract.keywords[:5],
        )
        return contract
    except (ValidationError, Exception) as exc:
        logger.warning(
            "contract_generator: Pydantic validation failed for %s: %s", req.id, exc
        )
        return fallback_contract(req)


def fallback_contract(req: Requirement) -> IntentContract:
    """
    Build a minimal IntentContract from the requirement text alone (no LLM).

    Used when credentials are missing or the LLM pipeline fails.  The
    pipeline treats contracts with evidence_strategy=unknown as UNPROVEN.
    """
    keywords = _extract_keywords(req.raw_text)
    return IntentContract(
        requirement_id=req.id,
        summary=req.raw_text[:60].rstrip() + ("…" if len(req.raw_text) > 60 else ""),
        acceptance_criteria=[req.raw_text],
        evidence_strategy=EvidenceStrategy.unknown,
        keywords=keywords,
        test_hint="",
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_prompt(req: Requirement) -> str:
    return _CONTRACT_PROMPT.format(req_id=req.id, req_text=req.raw_text)


def _extract_keywords(text: str) -> List[str]:
    """
    Extract meaningful search tokens from *text* using simple rules:
    - Lowercase, split on non-alphanumeric
    - Remove stopwords and very short words
    - Deduplicate while preserving order
    - Return up to 8 tokens
    """
    tokens = re.split(r"[^a-zA-Z0-9]+", text.lower())
    seen: dict[str, None] = {}
    for token in tokens:
        if (
            token
            and len(token) >= _MIN_KEYWORD_LEN
            and token not in _STOPWORDS
            and token not in seen
        ):
            seen[token] = None
    return list(seen.keys())[:8]
