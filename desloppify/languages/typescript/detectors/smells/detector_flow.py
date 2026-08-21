"""Control-flow and function-shape TypeScript smell detectors."""

from __future__ import annotations

import os
import re

from .detector_core import (
    _ARROW_RE,
    _ELSE_CONT,
    _ERROR_HANDLER_BASENAMES,
    _FUNC_RE,
    _HANDLED_RE,
    _HIGH_CYCLOMATIC_THRESHOLD,
    _IF_START,
    _MONSTER_FUNCTION_LOC,
    _MULTI_ELSE_IF_OPEN,
    _MULTI_ELSE_OPEN,
    _MULTI_IF_OPEN,
    _NESTED_CLOSURE_THRESHOLD,
    _PRECEDING_SKIP_PATTERNS,
    _SINGLE_EMPTY_ELSE,
    _SINGLE_EMPTY_ELSE_IF,
    _SINGLE_EMPTY_IF,
    _count_pattern_in_body,
    _compute_ts_cyclomatic_complexity,
    _emit,
    _extract_function_body,
    _find_function_start,
    _find_opening_brace_line,
)
from .helpers import (
    _code_text,
    _extract_block_body,
    _strip_ts_comments,
    _track_brace_body,
)


def _extract_async_declaration_body(lines: list[str], index: int) -> str | None:
    """Extract an async declaration body without mistaking typed parameter braces for it."""
    fragment = "\n".join(lines[index : index + 2000])
    code = _code_text(fragment)
    opening_paren = code.find("(")
    if opening_paren == -1:
        return None

    paren_depth = 0
    closing_paren = None
    for cursor in range(opening_paren, len(code)):
        char = code[cursor]
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
            if paren_depth == 0:
                closing_paren = cursor
                break
    if closing_paren is None:
        return None

    cursor = closing_paren + 1
    while cursor < len(code) and code[cursor].isspace():
        cursor += 1
    has_return_type = cursor < len(code) and code[cursor] == ":"
    if has_return_type:
        cursor += 1
        while cursor < len(code) and code[cursor].isspace():
            cursor += 1
    direct_object_return = has_return_type and cursor < len(code) and code[cursor] == "{"

    angle_depth = 0
    square_depth = 0
    type_brace_depth = 0
    for body_cursor in range(cursor, len(code)):
        char = code[body_cursor]
        if char == "<" and type_brace_depth == 0:
            angle_depth += 1
        elif char == ">" and angle_depth > 0 and type_brace_depth == 0:
            angle_depth -= 1
        elif char == "[" and type_brace_depth == 0:
            square_depth += 1
        elif char == "]" and square_depth > 0 and type_brace_depth == 0:
            square_depth -= 1
        elif char == "{" and angle_depth == 0 and square_depth == 0:
            if direct_object_return or type_brace_depth > 0:
                type_brace_depth += 1
                direct_object_return = False
            else:
                return _extract_block_body(
                    fragment, body_cursor, max_scan=len(fragment) - body_cursor
                )
        elif char == "}" and type_brace_depth > 0:
            type_brace_depth -= 1
    return None


def _detect_async_no_await(ctx, smell_counts: dict[str, list[dict]]) -> None:
    """Find async functions that do not use await."""
    async_re = re.compile(r"(?:async\s+function\s+(\w+)|(\w+)\s*=\s*async)")
    for index, line in enumerate(ctx.lines):
        match = async_re.search(line)
        if not match:
            continue
        name = match.group(1) or match.group(2)
        body = (
            _extract_async_declaration_body(ctx.lines, index)
            if match.group(1)
            else _extract_function_body(ctx.lines, index)
        )
        if body is not None and not re.search(r"\bawait\b", _code_text(body)):
            _emit(
                smell_counts,
                "async_no_await",
                ctx,
                index + 1,
                f"async {name or '(anonymous)'} has no await",
            )


def _scan_single_line_chain(ctx, index: int, smell_counts: dict[str, list[dict]]) -> int:
    """Consume a single-line empty if/else-if chain and return next index."""
    cursor = index + 1
    while cursor < len(ctx.lines):
        stripped = ctx.lines[cursor].strip()
        if _SINGLE_EMPTY_ELSE_IF.match(stripped):
            cursor += 1
            continue
        if _SINGLE_EMPTY_ELSE.match(stripped):
            cursor += 1
            continue
        break
    _emit(smell_counts, "empty_if_chain", ctx, index + 1, ctx.lines[index].strip()[:100])
    return cursor


def _scan_multi_line_chain(ctx, index: int, smell_counts: dict[str, list[dict]]) -> int:
    """Consume a multi-line empty if/else chain and return next index."""
    chain_all_empty = True
    cursor = index
    while cursor < len(ctx.lines):
        current = ctx.lines[cursor].strip()
        if cursor == index:
            if not _MULTI_IF_OPEN.match(current):
                chain_all_empty = False
                break
        elif _MULTI_ELSE_IF_OPEN.match(current) or _MULTI_ELSE_OPEN.match(current):
            pass
        elif current == "}":
            tail = cursor + 1
            while tail < len(ctx.lines) and ctx.lines[tail].strip() == "":
                tail += 1
            if tail < len(ctx.lines) and _ELSE_CONT.match(ctx.lines[tail].strip()):
                cursor = tail
                continue
            cursor += 1
            break
        elif current == "":
            cursor += 1
            continue
        else:
            chain_all_empty = False
            break
        cursor += 1

    if chain_all_empty and cursor > index + 1:
        _emit(smell_counts, "empty_if_chain", ctx, index + 1, ctx.lines[index].strip()[:100])
    return max(index + 1, cursor)


def _detect_empty_if_chains(ctx, smell_counts: dict[str, list[dict]]) -> None:
    """Find if/else chains where all branches are empty."""
    index = 0
    while index < len(ctx.lines):
        stripped = ctx.lines[index].strip()
        if not _IF_START.match(stripped):
            index += 1
            continue
        if _SINGLE_EMPTY_IF.match(stripped):
            index = _scan_single_line_chain(ctx, index, smell_counts)
            continue
        if _MULTI_IF_OPEN.match(stripped):
            index = _scan_multi_line_chain(ctx, index, smell_counts)
            continue
        index += 1


def _detect_error_no_throw(ctx, smell_counts: dict[str, list[dict]]) -> None:
    """Find console.error calls not followed by throw/return or handling."""
    basename = os.path.basename(ctx.filepath).lower()
    basename_no_ext = os.path.splitext(basename)[0]
    if any(tag in basename_no_ext for tag in _ERROR_HANDLER_BASENAMES):
        return

    for index, line in enumerate(ctx.lines):
        if "console.error" not in line:
            continue
        preceding = "\n".join(ctx.lines[max(0, index - 10) : index])
        if _PRECEDING_SKIP_PATTERNS.search(preceding):
            continue
        following = "\n".join(ctx.lines[index + 1 : index + 4])
        if not _HANDLED_RE.search(following):
            _emit(smell_counts, "console_error_no_throw", ctx, index + 1, line.strip()[:100])


def _detect_high_cyclomatic_complexity(ctx, smell_counts: dict[str, list[dict]]) -> None:
    """Flag functions with cyclomatic complexity > 15."""
    for index, line in enumerate(ctx.lines):
        name = _find_function_start(line, ctx.lines[index + 1 : index + 3])
        if not name:
            continue
        body = _extract_function_body(ctx.lines, index)
        if body is None:
            continue
        complexity = _compute_ts_cyclomatic_complexity(body)
        if complexity > _HIGH_CYCLOMATIC_THRESHOLD:
            _emit(
                smell_counts,
                "high_cyclomatic_complexity",
                ctx,
                index + 1,
                f"{name}() — cyclomatic complexity {complexity}",
            )


def _detect_monster_functions(ctx, smell_counts: dict[str, list[dict]]) -> None:
    """Find functions/components exceeding 150 LOC via brace tracking."""
    for index, line in enumerate(ctx.lines):
        name = _find_function_start(line, ctx.lines[index + 1 : index + 3])
        if not name:
            continue
        brace_line = _find_opening_brace_line(ctx.lines, index, window=5)
        if brace_line is None:
            continue
        end_line = _track_brace_body(ctx.lines, brace_line, max_scan=2000)
        if end_line is None:
            continue
        loc = end_line - index + 1
        if loc > _MONSTER_FUNCTION_LOC:
            _emit(smell_counts, "monster_function", ctx, index + 1, f"{name}() — {loc} LOC")


def _detect_nested_closures(ctx, smell_counts: dict[str, list[dict]]) -> None:
    """Find functions with many nested closure definitions."""
    for index, line in enumerate(ctx.lines):
        name = _find_function_start(line, ctx.lines[index + 1 : index + 3])
        if not name:
            continue
        body = _extract_function_body(ctx.lines, index)
        if body is None:
            continue
        closure_count = _count_pattern_in_body(body, _FUNC_RE) + _count_pattern_in_body(
            body,
            _ARROW_RE,
        )
        if closure_count >= _NESTED_CLOSURE_THRESHOLD:
            _emit(
                smell_counts,
                "nested_closure",
                ctx,
                index + 1,
                f"{name}() — {closure_count} nested closures",
            )


def _detect_stub_functions(ctx, smell_counts: dict[str, list[dict]]) -> None:
    """Find functions with empty or return-only bodies."""
    for index, line in enumerate(ctx.lines):
        if index > 0 and ctx.lines[index - 1].strip().startswith("@"):
            continue
        name = _find_function_start(line, ctx.lines[index + 1 : index + 3])
        if not name:
            continue
        body = _extract_function_body(ctx.lines, index, max_scan=30)
        if body is None:
            continue
        body_clean = _strip_ts_comments(body).strip().rstrip(";")
        if body_clean in ("", "return", "return null", "return undefined"):
            label = body_clean or "empty"
            _emit(smell_counts, "stub_function", ctx, index + 1, f"{name}() — body is {label}")


__all__ = [
    "_detect_async_no_await",
    "_detect_empty_if_chains",
    "_detect_error_no_throw",
    "_detect_high_cyclomatic_complexity",
    "_detect_monster_functions",
    "_detect_nested_closures",
    "_detect_stub_functions",
    "_scan_multi_line_chain",
    "_scan_single_line_chain",
]
