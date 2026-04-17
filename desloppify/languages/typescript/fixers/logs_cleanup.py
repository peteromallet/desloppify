"""Cleanup helpers for the TypeScript debug logs fixer."""

from __future__ import annotations

import re

from desloppify.languages.typescript.fixers.syntax_scan import (
    extract_body_between_braces,
    find_balanced_end,
)

_DEBUG_COMMENT_RE = re.compile(
    r"(?:DEBUG|TEMP|LOG|TRACE|TODO\s*.*debug|HACK\s*.*log)", re.IGNORECASE
)

_VAR_DECL_RE = re.compile(r"^\s*(?:const|let|var)\s+(\w+)\s*=")
_IDENT_RE = re.compile(r"\b([a-zA-Z_$]\w*)\b")

_IGNORE_IDENTS = frozenset(
    [
        "console",
        "log",
        "warn",
        "info",
        "debug",
        "error",
        "const",
        "let",
        "var",
        "true",
        "false",
        "null",
        "undefined",
        "if",
        "else",
        "return",
        "function",
        "new",
        "this",
        "typeof",
        "length",
        "toString",
        "JSON",
        "stringify",
        "Date",
        "now",
        "Math",
        "Object",
        "Array",
        "String",
        "Number",
        "Boolean",
        "Map",
        "Set",
        "Promise",
        "Error",
    ]
)

_EMPTY_BLOCK_RE = re.compile(
    r"""
    ^(\s*)
    (?:
        (?:if|else\s+if)\s*\([^)]*\)\s*\{\s*\}
        | else\s*\{\s*\}
        | \}\s*else\s*\{\s*\}
    )
    \s*$
    """,
    re.VERBOSE,
)

_EMPTY_CALLBACK_RE = re.compile(
    r"""
    ^\s*
    (?:
        \.then\s*\(\s*\(?[^)]*\)?\s*=>\s*\{\s*\}\s*\)
        | \.catch\s*\(\s*\(?[^)]*\)?\s*=>\s*\{\s*\}\s*\)
    )
    \s*[;,]?\s*$
    """,
    re.VERBOSE,
)


def mark_orphaned_comments(lines: list[str], log_start: int, lines_to_remove: set[int]) -> None:
    """Mark up to 3 preceding comment lines as orphaned if debug-tagged."""
    for offset in range(1, 4):
        idx = log_start - offset
        if idx < 0:
            break
        if idx in lines_to_remove:
            continue
        prev = lines[idx].strip()
        if not prev.startswith("//"):
            break
        if _DEBUG_COMMENT_RE.search(prev):
            lines_to_remove.add(idx)


def find_dead_log_variables(lines: list[str], removed_indices: set[int]) -> set[int]:
    """Find variable declarations that were only used in removed log lines."""
    referenced_in_logs: set[str] = set()
    for idx in removed_indices:
        if idx < len(lines):
            for match in _IDENT_RE.finditer(lines[idx]):
                ident = match.group(1)
                if ident not in _IGNORE_IDENTS:
                    referenced_in_logs.add(ident)

    if not referenced_in_logs:
        return set()

    decl_lines: dict[str, int] = {}
    for idx, line in enumerate(lines):
        if idx in removed_indices:
            continue
        match = _VAR_DECL_RE.match(line)
        if match and match.group(1) in referenced_in_logs:
            decl_lines[match.group(1)] = idx

    if not decl_lines:
        return set()

    dead: set[int] = set()
    for ident, decl_idx in decl_lines.items():
        used_elsewhere = False
        pattern = re.compile(r"\b" + re.escape(ident) + r"\b")
        for idx, line in enumerate(lines):
            if idx == decl_idx or idx in removed_indices:
                continue
            if pattern.search(line):
                used_elsewhere = True
                break
        if not used_elsewhere:
            dead.add(decl_idx)

    return dead


def _try_remove_empty_use_effect(
    lines: list[str], i: int, new_lines: list[str]
) -> int | None:
    """Remove empty useEffect(() => { }). Returns new index or None."""
    stripped = lines[i].strip()
    if not re.match(r"(?:React\.)?useEffect\s*\(\s*\(\s*\)\s*=>\s*\{", stripped):
        return None
    end = find_balanced_end(lines, i, track="all")
    if end is None:
        return None
    body = "".join(lines[i : end + 1])
    inner = extract_body_between_braces(body, search_after="=>")
    if inner is None or inner.strip() != "":
        return None
    if new_lines and new_lines[-1].strip().startswith("//"):
        new_lines.pop()
    return end + 1


def _try_remove_empty_callback(lines: list[str], i: int) -> int | None:
    """Remove single-line .then(() => { }) / .catch((e) => { })."""
    if _EMPTY_CALLBACK_RE.match(lines[i].strip()):
        return i + 1
    return None


def _try_remove_multiline_callback(lines: list[str], i: int) -> int | None:
    """Remove multi-line empty callback: someFunc(() => {\n})."""
    stripped = lines[i].strip()
    if not re.search(r"=>\s*\{\s*$", stripped):
        return None
    if not re.search(r"\(\s*(?:\([^)]*\))?\s*=>\s*\{\s*$", stripped):
        return None
    j = i + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j < len(lines) and lines[j].strip() in ("});", "},"):
        return j + 1
    return None


def _try_remove_multiline_block(
    lines: list[str], i: int, new_lines: list[str]
) -> int | None:
    """Remove multi-line empty if/else/else-if blocks."""
    line = lines[i]
    stripped = line.strip()
    if not stripped.endswith("{"):
        return None
    j = i + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j >= len(lines) or lines[j].strip() not in ("}", "});"):
        return None

    if re.match(r"\s*else\s*\{", stripped):
        return j + 1
    if re.match(r"\s*\}\s*else\s*\{", stripped):
        indent = line[: len(line) - len(line.lstrip())]
        new_lines.append(f"{indent}}}\n")
        return j + 1
    if re.match(r"\s*(?:if|else\s+if)\s*\(", stripped):
        next_line_idx = j + 1
        while next_line_idx < len(lines) and lines[next_line_idx].strip() == "":
            next_line_idx += 1
        if next_line_idx < len(lines):
            next_stripped = lines[next_line_idx].strip()
            if next_stripped.startswith("else"):
                return None
        return j + 1
    return None


def _try_remove_single_empty_block(lines: list[str], i: int) -> int | None:
    """Remove single-line empty block (if/else/else-if with empty {})."""
    if _EMPTY_BLOCK_RE.match(lines[i].strip()):
        return i + 1
    return None


def remove_empty_blocks(lines: list[str]) -> list[str]:
    """Remove empty blocks left behind after log removal."""
    handlers = [
        lambda src, idx, out: _try_remove_empty_use_effect(src, idx, out),
        lambda src, idx, _out: _try_remove_empty_callback(src, idx),
        lambda src, idx, _out: _try_remove_multiline_callback(src, idx),
        lambda src, idx, out: _try_remove_multiline_block(src, idx, out),
        lambda src, idx, _out: _try_remove_single_empty_block(src, idx),
    ]
    changed = True
    while changed:
        changed = False
        new_lines: list[str] = []
        i = 0
        while i < len(lines):
            new_i = None
            for handler in handlers:
                new_i = handler(lines, i, new_lines)
                if new_i is not None:
                    break
            if new_i is not None:
                changed = True
                i = new_i
            else:
                new_lines.append(lines[i])
                i += 1
        lines = new_lines

    result = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank
    return result


__all__ = ["find_dead_log_variables", "mark_orphaned_comments", "remove_empty_blocks"]
