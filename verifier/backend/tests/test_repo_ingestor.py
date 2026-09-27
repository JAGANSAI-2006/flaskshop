"""
tests/test_repo_ingestor.py — Tests for repo_ingestor.py.

Clone tests (marked with `requires_git`) are skipped automatically when git is
not installed on the host machine.  All build_file_index and AST tests use a
plain directory fixture and need no git at all.

Network tests (marked @pytest.mark.network) clone a real GitHub repo; skipped
unless --run-network is passed.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

# Ensure backend package root is importable regardless of pytest invocation dir.
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import repo_ingestor
from repo_ingestor import (
    FileIndex,
    _extract_top_level_names,
    _validate_url,
    build_file_index,
    cleanup_repo,
    clone_repo,
    git_available,
    new_job_id,
    repo_path_for,
)


# ---------------------------------------------------------------------------
# pytest option to enable real-network tests
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    try:
        parser.addoption(
            "--run-network",
            action="store_true",
            default=False,
            help="Run tests that make real network (git clone) calls",
        )
    except ValueError:
        pass  # option already registered by another conftest


def pytest_configure(config_obj):
    try:
        config_obj.addinivalue_line(
            "markers", "network: marks tests that require real network access"
        )
        config_obj.addinivalue_line(
            "markers", "requires_git: marks tests that require git on PATH"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shared skip marker
# ---------------------------------------------------------------------------

requires_git = pytest.mark.skipif(
    not git_available(),
    reason="git is not installed or not on PATH — skipping clone tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def py_tree(tmp_path_factory) -> Path:
    """
    Plain directory tree (no git) used by build_file_index tests.

    Structure:
        <tmp>/py_tree/
            auth/
                __init__.py
                tokens.py          — generate_reset_token, verify_token
                users.py           — UserService class
            products/
                __init__.py
                routes.py          — get_product, create_product
            app.py                 — create_app
            README.md              — non-Python (must not appear in index)
            bad_syntax.py          — intentionally broken Python
    """
    root = tmp_path_factory.mktemp("py_tree")

    (root / "auth").mkdir()
    (root / "auth" / "__init__.py").write_text("")
    (root / "auth" / "tokens.py").write_text(textwrap.dedent("""\
        import time

        EXPIRY_SECONDS = 900  # 15 minutes

        def generate_reset_token(user_id: int) -> dict:
            return {"user_id": user_id, "expires_in": EXPIRY_SECONDS, "created_at": time.time()}

        def verify_token(token: dict) -> bool:
            return time.time() - token["created_at"] < token["expires_in"]
    """))
    (root / "auth" / "users.py").write_text(textwrap.dedent("""\
        class UserService:
            def hash_password(self, password: str) -> str:
                return password  # stub
    """))

    (root / "products").mkdir()
    (root / "products" / "__init__.py").write_text("")
    (root / "products" / "routes.py").write_text(textwrap.dedent("""\
        def get_product(product_id: int):
            return {"id": product_id, "price": 9.99}

        def create_product(name: str, price: float):
            if price < 0:
                raise ValueError("Price must not be negative")
            return {"name": name, "price": price}
    """))

    (root / "app.py").write_text(textwrap.dedent("""\
        def create_app():
            return object()
    """))
    (root / "README.md").write_text("# Demo project\n")
    (root / "bad_syntax.py").write_text("def broken(\n    # unclosed paren\n")

    return root


@pytest.fixture()
def job_id() -> str:
    return new_job_id()


@pytest.fixture(autouse=True)
def override_temp_dir(tmp_path, monkeypatch):
    """Redirect TEMP_BASE_DIR into pytest's tmp_path so tests are self-contained."""
    monkeypatch.setattr(config, "TEMP_BASE_DIR", tmp_path / "req_verifier")


# ---------------------------------------------------------------------------
# _validate_url
# ---------------------------------------------------------------------------

class TestValidateUrl:
    def test_valid_https(self):
        _validate_url("https://github.com/owner/repo")

    def test_valid_http(self):
        _validate_url("http://github.com/owner/repo")

    def test_valid_git_at(self):
        _validate_url("git@github.com:owner/repo.git")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_url("")

    def test_whitespace_raises(self):
        with pytest.raises(ValueError):
            _validate_url("   ")

    def test_missing_scheme_raises(self):
        with pytest.raises(ValueError, match="must start with"):
            _validate_url("github.com/owner/repo")

    def test_ftp_scheme_raises(self):
        with pytest.raises(ValueError, match="must start with"):
            _validate_url("ftp://github.com/owner/repo")


# ---------------------------------------------------------------------------
# new_job_id
# ---------------------------------------------------------------------------

class TestNewJobId:
    def test_returns_string(self):
        assert isinstance(new_job_id(), str)

    def test_length_12(self):
        assert len(new_job_id()) == 12

    def test_unique(self):
        ids = {new_job_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# clone_repo — only run when git is available
# ---------------------------------------------------------------------------

class TestCloneRepo:
    @requires_git
    def test_clone_local_repo(self, py_tree, job_id):
        import subprocess
        # Initialise a throwaway git repo from py_tree so clone_repo can use it
        git = repo_ingestor._GIT_EXE
        tmp = py_tree.parent / f"gitrepo_{job_id}"
        shutil.copytree(py_tree, tmp)
        subprocess.run([git, "init"], cwd=tmp, capture_output=True, check=True)
        subprocess.run([git, "config", "user.email", "t@t.com"], cwd=tmp, capture_output=True, check=True)
        subprocess.run([git, "config", "user.name", "T"], cwd=tmp, capture_output=True, check=True)
        subprocess.run([git, "add", "-A"], cwd=tmp, capture_output=True, check=True)
        subprocess.run([git, "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)

        dest = clone_repo(str(tmp), job_id)
        assert dest.is_dir()
        assert (dest / "app.py").exists()
        cleanup_repo(job_id)
        shutil.rmtree(tmp, ignore_errors=True)

    @requires_git
    def test_clone_creates_correct_path(self, py_tree, job_id):
        import subprocess
        git = repo_ingestor._GIT_EXE
        tmp = py_tree.parent / f"gitrepo2_{job_id}"
        shutil.copytree(py_tree, tmp)
        subprocess.run([git, "init"], cwd=tmp, capture_output=True, check=True)
        subprocess.run([git, "config", "user.email", "t@t.com"], cwd=tmp, capture_output=True, check=True)
        subprocess.run([git, "config", "user.name", "T"], cwd=tmp, capture_output=True, check=True)
        subprocess.run([git, "add", "-A"], cwd=tmp, capture_output=True, check=True)
        subprocess.run([git, "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)

        dest = clone_repo(str(tmp), job_id)
        expected = repo_path_for(job_id)
        assert dest == expected
        cleanup_repo(job_id)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_clone_invalid_url_raises_value_error(self, job_id):
        with pytest.raises(ValueError):
            clone_repo("not-a-url", job_id)

    @requires_git
    def test_clone_nonexistent_path_raises_runtime_error(self, job_id, tmp_path):
        with pytest.raises(RuntimeError, match="git clone failed"):
            clone_repo(str(tmp_path / "nonexistent_repo_xyz"), job_id)

    def test_clone_no_git_raises_runtime_error(self, job_id, monkeypatch):
        """When git is not available, clone_repo raises RuntimeError (not FileNotFoundError)."""
        monkeypatch.setattr(repo_ingestor, "_GIT_EXE", None)
        with pytest.raises(RuntimeError, match="git is not installed"):
            clone_repo("https://github.com/owner/repo", job_id)


# ---------------------------------------------------------------------------
# build_file_index  (no git needed — uses plain py_tree fixture)
# ---------------------------------------------------------------------------

class TestBuildFileIndex:
    def test_returns_dict(self, py_tree):
        index = build_file_index(py_tree)
        assert isinstance(index, dict)

    def test_only_py_files(self, py_tree):
        index = build_file_index(py_tree)
        for key in index:
            assert key.endswith(".py"), f"Non-py key in index: {key}"

    def test_readme_not_in_index(self, py_tree):
        index = build_file_index(py_tree)
        assert "README.md" not in index

    def test_app_py_in_index(self, py_tree):
        index = build_file_index(py_tree)
        assert "app.py" in index

    def test_tokens_py_in_index(self, py_tree):
        index = build_file_index(py_tree)
        assert "auth/tokens.py" in index

    def test_extract_function_names_tokens(self, py_tree):
        index = build_file_index(py_tree)
        names = index["auth/tokens.py"]
        assert "generate_reset_token" in names
        assert "verify_token" in names

    def test_extract_class_name_users(self, py_tree):
        index = build_file_index(py_tree)
        names = index["auth/users.py"]
        assert "UserService" in names

    def test_extract_functions_products(self, py_tree):
        index = build_file_index(py_tree)
        names = index["products/routes.py"]
        assert "get_product" in names
        assert "create_product" in names

    def test_bad_syntax_file_skipped_gracefully(self, py_tree):
        index = build_file_index(py_tree)
        assert "bad_syntax.py" in index
        assert index["bad_syntax.py"] == []

    def test_nonexistent_path_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            build_file_index(tmp_path / "no_such_dir")

    def test_size_limit_enforced(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MAX_REPO_SIZE_MB", 0)
        (tmp_path / "tiny.py").write_text("x = 1\n")
        with pytest.raises(RuntimeError, match="exceeds"):
            build_file_index(tmp_path)


# ---------------------------------------------------------------------------
# _extract_top_level_names
# ---------------------------------------------------------------------------

class TestExtractTopLevelNames:
    def test_extracts_function(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("def foo(): pass\ndef bar(): pass\n")
        assert _extract_top_level_names(f) == ["foo", "bar"]

    def test_extracts_class(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("class MyClass:\n    def method(self): pass\n")
        names = _extract_top_level_names(f)
        assert "MyClass" in names

    def test_async_function(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("async def fetch(): pass\n")
        assert "fetch" in _extract_top_level_names(f)

    def test_bad_syntax_returns_empty(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n")
        assert _extract_top_level_names(f) == []

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        assert _extract_top_level_names(f) == []


# ---------------------------------------------------------------------------
# cleanup_repo
# ---------------------------------------------------------------------------

class TestCleanupRepo:
    def test_cleanup_removes_directory(self, py_tree, job_id):
        # Manually create the job dir structure (no clone needed)
        dest = repo_path_for(job_id)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "placeholder.py").write_text("x = 1\n")
        assert dest.exists()
        cleanup_repo(job_id)
        assert not dest.parent.exists()

    def test_cleanup_nonexistent_job_is_safe(self, job_id):
        cleanup_repo(job_id)  # must not raise


# ---------------------------------------------------------------------------
# git_available helper
# ---------------------------------------------------------------------------

def test_git_available_returns_bool():
    result = git_available()
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Network test (skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
@requires_git
def test_clone_real_github_repo(request, job_id):
    if not request.config.getoption("--run-network", default=False):
        pytest.skip("Pass --run-network to run this test")

    url = "https://github.com/pallets/flask"
    dest = clone_repo(url, job_id)
    try:
        assert dest.is_dir()
        index = build_file_index(dest)
        assert len(index) > 0
        assert any("flask" in k.lower() for k in index)
    finally:
        cleanup_repo(job_id)
