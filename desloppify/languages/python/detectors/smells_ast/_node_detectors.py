"""AST detectors that operate on function/class nodes."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.smells_ast._shared import (
    _is_docstring,
    _is_return_none,
)


def _is_test_file(filepath: str) -> bool:
    """Return True when a path clearly points to a test module."""
    normalized = filepath.replace("\\", "/")
    return normalized.startswith("tests/") or "/tests/" in normalized


def _detect_monster_functions(
    filepath: str, node: ast.AST, smell_counts: dict[str, list]
):
    """Flag functions longer than 150 LOC."""
    if not (hasattr(node, "end_lineno") and node.end_lineno):
        return
    loc = node.end_lineno - node.lineno + 1
    if loc > 150:
        smell_counts["monster_function"].append(
            {
                "file": filepath,
                "line": node.lineno,
                "content": f"{node.name}() — {loc} LOC",
            }
        )


def _detect_dead_functions(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag functions whose body is only pass, return, or return None."""
    if node.decorator_list:
        return
    body = node.body
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass) or _is_return_none(stmt):
            smell_counts["dead_function"].append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"{node.name}() — body is only {ast.dump(stmt)[:40]}",
                }
            )
    elif len(body) == 2:
        first, second = body
        if not _is_docstring(first):
            return
        if isinstance(second, ast.Pass):
            desc = "docstring + pass"
        elif _is_return_none(second):
            desc = "docstring + return None"
        else:
            return
        smell_counts["dead_function"].append(
            {
                "file": filepath,
                "line": node.lineno,
                "content": f"{node.name}() — {desc}",
            }
        )


def _detect_deferred_imports(
    filepath: str, node: ast.AST, smell_counts: dict[str, list]
):
    """Flag function-level imports (possible circular import workarounds)."""
    if _is_test_file(filepath):
        return
    _SKIP_MODULES = ("typing", "typing_extensions", "__future__")
    for child in ast.walk(node):
        if (
            not isinstance(child, ast.Import | ast.ImportFrom)
            or child.lineno <= node.lineno
        ):
            continue
        module = getattr(child, "module", None) or ""
        if module in _SKIP_MODULES:
            continue
        names = ", ".join(a.name for a in child.names[:3])
        if len(child.names) > 3:
            names += f", +{len(child.names) - 3}"
        smell_counts["deferred_import"].append(
            {
                "file": filepath,
                "line": child.lineno,
                "content": f"import {module or names} inside {node.name}()",
            }
        )
        break  # Only flag once per function


def _detect_inline_classes(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag classes defined inside functions."""
    for child in node.body:
        if isinstance(child, ast.ClassDef):
            smell_counts["inline_class"].append(
                {
                    "file": filepath,
                    "line": child.lineno,
                    "content": f"class {child.name} defined inside {node.name}()",
                }
            )


def _detect_lru_cache_mutable(
    filepath: str,
    node: ast.AST,
    tree: ast.Module,
    smell_counts: dict[str, list],
):
    """Flag @lru_cache/@cache functions that reference module-level mutable variables.

    Finds globals referenced in the function body that aren't in the parameter list,
    checking if those names are assigned to mutable values at module level.
    """
    # Check if this function has @lru_cache or @cache decorator
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
        return

    # Get parameter names
    param_names = set()
    for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
        param_names.add(arg.arg)
    if node.args.vararg:
        param_names.add(node.args.vararg.arg)
    if node.args.kwarg:
        param_names.add(node.args.kwarg.arg)

    # Collect module-level mutable assignments
    module_mutables = set()
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

    # Find Name references in function body that point to module-level mutables
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Name)
            and child.id in module_mutables
            and child.id not in param_names
        ):
            smell_counts["lru_cache_mutable"].append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"@lru_cache on {node.name}() reads mutable global '{child.id}'",
                }
            )
            return  # One warning per function is enough
