"""Node detectors for complexity and cached-global smells."""

from __future__ import annotations

import ast

# Node types that contribute to cyclomatic complexity.
_DECISION_TYPES = (
    ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While,
    ast.ExceptHandler, ast.With, ast.AsyncWith, ast.Assert,
)


def _compute_cyclomatic_complexity(node: ast.AST) -> int:
    """Compute cyclomatic complexity for a function AST node."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, _DECISION_TYPES):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
    return complexity


def _detect_high_cyclomatic_complexity(filepath: str, node: ast.AST) -> list[dict]:
    """Flag functions with cyclomatic complexity > 12."""
    complexity = _compute_cyclomatic_complexity(node)
    if complexity > 12:
        return [
            {
                "file": filepath,
                "line": node.lineno,
                "content": f"{node.name}() - cyclomatic complexity {complexity}",
            }
        ]
    return []


def _detect_lru_cache_mutable(
    filepath: str,
    node: ast.AST,
    tree: ast.Module,
) -> list[dict]:
    """Flag cached functions that reference mutable module-level variables."""
    has_cache = False
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in ("lru_cache", "cache"):
            has_cache = True
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            if dec.func.id in ("lru_cache", "cache"):
                has_cache = True
        elif isinstance(dec, ast.Attribute) and dec.attr in ("lru_cache", "cache"):
            has_cache = True
    if not has_cache:
        return []

    param_names = {
        arg.arg for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs
    }
    if node.args.vararg:
        param_names.add(node.args.vararg.arg)
    if node.args.kwarg:
        param_names.add(node.args.kwarg.arg)

    module_mutables: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and isinstance(
                    stmt.value, ast.List | ast.Dict | ast.Set | ast.Call
                ):
                    module_mutables.add(target.id)
        elif (
            isinstance(stmt, ast.AnnAssign)
            and stmt.target
            and isinstance(stmt.target, ast.Name)
        ):
            if stmt.value and isinstance(
                stmt.value, ast.List | ast.Dict | ast.Set | ast.Call
            ):
                module_mutables.add(stmt.target.id)

    for child in ast.walk(node):
        if (
            isinstance(child, ast.Name)
            and child.id in module_mutables
            and child.id not in param_names
        ):
            return [
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"@lru_cache on {node.name}() reads mutable global '{child.id}'",
                }
            ]
    return []


__all__ = [
    "_compute_cyclomatic_complexity",
    "_detect_high_cyclomatic_complexity",
    "_detect_lru_cache_mutable",
]
