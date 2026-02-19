"""Runtime-flow safety detectors split from tree_safety_detectors."""

from __future__ import annotations

import ast
from pathlib import Path

from desloppify.languages.python.detectors.smells_ast._shared import _iter_nodes

_CLI_FILENAMES = {"cli.py", "__main__.py", "manage.py", "setup.py"}
_CLI_DIR_PATTERNS = {"/commands/", "/management/"}


def _is_main_guard(test: ast.AST) -> bool:
    """Return True when test is `if __name__ == "__main__"`."""
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False

    left, right = test.left, test.comparators[0]

    def _is_name_main(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id == "__name__"

    def _is_main_literal(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value == "__main__"

    return (_is_name_main(left) and _is_main_literal(right)) or (
        _is_name_main(right) and _is_main_literal(left)
    )


def _iter_import_time_calls(tree: ast.Module):
    """Yield calls executed at module import time (excluding __main__ guard)."""
    stack: list[ast.AST] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.If) and _is_main_guard(stmt.test):
            continue
        stack.append(stmt)

    while stack:
        node = stack.pop()
        if isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda
        ):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_sys_path_mutation(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in {"insert", "append"}:
        return False
    value = func.value
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "path"
        and isinstance(value.value, ast.Name)
        and value.value.id == "sys"
    )


def _detect_import_time_boundary_mutations(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag import-time runtime mutations in non-entrypoint modules."""
    del all_nodes  # Traversal is top-level execution order, not full-node walk.

    for call in _iter_import_time_calls(tree):
        if _is_sys_path_mutation(call):
            if "import_path_mutation" in smell_counts:
                smell_counts["import_path_mutation"].append(
                    {
                        "file": filepath,
                        "line": call.lineno,
                        "content": "sys.path mutation at import time",
                    }
                )
            continue

        call_name = _call_name(call)
        if call_name == "load_dotenv":
            if "import_env_mutation" in smell_counts:
                smell_counts["import_env_mutation"].append(
                    {
                        "file": filepath,
                        "line": call.lineno,
                        "content": "load_dotenv() at import time",
                    }
                )
            continue

        if call_name in {"setup_logging", "basicConfig", "dictConfig", "fileConfig"}:
            if "import_runtime_init" in smell_counts:
                smell_counts["import_runtime_init"].append(
                    {
                        "file": filepath,
                        "line": call.lineno,
                        "content": f"{call_name}() at import time",
                    }
                )


def _detect_sys_exit_in_library(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag sys.exit()/exit()/quit() outside CLI entry points."""
    basename = Path(filepath).name
    if basename in _CLI_FILENAMES:
        return
    if any(pattern in filepath for pattern in _CLI_DIR_PATTERNS):
        return

    for node in _iter_nodes(tree, all_nodes, ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "exit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "sys"
        ):
            smell_counts["sys_exit_in_library"].append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": "sys.exit() in library code — raise an exception instead",
                }
            )
        elif isinstance(func, ast.Name) and func.id in ("exit", "quit"):
            smell_counts["sys_exit_in_library"].append(
                {
                    "file": filepath,
                    "line": node.lineno,
                    "content": f"{func.id}() in library code — raise an exception instead",
                }
            )


def _detect_silent_except(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag except handlers that only pass/continue and swallow errors silently."""
    for node in _iter_nodes(tree, all_nodes, ast.ExceptHandler):
        body = node.body
        if not body:
            continue
        all_silent = True
        for stmt in body:
            if isinstance(stmt, ast.Pass | ast.Continue):
                continue
            all_silent = False
            break
        if not all_silent:
            continue

        if node.type is None:
            clause = "except:"
        elif isinstance(node.type, ast.Name):
            clause = f"except {node.type.id}:"
        elif isinstance(node.type, ast.Tuple):
            names = [elt.id for elt in node.type.elts if isinstance(elt, ast.Name)]
            clause = f"except ({', '.join(names)}):"
        else:
            clause = "except ...:"

        body_text = "pass" if isinstance(body[0], ast.Pass) else "continue"
        smell_counts["silent_except"].append(
            {
                "file": filepath,
                "line": node.lineno,
                "content": f"{clause} {body_text} — error silently suppressed",
            }
        )


__all__ = [
    "_detect_import_time_boundary_mutations",
    "_detect_silent_except",
    "_detect_sys_exit_in_library",
]
