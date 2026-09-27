"""
tests/test_requirement_parser.py — Unit tests for requirement_parser.py.

All tests are pure (no network, no filesystem beyond stdlib).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the backend package root is on sys.path when pytest is run from the
# project root or from the backend directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from requirement_parser import parse_requirements
from models.intent_contract import Requirement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ids(reqs: list[Requirement]) -> list[str]:
    return [r.id for r in reqs]


def texts(reqs: list[Requirement]) -> list[str]:
    return [r.raw_text for r in reqs]


# ---------------------------------------------------------------------------
# Empty / whitespace input
# ---------------------------------------------------------------------------

def test_empty_string_returns_empty_list():
    assert parse_requirements("") == []


def test_whitespace_only_returns_empty_list():
    assert parse_requirements("   \n\n\t  ") == []


def test_none_equivalent_empty():
    # Falsy empty string
    assert parse_requirements("") == []


# ---------------------------------------------------------------------------
# Numbered lists
# ---------------------------------------------------------------------------

def test_numbered_dot_format():
    text = (
        "1. Password reset tokens must expire after 15 minutes.\n"
        "2. User passwords must be stored as bcrypt hashes.\n"
        "3. A user must not place an order with an empty cart.\n"
    )
    reqs = parse_requirements(text)
    assert len(reqs) == 3
    assert ids(reqs) == ["R01", "R02", "R03"]
    assert reqs[0].raw_text == "Password reset tokens must expire after 15 minutes."
    assert reqs[1].raw_text == "User passwords must be stored as bcrypt hashes."
    assert reqs[2].raw_text == "A user must not place an order with an empty cart."


def test_numbered_paren_format():
    text = "1) First requirement.\n2) Second requirement.\n"
    reqs = parse_requirements(text)
    assert len(reqs) == 2
    assert reqs[0].raw_text == "First requirement."
    assert reqs[1].raw_text == "Second requirement."


def test_multi_digit_numbering():
    lines = "\n".join(f"{i}. Requirement number {i}." for i in range(1, 13))
    reqs = parse_requirements(lines)
    assert len(reqs) == 12
    assert ids(reqs) == [f"R{i:02d}" for i in range(1, 13)]


# ---------------------------------------------------------------------------
# Bullet lists
# ---------------------------------------------------------------------------

def test_dash_bullets():
    text = "- First\n- Second\n- Third\n"
    reqs = parse_requirements(text)
    assert texts(reqs) == ["First", "Second", "Third"]


def test_star_bullets():
    text = "* Alpha requirement.\n* Beta requirement.\n"
    reqs = parse_requirements(text)
    assert len(reqs) == 2
    assert reqs[0].raw_text == "Alpha requirement."


def test_plus_bullets():
    text = "+ Item one.\n+ Item two.\n"
    reqs = parse_requirements(text)
    assert len(reqs) == 2
    assert reqs[1].raw_text == "Item two."


def test_unicode_bullet():
    text = "\u2022 Unicode bullet one.\n\u2022 Unicode bullet two.\n"
    reqs = parse_requirements(text)
    assert len(reqs) == 2
    assert reqs[0].raw_text == "Unicode bullet one."


# ---------------------------------------------------------------------------
# Plain lines (no markers)
# ---------------------------------------------------------------------------

def test_plain_lines():
    text = "First plain requirement.\nSecond plain requirement.\n"
    reqs = parse_requirements(text)
    assert len(reqs) == 2
    assert reqs[0].raw_text == "First plain requirement."


def test_plain_lines_no_trailing_newline():
    text = "First.\nSecond."
    reqs = parse_requirements(text)
    assert len(reqs) == 2


# ---------------------------------------------------------------------------
# Blank-line and separator handling
# ---------------------------------------------------------------------------

def test_blank_lines_are_skipped():
    text = "1. First.\n\n\n2. Second.\n\n3. Third.\n"
    reqs = parse_requirements(text)
    assert len(reqs) == 3
    assert ids(reqs) == ["R01", "R02", "R03"]


def test_separator_lines_skipped():
    text = "1. First.\n---\n2. Second.\n===\n3. Third.\n"
    reqs = parse_requirements(text)
    assert len(reqs) == 3


def test_markdown_headers_skipped():
    text = "# Requirements\n\n1. First requirement.\n## Section\n2. Second requirement.\n"
    reqs = parse_requirements(text)
    assert len(reqs) == 2
    assert reqs[0].raw_text == "First requirement."
    assert reqs[1].raw_text == "Second requirement."


# ---------------------------------------------------------------------------
# Mixed formatting
# ---------------------------------------------------------------------------

def test_mixed_format_plain_and_numbered():
    text = (
        "1. First requirement.\n"
        "Second requirement without number.\n"
        "3. Third requirement.\n"
    )
    reqs = parse_requirements(text)
    assert len(reqs) == 3
    assert reqs[1].raw_text == "Second requirement without number."


# ---------------------------------------------------------------------------
# ID assignment
# ---------------------------------------------------------------------------

def test_ids_are_sequential_and_zero_padded():
    text = "\n".join(f"Requirement {i}." for i in range(1, 10))
    reqs = parse_requirements(text)
    assert ids(reqs) == [f"R0{i}" for i in range(1, 10)]


def test_ids_past_nine_not_zero_padded():
    text = "\n".join(f"Requirement {i}." for i in range(1, 12))
    reqs = parse_requirements(text)
    assert reqs[9].id == "R10"
    assert reqs[10].id == "R11"


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

def test_returns_requirement_objects():
    reqs = parse_requirements("1. A requirement.")
    assert len(reqs) == 1
    assert isinstance(reqs[0], Requirement)
    assert reqs[0].id == "R01"


# ---------------------------------------------------------------------------
# Demo FlaskShop requirements (integration smoke)
# ---------------------------------------------------------------------------

FLASKSHOP_REQUIREMENTS = """\
1. Password reset tokens must expire after 15 minutes.
2. User passwords must be stored as bcrypt hashes, never in plaintext.
3. A user must not be able to place an order with an empty cart.
4. Product prices must never be negative.
5. Admin endpoints must require an admin role; regular users must receive HTTP 403.
6. Failed login attempts must be limited to 5 per minute per IP before lockout.
7. The cart total must correctly apply percentage discount codes.
8. Deleting a product must also delete all associated cart items.
9. Users must receive an email confirmation after successful registration.
10. Order history must be paginated with a maximum of 20 orders per page.
11. Search results must be returned in descending order of relevance score.
12. All API endpoints must return JSON, never HTML error pages.
"""


def test_flaskshop_requirements_parse_to_12():
    reqs = parse_requirements(FLASKSHOP_REQUIREMENTS)
    assert len(reqs) == 12


def test_flaskshop_r01_text():
    reqs = parse_requirements(FLASKSHOP_REQUIREMENTS)
    assert reqs[0].id == "R01"
    assert "expire" in reqs[0].raw_text.lower()
    assert "15 minutes" in reqs[0].raw_text


def test_flaskshop_r12_text():
    reqs = parse_requirements(FLASKSHOP_REQUIREMENTS)
    assert reqs[11].id == "R12"
    assert "JSON" in reqs[11].raw_text
