"""Python extraction: function bodies, class structure, param patterns."""

import ast
import hashlib
import re
from pathlib import Path

from desloppify.base.discovery.source import find_py_files
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.detectors.passthrough import (
    classify_params,
    classify_passthrough_tier,
)
from desloppify.languages.python.extractors_classes import extract_py_classes
from desloppify.languages.python.extractors_shared import (
    extract_py_params,
    find_block_end,
    read_file,
)


def _find_signature_end(lines: list[str], start: int) -> int | None:
    """Find the line where a function signature closes."""
    for j in range(start, len(lines)):
        lt = lines[j]
        if ")" in lt and ":" in lt[lt.rindex(")") + 1 :]:
            return j
        if j > start and lt.strip().endswith(":"):
            return j
    return None


def extract_py_functions(filepath: str) -> list[FunctionInfo]:
    """Extract function bodies from a Python file using indentation-based boundaries."""
    content = read_file(filepath)
    if content is None:
        return []
    lines = content.splitlines()
    functions = []
    fn_re = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(")
    i = 0
    while i < len(lines):
        m = fn_re.match(lines[i])
        if not m:
            i += 1
            continue
        fn_indent = len(m.group(1))
        name = m.group(2)
        start_line = i
        j = _find_signature_end(lines, i)
        if j is None:
            i += 1
            continue

        # Extract params from multi-line signature
        sig_text = "\n".join(lines[start_line : j + 1])
        if "(" not in sig_text or ")" not in sig_text:
            i += 1
            continue
        open_paren = sig_text.index("(")
        close_paren = sig_text.rindex(")")
        param_str = sig_text[open_paren + 1 : close_paren]
        params = extract_py_params(param_str)

        # Find body extent: all lines indented past fn_indent, trim trailing blanks
        block_end = find_block_end(lines, j + 1, fn_indent)
        end_line = block_end
        while end_line > j + 1 and not lines[end_line - 1].strip():
            end_line -= 1
        body = "\n".join(lines[start_line:end_line])
        normalized = normalize_py_body(body)
        if len(normalized.splitlines()) >= 3:
            functions.append(
                FunctionInfo(
                    name=name,
                    file=filepath,
                    line=start_line + 1,
                    end_line=end_line,
                    loc=end_line - start_line,
                    body=body,
                    normalized=normalized,
                    body_hash=hashlib.md5(
                        normalized.encode(),
                        usedforsecurity=False,
                    ).hexdigest(),
                    params=params,
                )
            )
        i = end_line
    return functions


def normalize_py_body(body: str) -> str:
    """Normalize a Python function body: strip docstrings, comments, print/logging."""
    lines = body.splitlines()
    normalized = []
    in_docstring = False
    docstring_quote = None
    for line in lines:
        stripped = line.strip()
        if in_docstring:
            if docstring_quote and docstring_quote in stripped:
                in_docstring = False
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            docstring_quote = stripped[:3]
            if stripped.count(docstring_quote) >= 2:
                continue
            in_docstring = True
            continue
        if not stripped or stripped.startswith("#"):
            continue
        cp = stripped.find("  #")
        if cp > 0:
            stripped = stripped[:cp].rstrip()
        if re.match(r"(?:print\s*\(|(?:logging|logger|log)\.\w+\s*\()", stripped):
            continue
        if stripped:
            normalized.append(stripped)
    return "\n".join(normalized)


def py_passthrough_pattern(name: str) -> str:
    """Match same-name keyword arg: param=param in a function call."""
    escaped = re.escape(name)
    return rf"\b{escaped}\s*=\s*{escaped}\b"


def _function_param_names(node: ast.FunctionDef) -> list[str]:
    """Return the explicit parameter names that count toward wrapper forwarding."""

    arguments = [
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg)
    return [
        argument.arg for argument in arguments if argument.arg not in {"self", "cls"}
    ]


def _is_docstring_expr(statement: ast.stmt) -> bool:
    """Return whether a statement is a function docstring expression."""

    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_direct_parameter_value(value: ast.expr, parameter_names: set[str]) -> bool:
    """Return whether a call argument directly forwards one function parameter."""

    if isinstance(value, ast.Name):
        return value.id in parameter_names
    return (
        isinstance(value, ast.Starred)
        and isinstance(value.value, ast.Name)
        and value.value.id in parameter_names
    )


def _is_direct_call_target(target: ast.expr) -> bool:
    """Return whether a call target has a static name or attribute-chain root."""

    while isinstance(target, ast.Attribute):
        target = target.value
    return isinstance(target, ast.Name)


def _passthrough_return_statement(
    node: ast.FunctionDef,
    parameter_names: list[str],
) -> ast.Return | None:
    """Return the sole direct-forwarding return statement for a pure wrapper.

    Decorated entrypoints and multi-step functions can forward many arguments
    while still constructing requests, making decisions, or retaining state.
    They are not the redundant wrappers this detector is meant to surface.
    """

    if node.decorator_list:
        return None
    statements = list(node.body)
    if statements and _is_docstring_expr(statements[0]):
        statements = statements[1:]
    if len(statements) != 1 or not isinstance(statements[0], ast.Return):
        return None
    statement = statements[0]
    if not isinstance(statement.value, ast.Call):
        return None
    if not _is_direct_call_target(statement.value.func):
        return None

    values = [
        *statement.value.args,
        *(keyword.value for keyword in statement.value.keywords),
    ]
    if not values:
        return None
    parameter_name_set = set(parameter_names)
    if not all(
        _is_direct_parameter_value(value, parameter_name_set) for value in values
    ):
        return None
    return statement


def detect_passthrough_functions(path: Path) -> list[dict]:
    """Detect pure Python wrappers where most params are same-name forwarded."""
    entries = []
    for filepath in find_py_files(path):
        content = read_file(filepath)
        if content is None:
            continue
        try:
            tree = ast.parse(content, filename=filepath)
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            name = node.name
            params = _function_param_names(node)
            if len(params) < 4:
                continue
            return_statement = _passthrough_return_statement(node, params)
            if return_statement is None:
                continue
            body = ast.get_source_segment(content, return_statement)
            if body is None:
                continue
            call = return_statement.value
            if not isinstance(call, ast.Call):
                continue

            has_kwargs_spread = any(keyword.arg is None for keyword in call.keywords)
            pt, direct = classify_params(
                params, body, py_passthrough_pattern, occurrences_per_match=2
            )

            if len(pt) < 4 and not has_kwargs_spread:
                continue
            ratio = len(pt) / len(params)
            classification = classify_passthrough_tier(
                len(pt), ratio, has_spread=has_kwargs_spread
            )
            if classification is None:
                continue
            tier, confidence = classification

            entries.append(
                {
                    "file": filepath,
                    "function": name,
                    "total_params": len(params),
                    "passthrough": len(pt),
                    "direct": len(direct),
                    "ratio": round(ratio, 2),
                    "line": node.lineno,
                    "tier": tier,
                    "confidence": confidence,
                    "passthrough_params": sorted(pt),
                    "direct_params": sorted(direct),
                    "has_kwargs_spread": has_kwargs_spread,
                }
            )

    return sorted(entries, key=lambda e: (-e["passthrough"], -e["ratio"]))


__all__ = [
    "detect_passthrough_functions",
    "extract_py_classes",
    "extract_py_functions",
    "extract_py_params",
    "normalize_py_body",
    "py_passthrough_pattern",
]
