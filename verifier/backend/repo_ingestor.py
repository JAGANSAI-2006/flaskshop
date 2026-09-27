"""
repo_ingestor.py — Clone a public Git repository into a per-job temp directory
and build a lightweight symbol index from its Python source files.

Public API
----------
clone_repo(repo_url, job_id)  -> Path          # clones; returns repo root path
build_file_index(repo_path)   -> FileIndex      # walks .py files, extracts names
cleanup_repo(job_id)          -> None           # deletes the job temp directory

FileIndex = dict[str, list[str]]
  key   : path relative to repo root  (e.g. "auth/tokens.py")
  value : list of top-level function and class names found by ast
"""

from __future__ import annotations

import ast
import logging
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

# Type alias kept here for use by other modules
FileIndex = Dict[str, List[str]]

# ---------------------------------------------------------------------------
# Git executable resolution
# ---------------------------------------------------------------------------

def _find_git() -> Optional[str]:
    """Return the absolute path to the git executable, or None if not found."""
    import shutil as _shutil
    found = _shutil.which("git")
    if found:
        return found
    # Common Windows install paths not always on PATH
    candidates = [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


_GIT_EXE: Optional[str] = _find_git()


def git_available() -> bool:
    """Return True if git is available on this system."""
    return _GIT_EXE is not None


def _git_cmd(*args: str) -> list:
    """Build a git command list using the resolved git executable."""
    if _GIT_EXE is None:
        raise RuntimeError(
            "git is not installed or not on PATH. "
            "Install Git and ensure 'git' is accessible from the command line."
        )
    return [_GIT_EXE, *args]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def new_job_id() -> str:
    """Generate a short random job identifier."""
    return uuid.uuid4().hex[:12]


def _job_dir(job_id: str) -> Path:
    """Return the per-job directory (not the repo root inside it)."""
    return config.TEMP_BASE_DIR / job_id


def repo_path_for(job_id: str) -> Path:
    """Return the path where the repo is (or will be) cloned."""
    return _job_dir(job_id) / "repo"


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------

def clone_repo(repo_url: str, job_id: str) -> Path:
    """
    Clone *repo_url* (shallow, depth=1) into TEMP_BASE_DIR/<job_id>/repo.

    Returns the repo root Path on success.
    Raises ValueError  for obviously invalid URLs (no scheme / no host).
    Raises RuntimeError if git exits non-zero (private repo, 404, network error).
    """
    # Validate remote URLs; allow local filesystem paths.
    if (
        repo_url.startswith("https://")
        or repo_url.startswith("http://")
        or repo_url.startswith("git@")
    ):
        _validate_url(repo_url)
    elif not Path(repo_url).exists() and not (
        Path(repo_url).is_absolute() or len(Path(repo_url).parts) > 1
    ):
        raise ValueError(
            f"repo_url must be a valid remote URL or local path: {repo_url!r}"
        )
    dest = repo_path_for(job_id)
    dest.parent.mkdir(parents=True, exist_ok=True)

    cmd = _git_cmd(
        "clone",
        "--depth", "1",
        "--single-branch",
        "--no-tags",
        repo_url,
        str(dest),
    )
    logger.info("Cloning %s → %s", repo_url, dest)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.GIT_CLONE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"git clone timed out after {config.GIT_CLONE_TIMEOUT}s for {repo_url}"
        ) from exc

    if result.returncode != 0:
        # Surface the git error message but cap length so it doesn't flood logs
        detail = (result.stderr or result.stdout or "").strip()[:400]
        raise RuntimeError(
            f"git clone failed (exit {result.returncode}): {detail}"
        )

    logger.info("Clone complete: %s", dest)
    return dest


def _validate_url(url: str) -> None:
    """Raise ValueError for URLs that cannot possibly be a remote git repo."""
    url = url.strip()
    if not url:
        raise ValueError("repo_url must not be empty")
    if not (url.startswith("https://") or url.startswith("http://") or url.startswith("git@")):
        raise ValueError(
            f"repo_url must start with https://, http://, or git@ — got: {url!r}"
        )


# ---------------------------------------------------------------------------
# File index
# ---------------------------------------------------------------------------

def build_file_index(repo_path: Path) -> FileIndex:
    """
    Walk *repo_path* and return a FileIndex mapping each .py file
    (relative path) to the list of top-level function and class names
    extracted via the stdlib `ast` module.

    Files that fail to parse are skipped with a warning (not an error).
    The total size of .py files is checked against MAX_REPO_SIZE_MB.
    """
    repo_path = Path(repo_path)
    if not repo_path.is_dir():
        raise ValueError(f"repo_path does not exist or is not a directory: {repo_path}")

    py_files = sorted(repo_path.rglob("*.py"))

    # Safety: reject repos whose Python source is suspiciously large
    total_bytes = sum(f.stat().st_size for f in py_files if f.is_file())
    limit_bytes = config.MAX_REPO_SIZE_MB * 1024 * 1024
    if total_bytes > limit_bytes:
        raise RuntimeError(
            f"Repository Python source exceeds {config.MAX_REPO_SIZE_MB} MB "
            f"({total_bytes / 1024 / 1024:.1f} MB). Refusing to index."
        )

    index: FileIndex = {}
    for py_file in py_files:
        rel = py_file.relative_to(repo_path).as_posix()
        names = _extract_top_level_names(py_file)
        index[rel] = names

    logger.info("File index built: %d .py files in %s", len(index), repo_path)
    return index


def _extract_top_level_names(py_file: Path) -> List[str]:
    """Return top-level function and class names from a single .py file."""
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError as exc:
        logger.warning("AST parse failed for %s: %s", py_file, exc)
        return []
    except Exception as exc:
        logger.warning("Could not read %s: %s", py_file, exc)
        return []

    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Only top-level (direct children of the Module node)
            names.append(node.name)
    return names


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_repo(job_id: str) -> None:
    """Delete the entire per-job temp directory (repo + any generated tests)."""
    job_dir = _job_dir(job_id)
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.info("Cleaned up job directory: %s", job_dir)
