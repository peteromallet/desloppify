"""Debug log fixer: removes tagged console.log lines and cleans up aftermath."""

import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.languages.typescript.fixers.common import (
    collapse_blank_lines,
    extract_body_between_braces,
    find_balanced_end,
)
from desloppify.utils import PROJECT_ROOT, c, rel, safe_write_text

logger = logging.getLogger(__name__)


def fix_debug_logs(entries: list[dict], *, dry_run: bool = False) -> list[dict]:
    """Remove tagged console.log lines from source files.

    Handles multi-line console.log calls by tracking open parens.

    Args:
        entries: Output of detect_logs() — [{file, line, tag, content}].
        dry_run: If True, don't write files.

    Returns:
        List of {file, tags: [str], lines_removed: int} dicts.
    """
    by_file: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_file[e["file"]].append(e)

    results = []
    skipped_files: list[tuple[str, str]] = []
    for filepath, file_entries in sorted(by_file.items()):
        try:
            p = (
                Path(filepath)
                if Path(filepath).is_absolute()
                else PROJECT_ROOT / filepath
            )
            original = p.read_text()
            lines = original.splitlines(keepends=True)

            lines_to_remove: set[int] = set()  # 0-indexed
            for e in file_entries:
                start = e["line"] - 1  # convert to 0-indexed
                if start >= len(lines):
                    continue
                # Find the extent of this console.log call (may span lines)
                end = find_balanced_end(lines, start, track="parens")
                if end is None:
                    print(
                        c(
                            f"  Warn: skipping {rel(filepath)}:{e['line']} — could not find statement end",
                            "yellow",
                        ),
                        file=sys.stderr,
                    )
                    continue
                for idx in range(start, end + 1):
                    lines_to_remove.add(idx)
                # Remove preceding debug annotation comments (up to 3 lines)
                _mark_orphaned_comments(lines, start, lines_to_remove)

            # Find variable declarations only used in removed log lines
            dead_vars = _find_dead_log_variables(lines, lines_to_remove)
            lines_to_remove |= dead_vars

            new_lines = collapse_blank_lines(lines, lines_to_remove)

            # Second pass: remove empty blocks left behind
            new_lines = _remove_empty_blocks(new_lines)

            new_content = "".join(new_lines)
            if new_content != original:
                tags = sorted(set(e["tag"] for e in file_entries))
                removed = len(lines) - len(new_lines)
                results.append(
                    {
                        "file": filepath,
                        "tags": tags,
                        "lines_removed": removed,
                        "log_count": len(file_entries),
                    }
                )
                if not dry_run:
                    safe_write_text(filepath, new_content)
        except (OSError, UnicodeDecodeError) as ex:
            skipped_files.append((filepath, str(ex)))
            print(c(f"  Skip {rel(filepath)}: {ex}", "yellow"), file=sys.stderr)

    if skipped_files:
        log_best_effort_failure(
            logger,
            f"apply debug-log fixer across {len(skipped_files)} skipped file(s)",
            OSError(
                "; ".join(f"{path}: {reason}" for path, reason in skipped_files[:5])
            ),
        )

    return results


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


def _remove_empty_blocks(lines: list[str]) -> list[str]:
    """Remove empty blocks left behind after log removal.

    Handles: empty if/else, empty useEffect, empty catch, empty callbacks.
    Makes multiple passes until stable.
    """
    changed = True
    while changed:
        changed = False
        new_lines: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # ── Empty useEffect / React.useEffect ──
            if re.match(r"(?:React\.)?useEffect\s*\(\s*\(\s*\)\s*=>\s*\{", stripped):
                end = find_balanced_end(lines, i, track="all")
                if end is not None:
                    body = "".join(lines[i : end + 1])
                    inner = extract_body_between_braces(body, search_after="=>")
                    if inner is not None and inner.strip() == "":
                        if new_lines and new_lines[-1].strip().startswith("//"):
                            new_lines.pop()
                        changed = True
                        i = end + 1
                        continue

            # ── Empty callback: .then(() => { }) or .catch((e) => { }) ──
            if _EMPTY_CALLBACK_RE.match(stripped):
                changed = True
                i += 1
                continue

            # ── Multi-line empty callback: someFunc(() => {\n}) ──
            if re.search(r"=>\s*\{\s*$", stripped):
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                if j < len(lines) and lines[j].strip() in ("}", "})", "});", "},"):
                    if re.search(r"\(\s*(?:\([^)]*\))?\s*=>\s*\{\s*$", stripped):
                        closing = lines[j].strip()
                        if closing in ("});", "},"):
                            changed = True
                            i = j + 1
                            continue

            # ── Multi-line empty block ──
            if stripped.endswith("{"):
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                if j < len(lines) and lines[j].strip() in ("}", "});"):
                    if re.match(r"\s*else\s*\{", stripped):
                        changed = True
                        i = j + 1
                        continue
                    if re.match(r"\s*\}\s*else\s*\{", stripped):
                        indent = line[: len(line) - len(line.lstrip())]
                        new_lines.append(f"{indent}}}\n")
                        changed = True
                        i = j + 1
                        continue
                    if re.match(r"\s*(?:if|else\s+if)\s*\(", stripped):
                        changed = True
                        i = j + 1
                        continue

            # ── Single-line empty block ──
            if _EMPTY_BLOCK_RE.match(stripped):
                changed = True
                i += 1
                continue

            new_lines.append(line)
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
