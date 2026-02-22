"""Unused vars fixer: removes unused names from destructuring patterns + standalone vars."""

import re
from collections import defaultdict
from typing import NamedTuple

from desloppify.languages.typescript.fixers.common import apply_fixer, collapse_blank_lines

_DESTR_MEMBER_RE = re.compile(r"^\s*(\w+)\s*(?:=\s*[^,]+)?\s*,?\s*$")
_REST_ELEMENT_RE = re.compile(r"\.\.\.\w+")


class _EntryAction(NamedTuple):
    """Result of analysing a single unused-var entry."""

    lines_to_remove: frozenset[int]
    inline_removals: dict[int, set[str]]
    removed_name: str | None
    skip_reason: str | None


def _try_direct_var_removal(
    stripped: str,
    line_idx: int,
    name: str,
) -> _EntryAction | None:
    """Try to remove a standalone variable declaration. Returns None if not applicable."""
    if not re.match(r"\s*(?:const|let|var)\s+\w+\s*=", stripped):
        return None
    rhs = stripped.split("=", 1)[1] if "=" in stripped else ""
    if stripped.rstrip().endswith(";") and "(" not in rhs:
        return _EntryAction(
            lines_to_remove=frozenset({line_idx}),
            inline_removals={},
            removed_name=name,
            skip_reason=None,
        )
    return _EntryAction(
        lines_to_remove=frozenset(),
        inline_removals={},
        removed_name=None,
        skip_reason="standalone_var_with_call",
    )


def _handle_unused_entry(
    entry: dict,
    *,
    lines: list[str],
) -> _EntryAction:
    """Analyse a single unused-var entry and return the action to take."""
    name = entry["name"]
    line_idx = entry["line"] - 1
    if line_idx < 0 or line_idx >= len(lines):
        return _EntryAction(frozenset(), {}, None, "out_of_range")

    stripped = lines[line_idx].strip()

    if _is_destr_member_line(stripped, name):
        destr_start = _find_destr_open_brace(lines, line_idx)
        if destr_start is not None:
            destr_text = _get_destr_text(lines, destr_start, line_idx + 20)
            if _REST_ELEMENT_RE.search(destr_text):
                return _EntryAction(frozenset(), {}, None, "rest_element")
            return _EntryAction(frozenset({line_idx}), {}, name, None)
        return _EntryAction(frozenset(), {}, None, "no_destr_context")

    if re.match(r"\s*(?:const|let|var)\s*\{", stripped):
        destr_text = _collect_full_statement(lines, line_idx)
        if _REST_ELEMENT_RE.search(destr_text):
            return _EntryAction(frozenset(), {}, None, "rest_element")
        return _EntryAction(frozenset(), {line_idx: {name}}, name, None)

    if re.match(r"\s*(?:const|let|var)\s*\[", stripped):
        return _EntryAction(frozenset(), {}, None, "array_destructuring")
    if re.search(r"(?:function|=>)\s*\(", stripped) or re.match(r"\s*\(", stripped):
        return _EntryAction(frozenset(), {}, None, "function_param")

    direct = _try_direct_var_removal(stripped, line_idx, name)
    if direct is not None:
        return direct

    return _EntryAction(frozenset(), {}, None, "other")


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

    Returns (results, skip_reasons) where skip_reasons maps reason string to count.
    """
    skip_reasons: dict[str, int] = defaultdict(int)

    def _transform(lines: list[str], file_entries: list[dict]):
        all_lines_to_remove: set[int] = set()
        merged_inline: dict[int, set[str]] = defaultdict(set)
        removed_names: list[str] = []
        for entry in file_entries:
            action = _handle_unused_entry(entry, lines=lines)
            all_lines_to_remove |= action.lines_to_remove
            for line_idx, names in action.inline_removals.items():
                merged_inline[line_idx] |= names
            if action.removed_name is not None:
                removed_names.append(action.removed_name)
            if action.skip_reason is not None:
                skip_reasons[action.skip_reason] += 1
        _apply_inline_removals(lines, merged_inline)
        new_lines = collapse_blank_lines(lines, all_lines_to_remove)
        return new_lines, removed_names

    results = apply_fixer(entries, _transform, dry_run=dry_run)
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
