"""JavaScript/TypeScript-oriented text helpers.

These helpers are intentionally framework-agnostic and live under the shared
Node layer so they can be used by framework scanners across JS/TS plugins.
"""

from __future__ import annotations

from collections.abc import Generator

from desloppify.base.text_utils import strip_c_style_comments


def strip_js_ts_comments(text: str) -> str:
    """Strip // and /* */ comments while preserving string literals."""
    return strip_c_style_comments(text)


def scan_code(text: str) -> Generator[tuple[int, str, bool], None, None]:
    """Yield ``(index, char, in_string)`` tuples while handling escapes."""
    i = 0
    in_str = None
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\" and i + 1 < len(text):
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


def code_text(text: str) -> str:
    """Blank string literals and ``//`` comments to spaces, preserving positions."""
    out = list(text)
    in_line_comment = False
    prev_code_idx = -2
    prev_code_ch = ""
    for i, ch, in_s in scan_code(text):
        if ch == "\n":
            in_line_comment = False
            prev_code_ch = ""
            continue
        if in_line_comment:
            out[i] = " "
            continue
        if in_s:
            out[i] = " "
            continue
        if ch == "/" and prev_code_ch == "/" and prev_code_idx == i - 1:
            out[prev_code_idx] = " "
            out[i] = " "
            in_line_comment = True
            prev_code_ch = ""
            continue
        prev_code_idx = i
        prev_code_ch = ch
    return "".join(out)


__all__ = [
    "code_text",
    "scan_code",
    "strip_js_ts_comments",
]

