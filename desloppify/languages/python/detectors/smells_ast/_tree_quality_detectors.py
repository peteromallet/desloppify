"""Quality and maintainability oriented tree-level smell detectors."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.smells_ast._helpers import (
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
    "_detect_del_param",
    "_detect_noop_function",
    "_detect_optional_param_sprawl",
    "_detect_unreachable_code",
]


def _detect_unreachable_code(
    filepath: str,
    tree: ast.Module,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag statements after unconditional return/raise/break/continue.

    Walks every statement block (function body, if/else body, etc.) and flags
    any statement that follows an unconditional flow-control statement.
    """
    _TERMINAL = (ast.Return, ast.Raise, ast.Break, ast.Continue)
    results: list[dict] = []

    def _check_block(stmts: list[ast.stmt]):
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, _TERMINAL) and i < len(stmts) - 1:
                next_stmt = stmts[i + 1]
                # Skip flagging string constants (often used as section markers)
                if isinstance(next_stmt, ast.Expr) and isinstance(
                    next_stmt.value, ast.Constant
                ):
                    continue
                results.append(
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
    return results


def _is_main_module_guard(node: ast.AST) -> bool:
    """Return whether a statement is exactly ``if __name__ == "__main__"``."""
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.Eq)
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "__main__"
    )


def _main_guard_invokes_main(guard: ast.If) -> bool:
    """Return whether a module-main guard directly executes ``main()``."""
    stack: list[ast.AST] = list(reversed(guard.body))
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Call) and isinstance(current.func, ast.Name):
            if current.func.id == "main":
                return True
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(current))))
    return False


def _find_top_level_cli_main(
    tree: ast.Module,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the top-level ``main`` invoked by a module-main guard, if any."""
    if not any(
        _is_main_module_guard(statement) and _main_guard_invokes_main(statement)
        for statement in tree.body
    ):
        return None
    for statement in reversed(tree.body):
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef) and statement.name == "main":
            return statement
    return None


def _detect_constant_return(
    filepath: str,
    tree: ast.Module,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag functions that always return the same constant value.

    Analyzes all return paths — if every return statement returns the same
    literal value (True, False, None, a number, or a string), the function
    likely has dead logic or is a stub masquerading as real code.
    """
    def _iter_function_scope_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef):
        """Iterate nodes in this function body, skipping nested function scopes."""
        stack: list[ast.AST] = list(reversed(node.body))
        while stack:
            current = stack.pop()
            yield current
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            for child in reversed(list(ast.iter_child_nodes(current))):
                stack.append(child)

    cli_main = _find_top_level_cli_main(tree)
    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node is cli_main:
            continue
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
        for child in _iter_function_scope_nodes(node):
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
            results.append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"{node.name}() always returns {val} ({len(returns)} return sites)",
                }
            )
    return results


def _detect_noop_function(
    filepath: str,
    tree: ast.Module,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
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
    _DISPLAY_HELPER_PREFIXES = ("_print_", "_render_", "_show_")

    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name in _SKIP_NAMES:
            continue
        if (
            "app/commands/" in filepath.replace("\\", "/")
            and node.name.startswith(_DISPLAY_HELPER_PREFIXES)
        ):
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
            results.append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"{node.name}() — {len(body)} statements, all trivial (pass/return/log)",
                }
            )
    return results


def _detect_del_param(
    filepath: str,
    tree: ast.Module,
    all_nodes: tuple[ast.AST, ...] | None = None,
) -> list[dict]:
    """Flag functions that ``del`` a parameter in the first 3 body statements.

    ``del param`` immediately after receiving it means the parameter shouldn't
    be in the signature at all — the caller shouldn't be passing it.
    """
    results: list[dict] = []
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        param_names = {
            a.arg
            for a in node.args.args + node.args.posonlyargs + node.args.kwonlyargs
        }
        if not param_names:
            continue

        # Strip leading docstring before checking first 3 body statements.
        body = node.body
        if body and _is_docstring(body[0]):
            body = body[1:]

        # Only check first 3 body statements (del is typically early cleanup).
        for stmt in body[:3]:
            if not isinstance(stmt, ast.Delete):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id in param_names:
                    results.append(
                        {
                            "file": filepath,
                            "line": stmt.lineno,
                            "content": f"del {target.id} — remove from function signature",
                        }
                    )
    return results
