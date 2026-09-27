"""
config.py — centralised configuration loaded from environment variables / .env file.

All sensitive values are read from the environment. The .env file is loaded
automatically when present (useful for local development). Never put real
credentials in this file or in source control.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend directory (or its parent) if it exists.
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)

# ── Required watsonx.ai credentials ─────────────────────────────────────────

WATSONX_API_KEY: str = os.environ.get("WATSONX_API_KEY", "")
WATSONX_PROJECT_ID: str = os.environ.get("WATSONX_PROJECT_ID", "")
WATSONX_URL: str = os.environ.get(
    "WATSONX_URL", "https://us-south.ml.cloud.ibm.com"
)

# ── Model identifiers ────────────────────────────────────────────────────────

GRANITE_MODEL_ID: str = "ibm/granite-3-3-8b-instruct"

# ── Generation defaults ──────────────────────────────────────────────────────

GENERATION_MAX_NEW_TOKENS: int = 1024
GENERATION_TEMPERATURE: float = 0.0   # deterministic output preferred
GENERATION_DECODING_METHOD: str = "greedy"

# ── Application settings ─────────────────────────────────────────────────────

APP_TITLE: str = "Requirement-to-Code Verifier"
APP_VERSION: str = "0.1.0"

# ── Repo ingestion settings ──────────────────────────────────────────────────

# Base directory for per-job temporary clones.
# Each job gets its own sub-directory: TEMP_BASE_DIR / <job_id> / repo
TEMP_BASE_DIR: Path = Path(
    os.environ.get("TEMP_BASE_DIR", str(Path(tempfile.gettempdir()) / "req_verifier"))
)

# Safety limit: refuse to index repos whose .py files exceed this total size.
MAX_REPO_SIZE_MB: int = int(os.environ.get("MAX_REPO_SIZE_MB", "100"))

# git clone timeout in seconds
GIT_CLONE_TIMEOUT: int = int(os.environ.get("GIT_CLONE_TIMEOUT", "60"))

# Test execution timeout in seconds (per generated test file)
TEST_EXECUTION_TIMEOUT: int = int(os.environ.get("TEST_EXECUTION_TIMEOUT", "30"))

# ── Helpers ──────────────────────────────────────────────────────────────────


def credentials_available() -> bool:
    """Return True if all required watsonx.ai credentials are set."""
    return bool(WATSONX_API_KEY and WATSONX_PROJECT_ID and WATSONX_URL)


def assert_credentials() -> None:
    """Raise RuntimeError with a helpful message if credentials are missing."""
    missing = [
        name
        for name, val in [
            ("WATSONX_API_KEY", WATSONX_API_KEY),
            ("WATSONX_PROJECT_ID", WATSONX_PROJECT_ID),
            ("WATSONX_URL", WATSONX_URL),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy backend/.env.example to backend/.env and fill in your credentials."
        )
