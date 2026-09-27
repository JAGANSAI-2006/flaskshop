"""
smoke_test.py — Sub-Task 2 verification script.

Tests:
  1. Backend imports cleanly (config, models, main).
  2. FastAPI /health endpoint returns HTTP 200 with expected fields.
  3. (Optional) Single watsonx.ai generate() call if credentials are set.

Run from the backend/ directory:
    python smoke_test.py

Exit codes:
  0 — all required tests passed (optional LLM test skipped if no creds)
  1 — one or more required tests failed
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import json

BACKEND_PORT = 8765   # Use a non-standard port so it doesn't clash with dev server
BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"
RESULTS: list[tuple[str, bool, str]] = []   # (name, passed, detail)


def record(name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append((name, passed, detail))


# ── Test 1: imports ──────────────────────────────────────────────────────────

def test_imports() -> None:
    print("\n── Test 1: Module imports ──")
    try:
        import config  # noqa: F401
        record("import config", True)
    except Exception as exc:
        record("import config", False, str(exc))

    try:
        from models.intent_contract import IntentContract, Requirement, RequirementResult  # noqa: F401
        record("import models.intent_contract", True)
    except Exception as exc:
        record("import models.intent_contract", False, str(exc))

    try:
        import main  # noqa: F401
        record("import main (FastAPI app)", True)
    except Exception as exc:
        record("import main (FastAPI app)", False, str(exc))


# ── Test 2: /health endpoint ─────────────────────────────────────────────────

def test_health_endpoint() -> None:
    print("\n── Test 2: /health endpoint ──")

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    # Wait for the server to start (up to 10 seconds)
    started = False
    for _ in range(20):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(f"{BASE_URL}/health", timeout=2)
            started = True
            break
        except Exception:
            pass

    if not started:
        proc.terminate()
        record("server starts", False, "Server did not respond within 10 seconds")
        return

    record("server starts", True)

    # Check /health response
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=5) as resp:
            status_code = resp.getcode()
            body = json.loads(resp.read().decode())

        record("/health returns 200", status_code == 200, f"got {status_code}")
        record('/health.status == "ok"', body.get("status") == "ok", str(body.get("status")))
        record("/health.model field present", "model" in body, str(body))
        record(
            "/health.model is granite-3-3-8b-instruct",
            "granite-3-3-8b-instruct" in body.get("model", ""),
            body.get("model", ""),
        )
        creds_reported = body.get("watsonx_credentials_configured", None)
        record(
            "/health.watsonx_credentials_configured field present",
            creds_reported is not None,
            str(creds_reported),
        )
        print(f"  [INFO] watsonx credentials configured: {creds_reported}")
    except Exception as exc:
        record("/health response valid", False, str(exc))
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ── Test 3: LLM call (optional) ──────────────────────────────────────────────

def test_llm_call() -> None:
    print("\n── Test 3: watsonx.ai LLM call (optional — skipped if no credentials) ──")
    try:
        import config as cfg
        if not cfg.credentials_available():
            print("  [SKIP] WATSONX_API_KEY / WATSONX_PROJECT_ID not set — skipping LLM test.")
            print("         To enable: copy backend/.env.example → backend/.env and fill in credentials.")
            return

        from llm_client import WatsonxClient
        client = WatsonxClient()
        response = client.generate("Reply with exactly the word: OK")
        passed = "ok" in response.lower() or len(response) > 0
        record("LLM generate() returns non-empty response", passed, repr(response[:120]))
    except Exception as exc:
        record("LLM generate() call", False, str(exc))


# ── Test 4: Pydantic model validation ────────────────────────────────────────

def test_pydantic_models() -> None:
    print("\n── Test 4: Pydantic model validation ──")
    try:
        from models.intent_contract import IntentContract, EvidenceStrategy

        contract = IntentContract(
            requirement_id="R01",
            summary="Token TTL validation",
            acceptance_criteria=["token.expires_in equals 900 seconds"],
            evidence_strategy=EvidenceStrategy.unit_test,
            keywords=["token", "reset", "expire", "900", "15"],
            test_hint="import token module, create token, assert TTL == 900",
        )
        record("IntentContract instantiation", True)
        record("IntentContract.requirement_id", contract.requirement_id == "R01")
        record(
            "IntentContract serialises to dict",
            isinstance(contract.model_dump(), dict),
        )
    except Exception as exc:
        record("IntentContract validation", False, str(exc))


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Sub-Task 2 — Backend + watsonx.ai Smoke Test")
    print("=" * 60)

    # Add backend dir to path so imports work
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    test_imports()
    test_pydantic_models()
    test_health_endpoint()
    test_llm_call()

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    total = len(RESULTS)
    print(f"  Results: {passed}/{total} passed, {failed} failed")

    required_failed = [name for name, ok, _ in RESULTS if not ok]
    if required_failed:
        print(f"\n  FAILED tests:")
        for name in required_failed:
            print(f"    ✗ {name}")
        sys.exit(1)
    else:
        print("\n  All required tests PASSED ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
