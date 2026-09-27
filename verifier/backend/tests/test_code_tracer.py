"""
tests/test_code_tracer.py — Unit tests for code_tracer.py.

All tests use plain tmp_path fixtures.  No network, no git, no LLM, no credentials.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from code_tracer import (
    MAX_REGIONS,
    TOP_FILES,
    _extract_regions,
    _score_file,
    _score_files,
    trace,
)
from models.code_region import CodeRegion
from models.intent_contract import EvidenceStrategy, IntentContract

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_contract(req_id: str, keywords: List[str]) -> IntentContract:
    return IntentContract(
        requirement_id=req_id,
        summary="test contract",
        acceptance_criteria=["criterion"],
        evidence_strategy=EvidenceStrategy.unit_test,
        keywords=keywords,
        test_hint="",
    )


def make_index(entries: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return entries


# ---------------------------------------------------------------------------
# _score_file
# ---------------------------------------------------------------------------

class TestScoreFile:
    def test_no_keywords_scores_zero(self):
        assert _score_file("auth/tokens.py", ["generate_reset_token"], []) == 0

    def test_keyword_in_path_scores_two(self):
        score = _score_file("auth/tokens.py", [], ["token"])
        assert score == 2

    def test_keyword_in_symbol_scores_one(self):
        score = _score_file("auth/utils.py", ["generate_token"], ["token"])
        assert score == 1  # symbol hit only (path doesn't match)

    def test_keyword_in_both_path_and_symbol(self):
        # "token" in "tokens.py" (path hit=2) and "generate_token" (symbol hit=1)
        score = _score_file("auth/tokens.py", ["generate_token", "Token"], ["token"])
        assert score == 3

    def test_no_match_scores_zero(self):
        score = _score_file("products/routes.py", ["get_product"], ["token"])
        assert score == 0

    def test_multiple_keywords_accumulate(self):
        score = _score_file(
            "auth/password_reset.py",
            ["reset_password", "generate_token"],
            ["password", "reset", "token"],
        )
        # "password" → path hit (2) + symbol hit (1)
        # "reset" → path hit (2) + symbol hit (1)
        # "token" → no path hit, symbol hit (1)
        assert score == 7

    def test_case_insensitive(self):
        score = _score_file("auth/Tokens.py", ["GenerateToken"], ["token"])
        assert score > 0


# ---------------------------------------------------------------------------
# _score_files
# ---------------------------------------------------------------------------

class TestScoreFiles:
    def test_returns_sorted_descending(self):
        index = {
            "auth/tokens.py": ["generate_reset_token"],
            "products/routes.py": ["get_product"],
            "auth/users.py": ["UserService"],
        }
        results = _score_files(index, ["token"])
        # Only token-related files should score > 0
        assert results[0][0] == "auth/tokens.py"
        assert results[0][1] > 0

    def test_zero_score_files_excluded(self):
        index = {"unrelated.py": ["some_func"]}
        results = _score_files(index, ["token"])
        assert results == []

    def test_empty_index_returns_empty(self):
        assert _score_files({}, ["token"]) == []

    def test_all_files_returned_if_all_match(self):
        index = {
            "auth/token_store.py": ["store_token"],
            "auth/token_verify.py": ["verify_token"],
        }
        results = _score_files(index, ["token"])
        assert len(results) == 2


# ---------------------------------------------------------------------------
# _extract_regions (pure filesystem — no git)
# ---------------------------------------------------------------------------

class TestExtractRegions:
    def test_extracts_matching_function(self, tmp_path):
        f = tmp_path / "tokens.py"
        f.write_text(textwrap.dedent("""\
            EXPIRY = 900

            def generate_reset_token(user_id):
                return {"expires_in": EXPIRY}

            def unrelated_function():
                return None
        """))
        regions = _extract_regions(f, "tokens.py", ["token", "reset"], base_score=3)
        names = [r.file for r in regions]
        assert "tokens.py" in names
        # The matching function region should be present
        snippets = " ".join(r.snippet for r in regions)
        assert "generate_reset_token" in snippets

    def test_nonexistent_file_returns_empty(self, tmp_path):
        regions = _extract_regions(
            tmp_path / "no_such.py", "no_such.py", ["token"], base_score=1
        )
        assert regions == []

    def test_bad_syntax_returns_whole_file_region(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n    # unclosed\n")
        regions = _extract_regions(f, "bad.py", ["broken"], base_score=2)
        assert len(regions) == 1
        assert regions[0].line_start == 1

    def test_empty_file_returns_whole_file_region(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        regions = _extract_regions(f, "empty.py", ["token"], base_score=1)
        # Empty file: no AST nodes → whole-file region
        assert len(regions) == 1
        assert regions[0].snippet == ""

    def test_score_includes_base_score(self, tmp_path):
        f = tmp_path / "tokens.py"
        f.write_text("def get_token(): return 'x'\n")
        regions = _extract_regions(f, "tokens.py", ["token"], base_score=5)
        assert all(r.score >= 5 for r in regions)

    def test_snippet_capped_at_30_lines(self, tmp_path):
        long_src = "def big_func():\n" + "    x = 1\n" * 50
        f = tmp_path / "big.py"
        f.write_text(long_src)
        regions = _extract_regions(f, "big.py", ["func"], base_score=1)
        for r in regions:
            line_count = r.snippet.count("\n") + 1
            assert line_count <= 32  # 30 lines + possible truncation marker


# ---------------------------------------------------------------------------
# trace (integration — uses real files in tmp_path)
# ---------------------------------------------------------------------------

class TestTrace:
    def _make_repo(self, tmp_path: Path) -> tuple:
        """Create a minimal repo tree and a corresponding FileIndex."""
        (tmp_path / "auth").mkdir()
        (tmp_path / "auth" / "tokens.py").write_text(textwrap.dedent("""\
            EXPIRY_SECONDS = 900

            def generate_reset_token(user_id: int) -> dict:
                return {"user_id": user_id, "expires_in": EXPIRY_SECONDS}

            def verify_token(token: dict) -> bool:
                return True
        """))
        (tmp_path / "auth" / "users.py").write_text(textwrap.dedent("""\
            class UserService:
                def hash_password(self, pw: str) -> str:
                    return pw
        """))
        (tmp_path / "products").mkdir()
        (tmp_path / "products" / "routes.py").write_text(textwrap.dedent("""\
            def get_product(pid):
                return {"id": pid, "price": 9.99}

            def create_product(name, price):
                return {"name": name, "price": price}
        """))
        file_index = {
            "auth/tokens.py": ["generate_reset_token", "verify_token"],
            "auth/users.py": ["UserService"],
            "products/routes.py": ["get_product", "create_product"],
        }
        return file_index

    def test_returns_list_of_code_regions(self, tmp_path):
        index = self._make_repo(tmp_path)
        contract = make_contract("R01", ["token", "reset", "expire"])
        regions = trace(contract, index, tmp_path)
        assert isinstance(regions, list)
        assert all(isinstance(r, CodeRegion) for r in regions)

    def test_token_keywords_match_tokens_file(self, tmp_path):
        index = self._make_repo(tmp_path)
        contract = make_contract("R01", ["token", "reset", "expire"])
        regions = trace(contract, index, tmp_path)
        assert len(regions) > 0
        files = [r.file for r in regions]
        assert any("tokens" in f for f in files)

    def test_irrelevant_keywords_return_empty(self, tmp_path):
        index = self._make_repo(tmp_path)
        contract = make_contract("R01", ["xyz_nonexistent_keyword_abc"])
        regions = trace(contract, index, tmp_path)
        assert regions == []

    def test_no_keywords_returns_empty(self, tmp_path):
        index = self._make_repo(tmp_path)
        contract = make_contract("R01", [])
        regions = trace(contract, index, tmp_path)
        assert regions == []

    def test_empty_index_returns_empty(self, tmp_path):
        contract = make_contract("R01", ["token"])
        regions = trace(contract, {}, tmp_path)
        assert regions == []

    def test_results_capped_at_max_regions(self, tmp_path):
        # Create many matching files
        for i in range(10):
            f = tmp_path / f"token_module_{i}.py"
            f.write_text(f"def get_token_{i}(): return {i}\n")
        index = {f"token_module_{i}.py": [f"get_token_{i}"] for i in range(10)}
        contract = make_contract("R01", ["token"])
        regions = trace(contract, index, tmp_path)
        assert len(regions) <= MAX_REGIONS

    def test_regions_sorted_by_score_descending(self, tmp_path):
        index = self._make_repo(tmp_path)
        contract = make_contract("R01", ["token", "reset"])
        regions = trace(contract, index, tmp_path)
        scores = [r.score for r in regions]
        assert scores == sorted(scores, reverse=True)

    def test_snippet_is_non_empty_string(self, tmp_path):
        index = self._make_repo(tmp_path)
        contract = make_contract("R01", ["token"])
        regions = trace(contract, index, tmp_path)
        for r in regions:
            assert isinstance(r.snippet, str)

    def test_product_keywords_match_products_file(self, tmp_path):
        index = self._make_repo(tmp_path)
        contract = make_contract("R04", ["product", "price", "create"])
        regions = trace(contract, index, tmp_path)
        assert len(regions) > 0
        files = [r.file for r in regions]
        assert any("products" in f for f in files)

    def test_line_numbers_are_valid(self, tmp_path):
        index = self._make_repo(tmp_path)
        contract = make_contract("R01", ["token"])
        regions = trace(contract, index, tmp_path)
        for r in regions:
            assert r.line_start >= 1
            assert r.line_end >= r.line_start
