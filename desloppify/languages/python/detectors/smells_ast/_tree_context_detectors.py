"""Context-oriented tree-level smell detectors (callbacks, path handling)."""

from __future__ import annotations

import ast

from desloppify.languages.python.detectors.smells_ast._shared import (
    _iter_nodes,
    _looks_like_path_var,
)

_CALLBACK_LOG_NAMES = {
    "dprint",
    "debug_print",
    "debug_func",
    "log_func",
    "print_fn",
    "logger_func",
    "log_callback",
    "print_func",
    "debug_log",
    "verbose_print",
    "trace_func",
}


def _detect_callback_logging(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag functions that accept a logging callback parameter.

    Detects parameters matching common logging-callback names (dprint, log_func, etc.)
    that are actually called with string arguments in the function body.
    """
    for node in _iter_nodes(tree, all_nodes, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # Check each parameter name
        for arg in node.args.args + node.args.kwonlyargs:
            name = arg.arg
            if name not in _CALLBACK_LOG_NAMES:
                continue

            # Verify it's actually called in the body (not just accepted)
            call_count = 0
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == name
                ):
                    call_count += 1

            if call_count >= 1:
                smell_counts["callback_logging"].append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": f"{node.name}({name}=...) — called {call_count} time(s)",
                    }
                )


def _detect_hardcoded_path_sep(
    filepath: str,
    tree: ast.Module,
    smell_counts: dict[str, list],
    *,
    all_nodes: tuple[ast.AST, ...] | None = None,
):
    """Flag .split('/') on path-like variables, and os.path.join mixed with '/'.

    Detects two patterns:
    1. path_var.split('/') — should use os.sep or normalize with replace('\\\\', '/')
    2. f-strings or concatenation building paths with hardcoded '/' separators
       on variables with path-like names
    """
    for node in _iter_nodes(tree, all_nodes, ast.Call):
        # Pattern 1: var.split("/") where var looks like a path
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "split"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "/"
        ):
            # Check what's being split
            obj = node.func.value
            var_name = ""
            if isinstance(obj, ast.Name):
                var_name = obj.id
            elif isinstance(obj, ast.Attribute):
                var_name = obj.attr
            # Also catch chained: os.path.relpath(...).split("/")
            elif isinstance(obj, ast.Call):
                if isinstance(obj.func, ast.Attribute) and obj.func.attr in (
                    "relpath",
                    "relative_to",
                ):
                    smell_counts["hardcoded_path_sep"].append(
                        {
                            "file": filepath,
                            "line": node.lineno,
                            "content": f'{ast.dump(obj.func)[:40]}.split("/")',
                        }
                    )
                    continue

            if var_name and _looks_like_path_var(var_name):
                smell_counts["hardcoded_path_sep"].append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": f'{var_name}.split("/")',
                    }
                )

        # Pattern 2: path_var.startswith("something/with/slashes")
        # Skip module specifiers (@/, http://, etc.)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and "/" in node.args[0].value
            and not node.args[0].value.startswith(("@", "http", "//"))
        ):
            obj = node.func.value
            var_name = ""
            if isinstance(obj, ast.Name):
                var_name = obj.id
            elif isinstance(obj, ast.Attribute):
                var_name = obj.attr
            if var_name and _looks_like_path_var(var_name):
                smell_counts["hardcoded_path_sep"].append(
                    {
                        "file": filepath,
                        "line": node.lineno,
                        "content": f'{var_name}.startswith("{node.args[0].value}")',
                    }
                )
