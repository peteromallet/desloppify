"""Shared fixer utilities: bracket tracking, body extraction, fixer template."""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, c, rel
from ..detectors._smell_helpers import scan_code

_CHAR_DEPTH_DELTA = {
    "(": ("parens", 1),
    ")": ("parens", -1),
    "{": ("braces", 1),
    "}": ("braces", -1),
    "[": ("brackets", 1),
    "]": ("brackets", -1),
}


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
    depths = {"parens": 0, "braces": 0, "brackets": 0}
    for idx in range(start, min(start + max_lines, len(lines))):
        for _, ch, in_s in scan_code(lines[idx]):
            if in_s:
                continue
            delta_spec = _CHAR_DEPTH_DELTA.get(ch)
            if delta_spec is None:
                continue
            key, delta = delta_spec
            depths[key] += delta
            if delta > 0:
                continue
            if track == "parens" and key == "parens" and depths["parens"] <= 0:
                return idx
            if track == "braces" and key == "braces" and depths["braces"] <= 0:
                return idx
            if track == "all" and key == "parens" and depths["parens"] <= 0:
                return idx
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


def _group_entries(entries: list[dict], file_key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        grouped[entry[file_key]].append(entry)
    return grouped


def _read_source_lines(filepath: str) -> tuple[Path, str, list[str]]:
    file_path = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
    original = file_path.read_text()
    return file_path, original, original.splitlines(keepends=True)


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content)
        os.replace(str(tmp), str(path))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _build_apply_result(filepath: str, original: str, new_content: str, removed_names: list[str]) -> dict | None:
    if new_content == original:
        return None
    lines_removed = len(original.splitlines()) - len(new_content.splitlines())
    return {
        "file": filepath,
        "removed": removed_names,
        "lines_removed": lines_removed,
    }


def apply_fixer(entries: list[dict], transform_fn, *, dry_run: bool = False,
                file_key: str = "file") -> list[dict]:
    """Shared file-loop template for fixers.

    Groups *entries* by file, reads each file, calls
    ``transform_fn(lines, file_entries) -> (new_lines, removed_names)``
    and writes back if changed.

    Returns ``[{file, removed, lines_removed}, ...]``.
    """
    by_file = _group_entries(entries, file_key)
    results = []
    skipped_files = 0
    for filepath, file_entries in sorted(by_file.items()):
        try:
            path, original, lines = _read_source_lines(filepath)
            new_lines, removed_names = transform_fn(lines, file_entries)
            new_content = "".join(new_lines)
            result = _build_apply_result(filepath, original, new_content, removed_names)
            if result is None:
                continue
            results.append(result)
            if not dry_run:
                _atomic_write(path, new_content)
        except (OSError, UnicodeDecodeError) as ex:
            print(c(f"  Skip {rel(filepath)}: {ex}", "yellow"), file=sys.stderr)
            skipped_files += 1

    if skipped_files:
        print(c(f"  Skipped {skipped_files} file(s) due to read/write errors.", "dim"))
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


def remove_symbols_from_import_stmt(import_stmt: str, symbols_to_remove: set[str]) -> str | None:
    """Remove specific symbols from an import statement."""
    stmt = import_stmt.strip()
    from_match = re.search(r"""from\s+(['"].*?['"]);?\s*$""", stmt, re.DOTALL)
    if not from_match:
        return import_stmt

    from_clause = from_match.group(0).rstrip()
    if not from_clause.endswith(";"):
        from_clause += ";"
    before_from = stmt[:from_match.start()].strip()

    type_prefix = ""
    if before_from.startswith("import type"):
        type_prefix = "type "
        before_from = before_from[len("import type"):].strip()
    elif before_from.startswith("import"):
        before_from = before_from[len("import"):].strip()
    else:
        return import_stmt

    default_import = None
    named_imports = []
    brace_match = re.search(r"\{([^}]*)\}", before_from, re.DOTALL)
    if brace_match:
        named_str = brace_match.group(1)
        named_imports = [n.strip() for n in named_str.split(",") if n.strip()]
        before_brace = before_from[:brace_match.start()].strip().rstrip(",").strip()
        if before_brace:
            default_import = before_brace
    else:
        default_import = before_from.strip().rstrip(",").strip()

    remove_default = default_import in symbols_to_remove if default_import else False
    remaining_named = [
        n for n in named_imports if n not in symbols_to_remove and n.split(" as ")[0].strip() not in symbols_to_remove
    ]
    new_default = None if remove_default else default_import
    if not new_default and not remaining_named:
        return None

    parts = []
    if new_default:
        parts.append(new_default)
    if remaining_named:
        if len(remaining_named) <= 3:
            parts.append("{ " + ", ".join(remaining_named) + " }")
        else:
            inner = ",\n  ".join(remaining_named)
            parts.append("{\n  " + inner + "\n}")

    indent = ""
    for ch in import_stmt:
        if ch in " \t":
            indent += ch
        else:
            break
    return f"{indent}import {type_prefix}{', '.join(parts)} {from_clause}\n"


def process_unused_import_lines(
    lines: list[str],
    unused_symbols: set[str],
    unused_by_line: dict[int, list[str]],
) -> list[str]:
    """Process TS lines and remove/import-trim unused import statements."""
    result: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip().startswith("import "):
            result.append(line)
            index += 1
            continue

        next_idx, replacement = _process_import_statement(
            lines=lines,
            start=index,
            unused_symbols=unused_symbols,
            unused_by_line=unused_by_line,
            prior_output=result,
        )
        if replacement:
            result.extend(replacement)
        index = next_idx
    return result


def _process_import_statement(
    *,
    lines: list[str],
    start: int,
    unused_symbols: set[str],
    unused_by_line: dict[int, list[str]],
    prior_output: list[str],
) -> tuple[int, list[str]]:
    import_lines, import_end = _collect_import_statement(lines, start)
    line_start = start + 1
    line_range = range(line_start, line_start + len(import_lines))
    if _should_remove_entire_import(unused_symbols, unused_by_line, line_range):
        return _advance_after_removed_import(lines, import_end, prior_output), []

    symbols_on_import = _symbols_for_line_range(unused_by_line, line_range)
    if not symbols_on_import:
        return import_end + 1, import_lines

    cleaned = remove_symbols_from_import_stmt("".join(import_lines), symbols_on_import)
    if cleaned is None:
        return _advance_after_removed_import(lines, import_end, prior_output), []
    return import_end + 1, [cleaned]


def _collect_import_statement(lines: list[str], start: int) -> tuple[list[str], int]:
    import_lines = [lines[start]]
    idx = start
    while not _is_import_complete("".join(import_lines)):
        idx += 1
        if idx >= len(lines):
            break
        import_lines.append(lines[idx])
    return import_lines, idx


def _should_remove_entire_import(
    unused_symbols: set[str],
    unused_by_line: dict[int, list[str]],
    line_range: range,
) -> bool:
    if "(entire import)" not in unused_symbols:
        return False
    return any("(entire import)" in unused_by_line.get(line_no, []) for line_no in line_range)


def _symbols_for_line_range(unused_by_line: dict[int, list[str]], line_range: range) -> set[str]:
    symbols: set[str] = set()
    for line_no in line_range:
        for symbol in unused_by_line.get(line_no, []):
            if symbol != "(entire import)":
                symbols.add(symbol)
    return symbols


def _advance_after_removed_import(lines: list[str], import_end: int, prior_output: list[str]) -> int:
    next_idx = import_end + 1
    if next_idx < len(lines) and lines[next_idx].strip() == "" and prior_output and prior_output[-1].strip() == "":
        next_idx += 1
    return next_idx


def _is_import_complete(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith(";"):
        return True
    if "from " not in stripped:
        return False
    trailing = stripped.split("from ", 1)[-1].strip()
    if (trailing.startswith("'") and trailing.count("'") >= 2) or (
        trailing.startswith('"') and trailing.count('"') >= 2
    ):
        return True
    return False
