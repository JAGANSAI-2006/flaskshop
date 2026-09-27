"""
requirement_parser.py — Convert raw requirements text into a list of
Requirement objects using the existing Pydantic model.

Handles the common formatting patterns found in real requirements documents:
  - Numbered lists:  "1. Passwords must be hashed."  "1) ..."
  - Bullet lists:    "- Passwords must be hashed."  "* ..."  "+ ..."
  - Plain lines:     "Passwords must be hashed."
  - Markdown headers and blank lines are skipped.

Each non-empty line that survives stripping becomes one Requirement.
IDs are assigned sequentially: R01, R02, … R99, R100 …

Public API
----------
parse_requirements(text: str) -> list[Requirement]
"""

from __future__ import annotations

import re
from typing import List

from models.intent_contract import Requirement

# Patterns stripped from the start of a line before treating it as requirement text.
# Order matters: try the most specific patterns first.
# Note: markdown header lines starting with '#' are skipped entirely before
# reaching _strip_markers, so no header pattern is needed here.
_STRIP_PATTERNS: list[re.Pattern[str]] = [
    # Numbered: "1.", "12.", "1)", "12)"
    re.compile(r"^\d+[.)]\s+"),
    # Bullets: "- ", "* ", "+ ", "• "
    re.compile(r"^[-*+\u2022]\s+"),
]

# Lines that should be skipped entirely even after stripping (blank / separator).
_SKIP_PATTERN = re.compile(r"^[-=_*#\s]{0,5}$")


def parse_requirements(text: str) -> List[Requirement]:
    """
    Parse *text* into an ordered list of Requirement objects.

    - Lines that are blank or contain only separator characters are skipped.
    - Lines that are markdown section headers (start with '#') are skipped.
    - Leading numbering and bullet markers are removed from requirement lines.
    - Trailing whitespace is stripped.
    - Empty result after stripping → line is skipped.
    - IDs are assigned as zero-padded strings: R01, R02 … R09, R10, R11 …

    Returns an empty list for empty or whitespace-only input.
    """
    if not text or not text.strip():
        return []

    requirements: List[Requirement] = []
    seq = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()

        # Skip blank / separator lines
        if not line or _SKIP_PATTERN.match(line):
            continue

        # Skip markdown section headers BEFORE stripping markers
        if line.startswith("#"):
            continue

        # Strip leading markers
        cleaned = _strip_markers(line)

        # Skip if nothing is left after stripping (e.g. a lone "1.")
        if not cleaned:
            continue

        seq += 1
        req_id = f"R{seq:02d}"
        requirements.append(Requirement(id=req_id, raw_text=cleaned))

    return requirements


def _strip_markers(line: str) -> str:
    """Remove a single leading numbering or bullet marker from *line*."""
    for pattern in _STRIP_PATTERNS:
        m = pattern.match(line)
        if m:
            return line[m.end():].strip()
    return line
