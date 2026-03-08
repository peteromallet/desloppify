"""Node detectors for basic function/class AST smells."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.smells_ast._helpers import (
    _is_docstring,
    _is_return_none,
)


def _is_test_file(filepath: str) -> bool:
    """Return True when a path clearly points to a test module."""
    normalized = filepath.replace("\\", "/")
    return normalized.startswith("tests/") or "/tests/" in normalized


def _detect_monster_functions(filepath: str, node: ast.AST) -> list[dict]:
    """Flag functions longer than 150 LOC."""
    if not (hasattr(node, "end_lineno") and node.end_lineno):
        return []
    loc = node.end_lineno - node.lineno + 1
    if loc > 150:
        return [
            {
                "file": filepath,
                "line": node.lineno,
                "content": f"{node.name}() - {loc} LOC",
            }
        ]
    return []


def _detect_dead_functions(filepath: str, node: ast.AST) -> list[dict]:
    """Flag functions whose body is only pass, return, or return None."""
    if node.decorator_list:
        return []
    body = node.body
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass) or _is_return_none(stmt):
            return [
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"{node.name}() - body is only {ast.dump(stmt)[:40]}",
                }
            ]
    elif len(body) == 2:
        first, second = body
        if not _is_docstring(first):
            return []
        if isinstance(second, ast.Pass):
            desc = "docstring + pass"
        elif _is_return_none(second):
            desc = "docstring + return None"
        else:
            return []
        return [
            {
                "file": filepath,
                "line": node.lineno,
                "content": f"{node.name}() - {desc}",
            }
        ]
    return []


def _detect_deferred_imports(filepath: str, node: ast.AST) -> list[dict]:
    """Flag function-level imports (possible circular import workarounds)."""
    if _is_test_file(filepath):
        return []
    skip_modules = ("typing", "typing_extensions", "__future__")
    for child in ast.walk(node):
        if (
            not isinstance(child, ast.Import | ast.ImportFrom)
            or child.lineno <= node.lineno
        ):
            continue
        module = getattr(child, "module", None) or ""
        if module in skip_modules:
            continue
        names = ", ".join(a.name for a in child.names[:3])
        if len(child.names) > 3:
            names += f", +{len(child.names) - 3}"
        return [
            {
                "file": filepath,
                "line": child.lineno,
                "content": f"import {module or names} inside {node.name}()",
            }
        ]
    return []


def _detect_inline_classes(filepath: str, node: ast.AST) -> list[dict]:
    """Flag classes defined inside functions."""
    results: list[dict] = []
    for child in node.body:
        if isinstance(child, ast.ClassDef):
            results.append(
                {
                    "file": filepath,
                    "line": child.lineno,
                    "content": f"class {child.name} defined inside {node.name}()",
                }
            )
    return results


__all__ = [
    "_detect_dead_functions",
    "_detect_deferred_imports",
    "_detect_inline_classes",
    "_detect_monster_functions",
    "_is_test_file",
]
