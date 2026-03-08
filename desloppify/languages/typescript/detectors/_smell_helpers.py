"""Compatibility facade for TypeScript smell helper utilities."""

from __future__ import annotations

from typing import NamedTuple

from desloppify.base.text_utils import strip_c_style_comments
from desloppify.languages.typescript.detectors._smell_helpers_blocks import (
    _code_text,
    _content_line_info,
    _extract_block_body,
    _find_block_end,
    _track_brace_body,
)
from desloppify.languages.typescript.detectors._smell_helpers_line_state import (
    _build_ts_line_state,
    _scan_template_content,
)
from desloppify.languages.typescript.syntax.scanner import scan_code

__all__ = [
    "_FileContext",
    "_build_ts_line_state",
    "_code_text",
    "_content_line_info",
    "_extract_block_body",
    "_find_block_end",
    "_scan_template_content",
    "_strip_ts_comments",
    "_track_brace_body",
    "_ts_match_is_in_string",
    "scan_code",
]


class _FileContext(NamedTuple):
    """Per-file data bundle passed to all smell detectors."""

    filepath: str
    content: str
    lines: list[str]
    line_state: dict[int, str]


def _strip_ts_comments(text: str) -> str:
    """Strip // and /* */ comments while preserving strings."""
    return strip_c_style_comments(text)


def _ts_match_is_in_string(line: str, match_start: int) -> bool:
    """Check if a match position falls inside a string literal/comment on one line."""
    i = 0
    in_str = None

    while i < len(line):
        if i == match_start:
            return in_str is not None

        ch = line[i]

        if in_str and ch == "\\" and i + 1 < len(line):
            i += 2
            continue

        if in_str:
            if ch == in_str:
                in_str = None
            i += 1
            continue

        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return match_start > i

        if ch in ("'", '"', "`"):
            in_str = ch
            i += 1
            continue

        i += 1

    return False
