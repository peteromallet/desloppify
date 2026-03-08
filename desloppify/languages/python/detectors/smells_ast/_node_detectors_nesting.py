"""Node detectors for closure nesting and mutable-ref patterns."""

from __future__ import annotations

import ast

_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_BLOCK_ATTRS = ("body", "handlers", "orelse", "finalbody")


def _walk_inner_defs(
    body: list[ast.AST], depth: int, inner_defs: list[ast.AST],
) -> int:
    """Recursively collect inner function/lambda defs and return max depth."""
    max_depth = 0
    for child in body:
        if isinstance(child, _FUNC_TYPES):
            inner_defs.append(child)
            current_depth = depth + 1
            max_depth = max(max_depth, current_depth)
            child_body = getattr(child, "body", None)
            if isinstance(child_body, list):
                max_depth = max(
                    max_depth,
                    _walk_inner_defs(child_body, current_depth, inner_defs),
                )
            elif isinstance(child, ast.Lambda):
                max_depth = max(
                    max_depth,
                    _collect_nested_lambdas(child, current_depth, inner_defs),
                )
        else:
            for attr in _BLOCK_ATTRS:
                sub_body = getattr(child, attr, None)
                if isinstance(sub_body, list):
                    max_depth = max(
                        max_depth, _walk_inner_defs(sub_body, depth, inner_defs),
                    )
    return max_depth


def _collect_nested_lambdas(
    parent: ast.Lambda, depth: int, inner_defs: list[ast.AST],
) -> int:
    """Walk a lambda expression body for nested lambdas."""
    max_depth = depth
    for sub in ast.walk(parent.body):
        if isinstance(sub, ast.Lambda) and sub is not parent:
            inner_defs.append(sub)
            max_depth = max(max_depth, depth + 1)
    return max_depth


def _format_inner_def_names(inner_defs: list[ast.AST]) -> str:
    """Format inner def names for issue content."""
    names = [
        getattr(d, "name", "<lambda>")
        for d in inner_defs[:5]
        if isinstance(d, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    names_str = ", ".join(names) if names else "<lambdas>"
    if len(inner_defs) > 5:
        names_str += ", ..."
    return names_str


def _detect_nested_closures(filepath: str, node: ast.AST) -> list[dict]:
    """Flag functions with deeply nested or numerous inner defs."""
    inner_defs: list[ast.AST] = []
    max_depth = _walk_inner_defs(node.body, 0, inner_defs)

    if max_depth < 2 and len(inner_defs) < 3:
        return []
    return [
        {
            "file": filepath,
            "line": node.lineno,
            "content": (
                f"{node.name}() - {len(inner_defs)} inner defs"
                f" (depth {max_depth}): {_format_inner_def_names(inner_defs)}"
            ),
        }
    ]


def _collect_single_list_assignments(body: list[ast.AST]) -> dict[str, int]:
    """Return {name: lineno} for assignments in the form ``x = [single]``."""
    result: dict[str, int] = {}
    for stmt in body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if (
            isinstance(target, ast.Name)
            and isinstance(stmt.value, ast.List)
            and len(stmt.value.elts) == 1
        ):
            result[target.id] = stmt.lineno
    return result


def _find_subscript_zero_refs(
    node: ast.AST, candidate_names: set[str],
) -> set[str]:
    """Find candidate names accessed as ``x[0]`` inside nested functions."""
    used: set[str] = set()
    for child in ast.walk(node):
        if child is node or not isinstance(child, _FUNC_TYPES):
            continue
        for sub in ast.walk(child):
            if not isinstance(sub, ast.Subscript):
                continue
            if not isinstance(sub.value, ast.Name):
                continue
            if sub.value.id not in candidate_names:
                continue
            if isinstance(sub.slice, ast.Constant) and sub.slice.value == 0:
                used.add(sub.value.id)
    return used


def _detect_mutable_ref_hack(filepath: str, node: ast.AST) -> list[dict]:
    """Flag ``x = [value]`` with ``x[0]`` mutation in nested functions."""
    single_list_names = _collect_single_list_assignments(node.body)
    if not single_list_names:
        return []

    used_names = _find_subscript_zero_refs(node, set(single_list_names))
    return [
        {
            "file": filepath,
            "line": single_list_names[name],
            "content": (
                f"{name} = [v] in {node.name}()"
                " - mutable-list ref hack (use nonlocal or a dataclass)"
            ),
        }
        for name in sorted(used_names)
    ]


__all__ = [
    "_collect_nested_lambdas",
    "_collect_single_list_assignments",
    "_detect_mutable_ref_hack",
    "_detect_nested_closures",
    "_find_subscript_zero_refs",
    "_format_inner_def_names",
    "_walk_inner_defs",
]
