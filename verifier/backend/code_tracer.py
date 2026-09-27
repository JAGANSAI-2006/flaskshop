"""
code_tracer.py — Map an IntentContract's keywords to relevant source regions
in a cloned repository.

No LLM calls, no network I/O.  Pure AST + keyword scoring over the FileIndex
produced by repo_ingestor.build_file_index().

Public API
----------
trace(contract, file_index, repo_path) -> list[CodeRegion]
    Returns up to MAX_REGIONS CodeRegion objects, highest-scoring first.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple

from models.code_region import CodeRegion
from models.intent_contract import IntentContract

logger = logging.getLogger(__name__)

# FileIndex type (mirrors repo_ingestor.FileIndex — imported by value to avoid
# a circular dependency chain through repo_ingestor → config)
FileIndex = Dict[str, List[str]]

# Maximum number of CodeRegion objects returned per requirement.
MAX_REGIONS: int = 5

# Maximum number of lines included in a single snippet.
SNIPPET_MAX_LINES: int = 30

# Number of top-scoring files to open for detailed AST region extraction.
TOP_FILES: int = 3


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def trace(
    contract: IntentContract,
    file_index: FileIndex,
    repo_path: Path,
) -> List[CodeRegion]:
    """
    Score every file in *file_index* against *contract.keywords*, open the
    top-scoring files, locate relevant functions/classes with AST, and return
    up to MAX_REGIONS CodeRegion objects sorted by score descending.

    Returns an empty list if *file_index* is empty or no keywords are set.
    """
    keywords = [kw.lower() for kw in contract.keywords if kw.strip()]
    if not keywords or not file_index:
        logger.info("trace: no keywords or empty index for %s", contract.requirement_id)
        return []

    # Step 1 — score every file by keyword presence in path + symbol names
    scored = _score_files(file_index, keywords)
    if not scored:
        return []

    # Step 2 — take top-N files and extract code regions via AST
    top = scored[:TOP_FILES]
    regions: List[CodeRegion] = []
    for rel_path, file_score in top:
        abs_path = Path(repo_path) / rel_path
        if not abs_path.is_file():
            continue
        extracted = _extract_regions(abs_path, rel_path, keywords, file_score)
        regions.extend(extracted)

    # Step 3 — sort by score desc, deduplicate by (file, line_start), cap at MAX_REGIONS
    regions.sort(key=lambda r: r.score, reverse=True)
    seen: set[Tuple[str, int]] = set()
    unique: List[CodeRegion] = []
    for region in regions:
        key = (region.file, region.line_start)
        if key not in seen:
            seen.add(key)
            unique.append(region)
        if len(unique) >= MAX_REGIONS:
            break

    logger.info(
        "trace: %d regions found for %s (keywords=%s)",
        len(unique), contract.requirement_id, keywords[:5],
    )
    return unique


# ---------------------------------------------------------------------------
# File scoring
# ---------------------------------------------------------------------------

def _score_files(
    file_index: FileIndex, keywords: List[str]
) -> List[Tuple[str, int]]:
    """
    Score each file in *file_index* and return a list of (rel_path, score)
    tuples sorted by score descending, excluding files with score == 0.
    """
    results: List[Tuple[str, int]] = []
    for rel_path, symbol_names in file_index.items():
        score = _score_file(rel_path, symbol_names, keywords)
        if score > 0:
            results.append((rel_path, score))
    results.sort(key=lambda t: t[1], reverse=True)
    return results


def _score_file(
    rel_path: str, symbol_names: List[str], keywords: List[str]
) -> int:
    """
    Return the total keyword hit count for a single file.

    Hits are counted in:
    - The file path components (directory names + filename stem)
    - Each symbol name (function / class) in the file
    """
    score = 0
    # Tokenise path: split on '/', '.', '_', '-'
    path_tokens = [t.lower() for t in re.split(r"[/._\-]", rel_path)]
    for kw in keywords:
        # Substring match: "token" matches "generate_reset_token"
        if any(kw in token for token in path_tokens):
            score += 2  # path match weighted higher
        if any(kw in name.lower() for name in symbol_names):
            score += 1
    return score


# ---------------------------------------------------------------------------
# AST region extraction
# ---------------------------------------------------------------------------

def _extract_regions(
    abs_path: Path,
    rel_path: str,
    keywords: List[str],
    base_score: int,
) -> List[CodeRegion]:
    """
    Open *abs_path*, parse it with ast, and return CodeRegion objects for
    each top-level function/class whose name or body source contains a keyword.

    Falls back to a whole-file region if parsing fails.
    """
    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("code_tracer: cannot read %s: %s", abs_path, exc)
        return []

    lines = source.splitlines()

    try:
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError:
        # Unparseable file — return a whole-file region with the base score
        return [_whole_file_region(rel_path, lines, base_score)]

    regions: List[CodeRegion] = []

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue

        # Compute the keyword score for this specific node
        node_score = _score_node(node, keywords, lines)
        if node_score == 0:
            continue

        line_start = node.lineno
        line_end = getattr(node, "end_lineno", node.lineno)
        snippet = _extract_snippet(lines, line_start, line_end)

        regions.append(CodeRegion(
            file=rel_path,
            line_start=line_start,
            line_end=line_end,
            snippet=snippet,
            score=base_score + node_score,
        ))

    # If no function/class matched but the file itself scored, include a
    # file-level region so the test generator still has some context.
    if not regions:
        regions.append(_whole_file_region(rel_path, lines, base_score))

    return regions


def _score_node(
    node: ast.AST, keywords: List[str], lines: List[str]
) -> int:
    """
    Return a per-node keyword score by checking the node name and its source.
    """
    score = 0
    name = getattr(node, "name", "").lower()
    for kw in keywords:
        if kw in name:
            score += 2
    # Also scan the raw source lines of the node body for keyword presence
    line_start = node.lineno
    line_end = getattr(node, "end_lineno", node.lineno)
    body_src = "\n".join(lines[line_start - 1 : line_end]).lower()
    for kw in keywords:
        if kw in body_src:
            score += 1
    return score


def _extract_snippet(
    lines: List[str], line_start: int, line_end: int
) -> str:
    """
    Return up to SNIPPET_MAX_LINES lines of source starting from line_start.
    line numbers are 1-based.
    """
    # clamp
    start = max(0, line_start - 1)
    end = min(len(lines), line_end)
    chunk = lines[start:end]
    if len(chunk) > SNIPPET_MAX_LINES:
        chunk = chunk[:SNIPPET_MAX_LINES]
        chunk.append(f"... ({line_end - line_start + 1 - SNIPPET_MAX_LINES} more lines)")
    return "\n".join(chunk)


def _whole_file_region(
    rel_path: str, lines: List[str], score: int
) -> CodeRegion:
    """Return a region covering the entire file (capped at SNIPPET_MAX_LINES)."""
    snippet = _extract_snippet(lines, 1, len(lines))
    return CodeRegion(
        file=rel_path,
        line_start=1,
        line_end=len(lines),
        snippet=snippet,
        score=score,
    )
