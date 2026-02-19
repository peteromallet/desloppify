"""Quality and maintainability oriented tree-level smell detectors."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.smells_ast._shared import (
    _is_docstring,
    _is_log_or_print,
    _is_return_none,
    _is_trivial_if,
    _iter_nodes,
)
from desloppify.languages.python.detectors.smells_ast._tree_quality_detectors_types import (
    _detect_annotation_quality as _detect_annotation_quality,
)
from desloppify.languages.python.detectors.smells_ast._tree_quality_detectors_types import (
    _detect_optional_param_sprawl as _detect_optional_param_sprawl,
)

__all__ = [
    "_detect_annotation_quality",
    "_detect_constant_return",
    "_detect_mutable_class_var",
    "_detect_noop_function",
    "_detect_optional_param_sprawl",
    "_detect_unreachable_code",
]


def _detect_mutable_class_var(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag class-level mutable defaults (shared across all instances).

    Detects: class Foo: data = [] / data = {} / data: list = []
    Skips dataclasses (which use field(default_factory=...)) and __init__ assignments.
    """
    for node in _iter_nodes(tree, all_nodes, ast.ClassDef):
        # Skip dataclasses (they handle mutable defaults via field())
        is_dataclass = any(
            (isinstance(d, ast.Name) and d.id == "dataclass")
            or (
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Name)
                and d.func.id == "dataclass"
            )
            or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
            for d in node.decorator_list
        )
        if is_dataclass:
            continue

        for stmt in node.body:
            # Plain assignment: data = [] or data = {}
            if isinstance(stmt, ast.Assign):
                if isinstance(stmt.value, ast.List | ast.Dict | ast.Set):
                    names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                    for name in names:
                        smell_counts["mutable_class_var"].append(
                            {
                                "file": filepath,
                                "line": stmt.lineno,
                                "content": f"{node.name}.{name} = {ast.dump(stmt.value)[:40]}",
                            }
                        )
            # Annotated assignment: data: list = []
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                if isinstance(stmt.value, ast.List | ast.Dict | ast.Set):
                    name = stmt.target.id if isinstance(stmt.target, ast.Name) else "?"
                    smell_counts["mutable_class_var"].append(
                        {
                            "file": filepath,
                            "line": stmt.lineno,
                            "content": f"{node.name}.{name}: ... = {ast.dump(stmt.value)[:40]}",
                        }
                    )


def _detect_unreachable_code(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag statements after unconditional return/raise/break/continue.

    Walks every statement block (function body, if/else body, etc.) and flags
    any statement that follows an unconditional flow-control statement.
    """
    _TERMINAL = (ast.Return, ast.Raise, ast.Break, ast.Continue)

    def _check_block(stmts: list[ast.stmt]):
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, _TERMINAL) and i < len(stmts) - 1:
                next_stmt = stmts[i + 1]
                # Skip flagging string constants (often used as section markers)
                if isinstance(next_stmt, ast.Expr) and isinstance(
                    next_stmt.value, ast.Constant
                ):
                    continue
                smell_counts["unreachable_code"].append(
                    {
                        "file": filepath,
                        "line": next_stmt.lineno,
                        "content": f"unreachable after {type(stmt).__name__.lower()} on line {stmt.lineno}",
                    }
                )
            # Recurse into compound statements
            for attr in ("body", "orelse", "finalbody", "handlers"):
                block = getattr(stmt, attr, None)
                if isinstance(block, list):
                    child_stmts = [s for s in block if isinstance(s, ast.stmt)]
                    if child_stmts:
                        _check_block(child_stmts)
            # ExceptHandler has a body too
            if isinstance(stmt, ast.ExceptHandler):
                _check_block(stmt.body)

    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _check_block(node.body)


def _detect_constant_return(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag functions that always return the same constant value.

    Analyzes all return paths — if every return statement returns the same
    literal value (True, False, None, a number, or a string), the function
    likely has dead logic or is a stub masquerading as real code.
    """
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Skip tiny functions (stubs/pass-only already caught by dead_function)
        if not hasattr(node, "end_lineno") or not node.end_lineno:
            continue
        loc = node.end_lineno - node.lineno + 1
        if loc < 4:
            continue
        # Skip decorated functions (properties, abstractmethods, etc.)
        if node.decorator_list:
            continue

        returns = []
        has_conditional = False
        for child in ast.walk(node):
            if isinstance(child, ast.Return):
                returns.append(child)
            if isinstance(
                child,
                ast.If | ast.For | ast.While | ast.With | ast.Try | ast.ExceptHandler,
            ):
                has_conditional = True

        # Need at least 2 returns and some conditional logic to be interesting
        if len(returns) < 2 or not has_conditional:
            continue

        # Extract constant values from all returns
        values = set()
        all_constant = True
        for ret in returns:
            if ret.value is None:
                values.add(repr(None))
            elif isinstance(ret.value, ast.Constant):
                values.add(repr(ret.value.value))
            else:
                all_constant = False
                break

        if all_constant and len(values) == 1:
            val = next(iter(values))
            # Skip functions that always return None — they're just procedures
            if val == "None":
                continue
            smell_counts["constant_return"].append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"{node.name}() always returns {val} ({len(returns)} return sites)",
                }
            )


def _detect_noop_function(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag non-trivial functions whose body does nothing useful.

    A function is noop if its body contains only: pass, return, logging calls,
    and early-return ifs with trivial bodies. Excludes __init__, abstract methods,
    property getters, short functions (< 3 statements), and decorated functions.
    """
    _SKIP_NAMES = {
        "__init__",
        "__str__",
        "__repr__",
        "__enter__",
        "__exit__",
        "__del__",
        "__hash__",
        "__eq__",
        "__lt__",
        "__le__",
        "__gt__",
        "__ge__",
        "__ne__",
        "__bool__",
        "__len__",
    }

    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name in _SKIP_NAMES:
            continue
        # Skip decorated functions (abstract methods, properties, etc.)
        if node.decorator_list:
            continue
        # Skip short functions — dead_function already catches 1-2 statement bodies
        body = node.body
        # Strip leading docstring
        if body and _is_docstring(body[0]):
            body = body[1:]
        if len(body) < 3:
            continue

        # Check if every statement is trivial
        all_trivial = True
        for stmt in body:
            if isinstance(stmt, ast.Pass):
                continue
            if _is_return_none(stmt):
                continue
            if _is_log_or_print(stmt):
                continue
            if _is_trivial_if(stmt):
                continue
            all_trivial = False
            break

        if all_trivial:
            smell_counts["noop_function"].append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"{node.name}() — {len(body)} statements, all trivial (pass/return/log)",
                }
            )
