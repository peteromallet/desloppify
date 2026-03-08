"""Line-state scanners for block comments and template literals."""

from __future__ import annotations


def _scan_template_content(
    line: str, start: int, brace_depth: int = 0
) -> tuple[int, bool, int]:
    """Scan template literal content from *start* in *line*."""
    j = start
    while j < len(line):
        ch = line[j]
        if ch == "\\" and j + 1 < len(line):
            j += 2
            continue
        if ch == "$" and j + 1 < len(line) and line[j + 1] == "{":
            brace_depth += 1
            j += 2
            continue
        if ch == "}" and brace_depth > 0:
            brace_depth -= 1
            j += 1
            continue
        if ch == "`" and brace_depth == 0:
            return (j + 1, True, brace_depth)
        j += 1
    return (j, False, brace_depth)


def _scan_code_line(line: str) -> tuple[bool, bool, int]:
    """Scan a normal code line for block comment or template literal start."""
    j = 0
    in_str = None
    while j < len(line):
        ch = line[j]

        if in_str and ch == "\\" and j + 1 < len(line):
            j += 2
            continue

        if in_str:
            if ch == in_str:
                in_str = None
            j += 1
            continue

        if ch == "/" and j + 1 < len(line) and line[j + 1] == "/":
            break

        if ch == "/" and j + 1 < len(line) and line[j + 1] == "*":
            close = line.find("*/", j + 2)
            if close != -1:
                j = close + 2
                continue
            return (True, False, 0)

        if ch == "`":
            end_pos, found_close, depth = _scan_template_content(line, j + 1)
            if found_close:
                j = end_pos
                continue
            return (False, True, depth)

        if ch in ("'", '"'):
            in_str = ch
            j += 1
            continue

        j += 1

    return (False, False, 0)


def _build_ts_line_state(lines: list[str]) -> dict[int, str]:
    """Build a map of lines inside block comments or template literals."""
    state: dict[int, str] = {}
    in_block_comment = False
    in_template = False
    template_brace_depth = 0

    for i, line in enumerate(lines):
        if in_block_comment:
            state[i] = "block_comment"
            if "*/" in line:
                in_block_comment = False
            continue

        if in_template:
            state[i] = "template_literal"
            _, found_close, template_brace_depth = _scan_template_content(
                line, 0, template_brace_depth
            )
            if found_close:
                in_template = False
            continue

        in_block_comment, in_template, depth = _scan_code_line(line)
        if in_template:
            template_brace_depth = depth

    return state


__all__ = [
    "_build_ts_line_state",
    "_scan_code_line",
    "_scan_template_content",
]
