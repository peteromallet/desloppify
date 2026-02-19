"""Unused vars fixer: removes unused names from destructuring patterns + standalone vars."""

import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.languages.typescript.fixers.common import collapse_blank_lines
from desloppify.utils import PROJECT_ROOT, c, rel, safe_write_text

_DESTR_MEMBER_RE = re.compile(r"^\s*(\w+)\s*(?:=\s*[^,]+)?\s*,?\s*$")
_REST_ELEMENT_RE = re.compile(r"\.\.\.\w+")
logger = logging.getLogger(__name__)


def _record_direct_var_removal(
    stripped: str,
    line_idx: int,
    name: str,
    *,
    lines_to_remove: set[int],
    removed_names: list[str],
    skip_reasons: dict[str, int],
) -> bool:
    if not re.match(r"\s*(?:const|let|var)\s+\w+\s*=", stripped):
        return False
    rhs = stripped.split("=", 1)[1] if "=" in stripped else ""
    if stripped.rstrip().endswith(";") and "(" not in rhs:
        lines_to_remove.add(line_idx)
        removed_names.append(name)
    else:
        skip_reasons["standalone_var_with_call"] += 1
    return True


def _handle_unused_entry(
    entry: dict,
    *,
    lines: list[str],
    lines_to_remove: set[int],
    inline_removals: dict[int, set[str]],
    removed_names: list[str],
    skip_reasons: dict[str, int],
) -> None:
    name = entry["name"]
    line_idx = entry["line"] - 1
    if line_idx < 0 or line_idx >= len(lines):
        skip_reasons["out_of_range"] += 1
        return

    src = lines[line_idx]
    stripped = src.strip()

    if _is_destr_member_line(stripped, name):
        destr_start = _find_destr_open_brace(lines, line_idx)
        if destr_start is not None:
            destr_text = _get_destr_text(lines, destr_start, line_idx + 20)
            if _REST_ELEMENT_RE.search(destr_text):
                skip_reasons["rest_element"] += 1
                return
            lines_to_remove.add(line_idx)
            removed_names.append(name)
        else:
            skip_reasons["no_destr_context"] += 1
        return

    if re.match(r"\s*(?:const|let|var)\s*\{", stripped):
        destr_text = _collect_full_statement(lines, line_idx)
        if _REST_ELEMENT_RE.search(destr_text):
            skip_reasons["rest_element"] += 1
            return
        inline_removals[line_idx].add(name)
        removed_names.append(name)
        return

    if re.match(r"\s*(?:const|let|var)\s*\[", stripped):
        skip_reasons["array_destructuring"] += 1
        return
    if re.search(r"(?:function|=>)\s*\(", stripped) or re.match(r"\s*\(", stripped):
        skip_reasons["function_param"] += 1
        return
    if _record_direct_var_removal(
        stripped,
        line_idx,
        name,
        lines_to_remove=lines_to_remove,
        removed_names=removed_names,
        skip_reasons=skip_reasons,
    ):
        return
    skip_reasons["other"] += 1


def _apply_inline_removals(
    lines: list[str],
    inline_removals: dict[int, set[str]],
) -> None:
    for line_idx, names_to_remove in inline_removals.items():
        new_line = _remove_names_from_destr(lines, line_idx, names_to_remove)
        if new_line is not None:
            lines[line_idx] = new_line


def fix_unused_vars(
    entries: list[dict], *, dry_run: bool = False
) -> tuple[list[dict], dict[str, int]]:
    """Remove unused names from destructuring patterns.

    Handles two patterns:
    1. Multi-line destructuring: name on its own line -> remove line
    2. Single-line destructuring: const { a, unused, b } = ... -> remove unused

    Returns:
        (results, skip_reasons) — results is the usual list of dicts,
        skip_reasons maps reason string -> count.
    """
    by_file: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_file[e["file"]].append(e)

    results = []
    skip_reasons: dict[str, int] = defaultdict(int)
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

            lines_to_remove: set[int] = set()
            inline_removals: dict[int, set[str]] = defaultdict(set)
            removed_names: list[str] = []

            for entry in file_entries:
                _handle_unused_entry(
                    entry,
                    lines=lines,
                    lines_to_remove=lines_to_remove,
                    inline_removals=inline_removals,
                    removed_names=removed_names,
                    skip_reasons=skip_reasons,
                )

            _apply_inline_removals(lines, inline_removals)

            new_lines = collapse_blank_lines(lines, lines_to_remove)

            new_content = "".join(new_lines)
            if new_content != original:
                lines_removed = len(original.splitlines()) - len(
                    new_content.splitlines()
                )
                results.append(
                    {
                        "file": filepath,
                        "removed": removed_names,
                        "lines_removed": lines_removed,
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
            f"apply unused-vars fixer across {len(skipped_files)} skipped file(s)",
            OSError(
                "; ".join(f"{path}: {reason}" for path, reason in skipped_files[:5])
            ),
        )

    return results, dict(skip_reasons)


def _is_destr_member_line(stripped: str, name: str) -> bool:
    """Check if a stripped line is a destructuring member matching `name`."""
    patterns = [
        rf"^(?:type\s+)?{re.escape(name)}\s*[,}}]",
        rf"^(?:type\s+)?{re.escape(name)}\s*=\s*[^,]+[,}}]",
        rf"^(?:type\s+)?{re.escape(name)}\s*:\s*\w+\s*[,}}]",
        rf"^(?:type\s+)?{re.escape(name)}\s*$",
        rf"^(?:type\s+)?{re.escape(name)}\s*=\s*[^,]+\s*$",
        rf"^(?:type\s+)?{re.escape(name)}\s*,",
    ]
    clean = stripped.split("//")[0].strip()
    return any(re.match(p, clean) for p in patterns)


def _find_destr_open_brace(lines: list[str], member_idx: int) -> int | None:
    """Walk backwards from a member line to find the opening { of a destructuring."""
    for idx in range(member_idx - 1, max(member_idx - 30, -1), -1):
        stripped = lines[idx].strip()
        if "{" in stripped:
            return idx
        if stripped and not stripped.endswith(",") and "{" not in stripped:
            if "=" in stripped or "=>" in stripped or "(" in stripped:
                continue
            break
    return None


def _get_destr_text(lines: list[str], start: int, max_end: int) -> str:
    """Get the text of a destructuring block from start to closing }."""
    text = ""
    depth = 0
    for idx in range(start, min(max_end, len(lines))):
        text += lines[idx]
        for ch in lines[idx]:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth <= 0:
                    return text
    return text


def _collect_full_statement(lines: list[str], start: int) -> str:
    """Collect a potentially multi-line statement starting at start."""
    text = ""
    for idx in range(start, min(start + 20, len(lines))):
        text += lines[idx]
        if ";" in lines[idx] or (idx > start and "}" in lines[idx]):
            break
    return text


def _remove_names_from_destr(
    lines: list[str], line_idx: int, names: set[str]
) -> str | None:
    """Remove specific names from a single-line object destructuring.

    Returns None if we can't safely parse/modify.
    """
    line = lines[line_idx]
    brace_match = re.search(r"\{([^}]*)\}", line)
    if not brace_match:
        return None

    inner = brace_match.group(1)
    members = [m.strip() for m in inner.split(",") if m.strip()]

    remaining = []
    for m in members:
        member_name = m.split(":")[0].split("=")[0].strip()
        if member_name.startswith("type "):
            member_name = member_name[5:].strip()
        if member_name.startswith("..."):
            remaining.append(m)
            continue
        if member_name in names:
            continue
        remaining.append(m)

    if not remaining:
        return None

    new_inner = ", ".join(remaining)
    before = line[: brace_match.start()]
    after = line[brace_match.end() :]
    return f"{before}{{ {new_inner} }}{after}"
