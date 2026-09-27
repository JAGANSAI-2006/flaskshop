"""
models/code_region.py — Pydantic model for a single traced code region.

Produced by code_tracer.py and consumed by test_generator.py and the
Report Builder.  Each instance represents a contiguous block of source
lines that the Code Tracer believes is relevant to a requirement.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CodeRegion(BaseModel):
    """A contiguous block of source lines relevant to a requirement."""

    file: str = Field(
        ..., description="Relative path from repo root, e.g. 'auth/tokens.py'"
    )
    line_start: int = Field(..., description="1-based line number of the first line")
    line_end: int = Field(..., description="1-based line number of the last line (inclusive)")
    snippet: str = Field(..., description="Raw source text of the region (up to 30 lines)")
    score: int = Field(
        default=0,
        description="Keyword hit count used for ranking; higher = more relevant",
    )
