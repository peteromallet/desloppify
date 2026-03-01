"""Uncalled private function detection for Python.

Finds underscore-prefixed top-level functions with zero references
across the entire codebase. Only flags high-confidence cases:
- _private (underscore prefix = explicitly internal)
- Top-level only (no method-resolution ambiguity)
- Non-dunder, non-decorated, non-test
- Body > 3 lines (skip trivial helpers)
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from desloppify.core.discovery_api import read_file_text, rel

# Entry-point files where unused private functions are expected.
# Subset of PY_ENTRY_PATTERNS from phases.py (can't import — circular).
_ENTRY_PATTERNS = [
    "__main__.py",
    "conftest.py",
    "manage.py",
    "setup.py",
    "cli.py",
    "wsgi.py",
    "asgi.py",
]


def _is_test_file(filepath: str) -> bool:
    """True when a file path clearly points to test code."""
    normalized = filepath.replace("\\", "/")
    basename = os.path.basename(normalized)
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return True
    markers = ("/tests/", "/test/", "/__tests__/", "/fixtures/")
    padded = f"/{normalized}/"
    return any(marker in padded for marker in markers)


def _is_entry_file(filepath: str) -> bool:
    """True if file matches any entry-point pattern."""
    r = rel(filepath)
    return any(p in r for p in _ENTRY_PATTERNS)


def _is_candidate(node: ast.AST) -> bool:
    """True if an AST node is a top-level private function worth flagging."""
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    name = node.name
    if not name.startswith("_"):
        return False
    if name.startswith("__") and name.endswith("__"):
        return False
    if node.decorator_list:
        return False
    loc = (node.end_lineno or node.lineno) - node.lineno + 1
    if loc <= 3:
        return False
    return True


def detect_uncalled_functions(
    path: Path,
    graph: dict,
) -> tuple[list[dict], int]:
    """Find underscore-prefixed top-level functions with zero references.

    Single-pass: walks every file's AST once, collecting both references
    (Name, Attribute, import aliases) and function-definition candidates.

    Returns:
        (entries, total_candidates) — entries are dicts with file/name/line/loc.
    """
    project_files = [f for f in graph if f.endswith(".py")]
    if not project_files:
        return [], 0

    refs: set[str] = set()
    # (rel_path, name, lineno, loc) for each candidate
    candidates: list[tuple[str, str, int, int]] = []

    for filepath in project_files:
        content = read_file_text(filepath)
        if content is None:
            continue
        try:
            tree = ast.parse(content, filename=filepath)
        except SyntaxError as exc:
            _ = exc
            continue

        # Collect all references from this file
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                refs.add(node.id)
            elif isinstance(node, ast.Attribute):
                refs.add(node.attr)
            elif isinstance(node, ast.ImportFrom | ast.Import):
                for alias in node.names or []:
                    refs.add(alias.name)

        # Collect candidates (only from non-test, non-entry files)
        if _is_test_file(filepath) or _is_entry_file(filepath):
            continue
        for node in ast.iter_child_nodes(tree):
            if _is_candidate(node):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                candidates.append((rel(filepath), node.name, node.lineno, loc))

    # Filter candidates against reference index
    entries = [
        {"file": rfile, "name": name, "line": line, "loc": loc}
        for rfile, name, line, loc in candidates
        if name not in refs
    ]

    return sorted(entries, key=lambda e: -e["loc"]), len(candidates)
