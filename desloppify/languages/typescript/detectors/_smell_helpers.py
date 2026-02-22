"""Multi-line smell detection helpers (brace-tracked).

Shared utilities (string-aware scanning, brace tracking, comment stripping)
plus a handful of smell detectors. Monster-function, dead-function,
window-global, catch-return-default, and switch-no-default detectors live
in _smell_detectors.py.
"""

from __future__ import annotations

import re
from collections.abc import Generator

from desloppify.languages.typescript.detectors._smell_effects import (
    detect_dead_useeffects as _detect_dead_useeffects_impl,
)
from desloppify.languages.typescript.detectors._smell_effects import (
    detect_empty_if_chains as _detect_empty_if_chains_impl,
)
from desloppify.languages.typescript.detectors._smell_effects import (
    detect_error_no_throw as _detect_error_no_throw_impl,
)
from desloppify.languages.typescript.detectors._smell_effects import (
    detect_swallowed_errors as _detect_swallowed_errors_impl,
)
from desloppify.languages.typescript.detectors._smell_effects import (
    track_brace_body as _track_brace_body_impl,
)
from desloppify.core._internal.text_utils import strip_c_style_comments


def scan_code(
    text: str, start: int = 0, end: int | None = None
) -> Generator[tuple[int, str, bool], None, None]:
    """Yield (index, char, in_string) tuples, handling escapes correctly.

    Skips escaped characters (\\x) by advancing +2 instead of +1.
    Tracks single-quoted, double-quoted, and template literal strings.
    Correct for \\\\\" (escaped backslash before quote) where prev_ch pattern fails.
    """
    i = start
    limit = end if end is not None else len(text)
    in_str = None
    while i < limit:
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < limit:
                yield (i, ch, True)
                i += 1
                yield (i, text[i], True)
                i += 1
                continue
            if ch == in_str:
                in_str = None
            yield (i, ch, in_str is not None)
        else:
            if ch in ("'", '"', "`"):
                in_str = ch
                yield (i, ch, True)
            else:
                yield (i, ch, False)
        i += 1


def _strip_ts_comments(text: str) -> str:
    """Strip // and /* */ comments while preserving strings.

    Delegates to the shared implementation in utils.py.
    """
    return strip_c_style_comments(text)


def _ts_match_is_in_string(line: str, match_start: int) -> bool:
    """Check if a match position falls inside a string literal or comment on a single line.

    Mirrors Python's _match_is_in_string but for TS syntax (', ", `, //).
    """
    i = 0
    in_str = None

    while i < len(line):
        if i == match_start:
            return in_str is not None

        ch = line[i]

        # Escape sequences inside strings
        if in_str and ch == "\\" and i + 1 < len(line):
            i += 2
            continue

        if in_str:
            if ch == in_str:
                in_str = None
            i += 1
            continue

        # Line comment — everything after is non-code
        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return match_start > i

        if ch in ("'", '"', "`"):
            in_str = ch
            i += 1
            continue

        i += 1

    return False


def _detect_async_no_await(
    filepath: str, content: str, lines: list[str], smell_counts: dict[str, list[dict]]
):
    """Find async functions that don't use await.

    Algorithm: for each async declaration, track brace depth to find the function
    body extent (up to 200 lines). Scan each line for 'await' within those braces.
    If the opening brace closes (depth returns to 0) without seeing await, flag it.
    """
    async_re = re.compile(r"(?:async\s+function\s+(\w+)|(\w+)\s*=\s*async)")
    for i, line in enumerate(lines):
        m = async_re.search(line)
        if not m:
            continue
        name = m.group(1) or m.group(2)
        brace_depth = 0
        found_open = False
        has_await = False
        for j in range(i, min(i + 200, len(lines))):
            body_line = lines[j]
            prev_code_ch = ""
            for _, ch, in_s in scan_code(body_line):
                if in_s:
                    continue
                if ch == "/" and prev_code_ch == "/":
                    break  # Rest of line is comment
                elif ch == "{":
                    brace_depth += 1
                    found_open = True
                elif ch == "}":
                    brace_depth -= 1
                prev_code_ch = ch
            if "await " in body_line or "await\n" in body_line:
                has_await = True
            if found_open and brace_depth <= 0:
                break

        if found_open and not has_await:
            smell_counts["async_no_await"].append(
                {
                    "file": filepath,
                    "line": i + 1,
                    "content": f"async {name or '(anonymous)'} has no await",
                }
            )


def _detect_error_no_throw(
    filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]
):
    """Find console.error calls not followed by throw or return."""
    _detect_error_no_throw_impl(filepath, lines, smell_counts)


def _detect_empty_if_chains(
    filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]
):
    """Find if/else chains where all branches are empty."""
    _detect_empty_if_chains_impl(filepath, lines, smell_counts)


def _detect_dead_useeffects(
    filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]
):
    """Find useEffect calls with empty or whitespace/comment-only bodies.

    Algorithm: two-pass brace/paren tracking with string-escape awareness.
    Pass 1: track paren depth to find the full useEffect(...) extent.
    Pass 2: within that extent, find the arrow body ({...} after =>) using
    brace depth, skipping characters inside string literals (', ", `).
    Then strip comments from the body and check if anything remains.
    """
    _detect_dead_useeffects_impl(
        filepath,
        lines,
        smell_counts,
        scan_code_fn=scan_code,
        strip_ts_comments_fn=_strip_ts_comments,
    )


def _detect_swallowed_errors(
    filepath: str, content: str, lines: list[str], smell_counts: dict[str, list[dict]]
):
    """Find catch blocks whose only content is console.error/warn/log (swallowed errors).

    Algorithm: regex-find each `catch(...) {`, then track brace depth with
    string-escape awareness to extract the catch body (up to 500 chars).
    Strip comments, split into statements, and check if every statement
    is a console.error/warn/log call.
    """
    _detect_swallowed_errors_impl(
        filepath,
        content,
        lines,
        smell_counts,
        scan_code_fn=scan_code,
        strip_ts_comments_fn=_strip_ts_comments,
    )


def _track_brace_body(
    lines: list[str], start_line: int, *, max_scan: int = 2000
) -> int | None:
    """Find the closing brace that matches the first opening brace from start_line.

    Tracks brace depth with string-literal awareness (', ", `).
    Returns the line index of the closing brace, or None if not found.
    """
    return _track_brace_body_impl(
        lines,
        start_line,
        scan_code_fn=scan_code,
        max_scan=max_scan,
    )
