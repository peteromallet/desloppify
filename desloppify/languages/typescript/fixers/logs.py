"""Debug log fixer: removes tagged console.log lines and cleans up aftermath."""

import re
import sys

from desloppify.languages.typescript.fixers.common import (
    apply_fixer,
    collapse_blank_lines,
    extract_body_between_braces,
    find_balanced_end,
)
from desloppify.file_discovery import rel
from desloppify.utils import colorize


def fix_debug_logs(entries: list[dict], *, dry_run: bool = False) -> list[dict]:
    """Remove tagged console.log lines and clean up aftermath (dead vars, empty blocks)."""
    entries_by_file: dict[str, list[dict]] = {}
    for e in entries:
        entries_by_file.setdefault(e["file"], []).append(e)

    def _transform(lines: list[str], file_entries: list[dict]):
        lines_to_remove: set[int] = set()
        for e in file_entries:
            start = e["line"] - 1
            if start >= len(lines):
                continue
            end = find_balanced_end(lines, start, track="parens")
            if end is None:
                print(
                    colorize(
                        f"  Warn: skipping {rel(e['file'])}:{e['line']} — could not find statement end",
                        "yellow",
                    ),
                    file=sys.stderr,
                )
                continue
            for idx in range(start, end + 1):
                lines_to_remove.add(idx)
            _mark_orphaned_comments(lines, start, lines_to_remove)

        dead_vars = _find_dead_log_variables(lines, lines_to_remove)
        lines_to_remove |= dead_vars
        new_lines = collapse_blank_lines(lines, lines_to_remove)
        new_lines = _remove_empty_blocks(new_lines)
        tags = sorted(set(e.get("tag", "") for e in file_entries))
        return new_lines, tags

    raw_results = apply_fixer(entries, _transform, dry_run=dry_run)
    return [
        {
            "file": r["file"],
            "removed": r["removed"],
            "tags": r["removed"],
            "lines_removed": r["lines_removed"],
            "log_count": len(entries_by_file.get(r["file"], [])),
        }
        for r in raw_results
    ]


# ── Orphaned comment cleanup ──────────────────────────────

_DEBUG_COMMENT_RE = re.compile(
    r"(?:DEBUG|TEMP|LOG|TRACE|TODO\s*.*debug|HACK\s*.*log)", re.IGNORECASE
)


def _mark_orphaned_comments(
    lines: list[str], log_start: int, lines_to_remove: set[int]
):
    """Mark up to 3 preceding comment lines as orphaned if they contain debug annotations."""
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


# ── Dead variable detection ──────────────────────────────

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


def _find_dead_log_variables(lines: list[str], removed_indices: set[int]) -> set[int]:
    """Find variable declarations that were only used in removed log lines."""
    referenced_in_logs: set[str] = set()
    for idx in removed_indices:
        if idx < len(lines):
            for m in _IDENT_RE.finditer(lines[idx]):
                ident = m.group(1)
                if ident not in _IGNORE_IDENTS:
                    referenced_in_logs.add(ident)

    if not referenced_in_logs:
        return set()

    decl_lines: dict[str, int] = {}
    for idx, line in enumerate(lines):
        if idx in removed_indices:
            continue
        m = _VAR_DECL_RE.match(line)
        if m and m.group(1) in referenced_in_logs:
            decl_lines[m.group(1)] = idx

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


# ── Empty block cleaner ────────────────────────────────────

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
    """Remove multi-line empty callback: someFunc(() => {\\n})."""
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
        return j + 1
    return None


def _try_remove_single_empty_block(lines: list[str], i: int) -> int | None:
    """Remove single-line empty block (if/else/else-if with empty {})."""
    if _EMPTY_BLOCK_RE.match(lines[i].strip()):
        return i + 1
    return None


def _remove_empty_blocks(lines: list[str]) -> list[str]:
    """Remove empty blocks left behind after log removal.

    Handles: empty if/else, empty useEffect, empty catch, empty callbacks.
    Makes multiple passes until stable.
    """
    _handlers = [
        lambda lines, i, out: _try_remove_empty_use_effect(lines, i, out),
        lambda lines, i, out: _try_remove_empty_callback(lines, i),
        lambda lines, i, out: _try_remove_multiline_callback(lines, i),
        lambda lines, i, out: _try_remove_multiline_block(lines, i, out),
        lambda lines, i, out: _try_remove_single_empty_block(lines, i),
    ]
    changed = True
    while changed:
        changed = False
        new_lines: list[str] = []
        i = 0
        while i < len(lines):
            new_i = None
            for handler in _handlers:
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

    # Final pass: collapse double blank lines
    result = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank
    return result
