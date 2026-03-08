"""Block parsing and code-text projection helpers for TS smell detectors."""

from __future__ import annotations

from desloppify.languages.typescript.syntax.scanner import scan_code


def _track_brace_body(
    lines: list[str], start_line: int, *, max_scan: int = 2000
) -> int | None:
    """Find the closing brace matching the first opening brace from start_line."""
    depth = 0
    found_open = False
    for line_idx in range(start_line, min(start_line + max_scan, len(lines))):
        for _, ch, in_string in scan_code(lines[line_idx]):
            if in_string:
                continue
            if ch == "{":
                depth += 1
                found_open = True
            elif ch == "}":
                depth -= 1
                if found_open and depth == 0:
                    return line_idx
    return None


def _find_block_end(content: str, brace_start: int, max_scan: int = 5000) -> int | None:
    """Find the closing brace position in a content string from an opening brace."""
    depth = 0
    for ci, ch, in_s in scan_code(
        content, brace_start, min(brace_start + max_scan, len(content))
    ):
        if in_s:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return ci
    return None


def _extract_block_body(
    content: str, brace_start: int, max_scan: int = 5000
) -> str | None:
    """Return text between ``{`` at brace_start and its matching ``}``."""
    end = _find_block_end(content, brace_start, max_scan)
    if end is None:
        return None
    return content[brace_start + 1 : end]


def _content_line_info(content: str, pos: int) -> tuple[int, str]:
    """Return ``(line_no, stripped snippet[:100])`` for a position in content."""
    line_no = content[:pos].count("\n") + 1
    line_start = content.rfind("\n", 0, pos) + 1
    line_end = content.find("\n", pos)
    if line_end == -1:
        line_end = len(content)
    return line_no, content[line_start:line_end].strip()[:100]


def _code_text(text: str) -> str:
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
    "_code_text",
    "_content_line_info",
    "_extract_block_body",
    "_find_block_end",
    "_track_brace_body",
    "scan_code",
]
