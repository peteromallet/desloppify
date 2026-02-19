"""Unused params fixer: prefixes unused function/callback params with _."""

import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.utils import PROJECT_ROOT, c, rel, safe_write_text

logger = logging.getLogger(__name__)


def fix_unused_params(entries: list[dict], *, dry_run: bool = False) -> list[dict]:
    """Prefix unused function/callback/catch parameters with _.

    Only handles parameters (positional — can't remove without breaking calls).
    Prefixing with _ signals "intentionally unused" and is ignored by the scanner.

    Args:
        entries: [{file, line, col, name, category}, ...] from detect_unused(), category=="vars".
        dry_run: If True, don't write files.

    Returns:
        List of {file, removed: [str], lines_removed: int} dicts.
    """
    by_file: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_file[e["file"]].append(e)

    results = []
    skipped_files: list[tuple[str, str]] = []

    for filepath, file_entries in sorted(by_file.items()):
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            original = p.read_text()
            lines = original.splitlines(keepends=True)

            removed_names: list[str] = []
            for entry in file_entries:
                removed_name = _rewrite_unused_param(lines, entry)
                if removed_name:
                    removed_names.append(removed_name)

            new_content = "".join(lines)
            if new_content != original:
                results.append(
                    {
                        "file": filepath,
                        "removed": removed_names,
                        "lines_removed": 0,
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
            f"apply unused-params fixer across {len(skipped_files)} skipped file(s)",
            OSError(
                "; ".join(f"{path}: {reason}" for path, reason in skipped_files[:5])
            ),
        )

    return results


def _rewrite_unused_param(lines: list[str], entry: dict) -> str | None:
    """Rewrite one unused param entry in-place and return renamed symbol."""
    name = entry["name"]
    if name.startswith("_"):
        return None

    line_idx = entry["line"] - 1
    if line_idx < 0 or line_idx >= len(lines):
        return None

    src = lines[line_idx]
    if not _line_is_param_context(src, lines, line_idx):
        return None

    if _rewrite_with_column_hint(lines, line_idx, src, name, entry.get("col", 0)):
        return name

    new_name = f"_{name}"
    param_re = re.compile(r"(?<=[\(,\s])" + re.escape(name) + r"(?=\s*[?:,)=])")
    new_line = param_re.sub(new_name, src, count=1)
    if new_line == src:
        return None
    lines[line_idx] = new_line
    return name


def _line_is_param_context(src: str, lines: list[str], line_idx: int) -> bool:
    stripped = src.strip()
    return bool(
        re.search(r"(?:function\s+\w+|function)\s*\(", stripped)
        or re.search(r"\)\s*(?:=>|:)", stripped)
        or re.search(r"=>\s*\{", stripped)
        or re.match(r"\s*\(", stripped)
        or re.search(r"catch\s*\(", stripped)
        or _is_param_context(lines, line_idx)
    )


def _rewrite_with_column_hint(
    lines: list[str], line_idx: int, src: str, name: str, col: int
) -> bool:
    if col <= 0:
        return False
    col_idx = col - 1
    if col_idx + len(name) > len(src):
        return False
    if src[col_idx : col_idx + len(name)] != name:
        return False
    new_name = f"_{name}"
    lines[line_idx] = src[:col_idx] + new_name + src[col_idx + len(name) :]
    return True


def _is_param_context(lines: list[str], line_idx: int) -> bool:
    """Check if a line is inside a multi-line function parameter list."""
    paren_depth = 0
    for back in range(0, 15):
        idx = line_idx - back
        if idx < 0:
            break
        line = lines[idx]
        for ch in reversed(line):
            if ch == ")":
                paren_depth += 1
            elif ch == "(":
                paren_depth -= 1
        if paren_depth < 0:
            # Found unmatched ( — check if it belongs to a function/catch
            for check_idx in range(max(0, idx - 1), idx + 1):
                prev = lines[check_idx].strip()
                if re.search(
                    r"(?:function\s+\w+|catch|\w+\s*=\s*(?:async\s+)?)\s*$", prev
                ):
                    return True
                if re.search(r"(?:function|catch)\s*\($", prev):
                    return True
                if prev.endswith("("):
                    return True
            return False  # Unmatched ( but not a function/catch context
        if line.strip().endswith((";", "{")):
            break
    return False
