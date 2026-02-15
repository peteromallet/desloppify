"""Shared fixer utilities: bracket tracking, body extraction, fixer template."""

import os
import sys
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, c, rel
from ..detectors._smell_helpers import scan_code


def find_balanced_end(lines: list[str], start: int, *, track: str = "parens",
                      max_lines: int = 80) -> int | None:
    """Find the line where brackets opened at *start* balance to zero.

    Args:
        lines: Source lines (with newlines).
        start: 0-indexed starting line.
        track: Which brackets to track —
               ``"parens"`` (only ``()``),
               ``"braces"`` (only ``{}``),
               ``"all"`` (``()``, ``{}``, ``[]`` — returns when *parens* hit 0).
        max_lines: Give up after this many lines.

    Returns:
        0-indexed line number where depth returns to zero, or ``None``.
    """
    paren_depth = 0
    brace_depth = 0
    bracket_depth = 0

    for idx in range(start, min(start + max_lines, len(lines))):
        for _, ch, in_s in scan_code(lines[idx]):
            if in_s:
                continue
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
                if track == "parens" and paren_depth <= 0:
                    return idx
                if track == "all" and paren_depth <= 0:
                    return idx
            elif ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if track == "braces" and brace_depth <= 0:
                    return idx
            elif ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth -= 1
    return None


def extract_body_between_braces(text: str, search_after: str = "") -> str | None:
    """Extract content between the first ``{`` and its matching ``}``.

    If *search_after* is given, scanning starts after the first occurrence
    of that string (e.g. ``"=>"`` for arrow function bodies).

    Returns the inner text, or ``None`` if no balanced braces found.
    """
    start_pos = 0
    if search_after:
        pos = text.find(search_after)
        if pos == -1:
            return None
        start_pos = pos + len(search_after)

    brace_pos = text.find("{", start_pos)
    if brace_pos == -1:
        return None

    depth = 0
    for i, ch, in_s in scan_code(text, brace_pos):
        if in_s:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace_pos + 1:i]
    return None


def apply_fixer(entries: list[dict], transform_fn, *, dry_run: bool = False,
                file_key: str = "file") -> list[dict]:
    """Shared file-loop template for fixers.

    Groups *entries* by file, reads each file, calls
    ``transform_fn(lines, file_entries) -> (new_lines, removed_names)``
    and writes back if changed.

    Returns ``[{file, removed, lines_removed}, ...]``.
    """
    by_file: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_file[e[file_key]].append(e)

    results = []
    for filepath, file_entries in sorted(by_file.items()):
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            original = p.read_text()
            lines = original.splitlines(keepends=True)

            new_lines, removed_names = transform_fn(lines, file_entries)
            new_content = "".join(new_lines)

            if new_content != original:
                lines_removed = len(original.splitlines()) - len(new_content.splitlines())
                results.append({
                    "file": filepath,
                    "removed": removed_names,
                    "lines_removed": lines_removed,
                })
                if not dry_run:
                    tmp = p.with_suffix(p.suffix + ".tmp")
                    try:
                        tmp.write_text(new_content)
                        os.replace(str(tmp), str(p))
                    except BaseException:
                        tmp.unlink(missing_ok=True)
                        raise
        except (OSError, UnicodeDecodeError) as ex:
            print(c(f"  Skip {rel(filepath)}: {ex}", "yellow"), file=sys.stderr)

    return results


def collapse_blank_lines(lines: list[str], removed_indices: set[int] | None = None) -> list[str]:
    """Filter out removed lines and collapse double blank lines."""
    result = []
    prev_blank = False
    for idx, line in enumerate(lines):
        if removed_indices and idx in removed_indices:
            continue
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank
    return result
