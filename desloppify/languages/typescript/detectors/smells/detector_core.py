"""Shared helpers and constants for TypeScript smell detectors."""

from __future__ import annotations

import re

from .helpers import (
    _code_text,
    _strip_ts_comments,
)

_MONSTER_FUNCTION_LOC = 150
_HIGH_CYCLOMATIC_THRESHOLD = 15
_NESTED_CLOSURE_THRESHOLD = 3
_CATCH_DEFAULT_FIELD_THRESHOLD = 2
_SWITCH_CASE_MINIMUM = 2

_MAX_CATCH_BODY = 1000
_MAX_SWITCH_BODY_SCAN = 5000

_ERROR_HANDLER_BASENAMES = (
    "logger",
    "errorpresentation",
    "errorhandler",
    "errorreporting",
)
_PRECEDING_SKIP_PATTERNS = re.compile(
    r"componentDidCatch|import\.meta\.env\.DEV|process\.env\.NODE_ENV"
)
_HANDLED_RE = re.compile(
    r"\b(?:throw|return)\b|toast\(|normalizeAndPresentError\(|presentError\(|rethrow"
)

_FUNC_RE = re.compile(r"\bfunction\s*[\w(]")
_ARROW_RE = re.compile(r"=>\s*\{")

_TS_BRANCH_PATTERNS = (
    re.compile(r"\bif\s*\("),
    re.compile(r"\belse\s+if\s*\("),
    re.compile(r"\bcase\s+"),
    re.compile(r"\bcatch\s*\("),
    re.compile(r"\bfor\s*\("),
    re.compile(r"\bwhile\s*\("),
)

_OPERATOR_BRANCH_RE = re.compile(r"&&|\|\||\?(?!=)")

_IF_START = re.compile(r"(?:else\s+)?if\s*\(")
_SINGLE_EMPTY_IF = re.compile(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*\}\s*$")
_SINGLE_EMPTY_ELSE_IF = re.compile(r"else\s+if\s*\([^)]*\)\s*\{\s*\}\s*$")
_SINGLE_EMPTY_ELSE = re.compile(r"(?:\}\s*)?else\s*\{\s*\}\s*$")
_MULTI_IF_OPEN = re.compile(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*$")
_MULTI_ELSE_IF_OPEN = re.compile(r"\}\s*else\s+if\s*\([^)]*\)\s*\{\s*$")
_MULTI_ELSE_OPEN = re.compile(r"\}\s*else\s*\{\s*$")
_ELSE_CONT = re.compile(r"else\s")


def _emit(
    smell_counts: dict[str, list[dict]],
    key: str,
    ctx,
    line: int,
    content: str,
) -> None:
    """Append a smell issue."""
    smell_counts[key].append({"file": ctx.filepath, "line": line, "content": content})


def _find_function_start(line: str, next_lines: list[str]) -> str | None:
    """Return function name for declarations/assignments, else None."""
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith(("interface ", "type ", "enum ", "class ")):
        return None

    declaration_match = re.match(
        r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(",
        stripped,
    )
    if declaration_match:
        return declaration_match.group(1)

    assignment_match = re.match(
        r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b",
        stripped,
    )
    if not assignment_match:
        return None

    combined = "\n".join(
        [stripped] + [next_line.strip() for next_line in next_lines[:2]]
    )
    eq_pos = combined.find("=", assignment_match.end())
    if eq_pos == -1:
        return None
    after_eq = combined[eq_pos + 1 :].lstrip()
    if re.match(r"(?:async\s+)?\([^)]*\)\s*=>", after_eq):
        return assignment_match.group(1)
    if re.match(r"function\b", after_eq):
        return assignment_match.group(1)
    return None


def _find_opening_brace_line(
    lines: list[str], start: int, *, window: int = 5
) -> int | None:
    for idx in range(start, min(start + window, len(lines))):
        if "{" in lines[idx]:
            return idx
    return None


def _extract_function_body(
    lines: list[str],
    start_line: int,
    *,
    max_scan: int = 2000,
) -> str | None:
    """Extract the inner body text of a function starting at start_line."""
    segment = "\n".join(lines[start_line : min(start_line + max_scan, len(lines))])
    code = _code_text(segment)
    paren_depth = 0
    bracket_depth = 0
    signature_brace_depth = 0
    parameter_list_started = False
    parameters_closed = False
    previous_code_character = ""
    body_start: int | None = None

    for index, character in enumerate(code):
        if character == "(":
            parameter_list_started = True
            paren_depth += 1
        elif character == ")" and paren_depth > 0:
            paren_depth -= 1
            if parameter_list_started and paren_depth == 0:
                parameters_closed = True
        elif character == "[":
            bracket_depth += 1
        elif character == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif character == "{" and paren_depth == 0 and bracket_depth == 0:
            if not parameters_closed:
                # Generic constraints can contain object types before the parameter list.
                # They cannot be executable bodies for the function shapes detected here.
                pass
            elif signature_brace_depth > 0:
                signature_brace_depth += 1
            elif previous_code_character in ":<|&,(=[":
                # Object-shaped parameter/return types are part of the signature, not
                # the executable function body. Keep scanning after their matching brace.
                signature_brace_depth = 1
            else:
                body_start = index
                break
        elif character == "}" and signature_brace_depth > 0:
            signature_brace_depth -= 1

        if not character.isspace():
            previous_code_character = character

    if body_start is None:
        return None

    depth = 0
    for index in range(body_start, len(code)):
        character = code[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return segment[body_start + 1 : index]

    return None


def _count_pattern_in_body(body: str, pattern: re.Pattern[str]) -> int:
    """Count regex matches in body that are not inside string literals."""
    return len(pattern.findall(_code_text(body)))


def _compute_ts_cyclomatic_complexity(body: str) -> int:
    """Compute cyclomatic complexity for a TypeScript function body string."""
    stripped = _strip_ts_comments(body)
    complexity = 1
    for pattern in _TS_BRANCH_PATTERNS:
        complexity += len(pattern.findall(stripped))
    complexity += len(_OPERATOR_BRANCH_RE.findall(stripped))
    return complexity


__all__ = [
    "_ARROW_RE",
    "_CATCH_DEFAULT_FIELD_THRESHOLD",
    "_ELSE_CONT",
    "_ERROR_HANDLER_BASENAMES",
    "_FUNC_RE",
    "_HANDLED_RE",
    "_HIGH_CYCLOMATIC_THRESHOLD",
    "_IF_START",
    "_MAX_CATCH_BODY",
    "_MAX_SWITCH_BODY_SCAN",
    "_MONSTER_FUNCTION_LOC",
    "_MULTI_ELSE_IF_OPEN",
    "_MULTI_ELSE_OPEN",
    "_MULTI_IF_OPEN",
    "_NESTED_CLOSURE_THRESHOLD",
    "_PRECEDING_SKIP_PATTERNS",
    "_SINGLE_EMPTY_ELSE",
    "_SINGLE_EMPTY_ELSE_IF",
    "_SINGLE_EMPTY_IF",
    "_SWITCH_CASE_MINIMUM",
    "_count_pattern_in_body",
    "_compute_ts_cyclomatic_complexity",
    "_emit",
    "_extract_function_body",
    "_find_function_start",
    "_find_opening_brace_line",
]
