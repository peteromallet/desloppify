"""Unused params fixer: prefixes unused function/callback params with _."""

import re
import sys
from collections import defaultdict
from pathlib import Path

from ....utils import PROJECT_ROOT, c, rel


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
    skipped_files = 0

    for filepath, file_entries in sorted(by_file.items()):
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            original = p.read_text()
            lines = original.splitlines(keepends=True)

            removed_names: list[str] = []

            for e in file_entries:
                name = e["name"]
                if name.startswith("_"):
                    continue

                line_idx = e["line"] - 1
                if line_idx < 0 or line_idx >= len(lines):
                    continue

                src = lines[line_idx]
                stripped = src.strip()

                is_param = (
                    re.search(r"(?:function\s+\w+|function)\s*\(", stripped) or
                    re.search(r"\)\s*(?:=>|:)", stripped) or
                    re.search(r"=>\s*\{", stripped) or
                    re.match(r"\s*\(", stripped) or
                    re.search(r"catch\s*\(", stripped) or
                    _is_param_context(lines, line_idx)
                )

                if not is_param:
                    continue

                col = e.get("col", 0)
                new_name = f"_{name}"

                if col > 0:
                    col_idx = col - 1
                    if col_idx + len(name) <= len(src) and src[col_idx:col_idx + len(name)] == name:
                        lines[line_idx] = src[:col_idx] + new_name + src[col_idx + len(name):]
                        removed_names.append(name)
                        continue

                # Only replace at a parameter position (after (, comma, or start of line)
                param_re = re.compile(
                    r"(?<=[\(,\s])" + re.escape(name) + r"(?=\s*[?:,)=])"
                )
                new_line = param_re.sub(new_name, src, count=1)
                if new_line != src:
                    lines[line_idx] = new_line
                    removed_names.append(name)

            new_content = "".join(lines)
            if new_content != original:
                results.append({
                    "file": filepath,
                    "removed": removed_names,
                    "lines_removed": 0,
                })
                if not dry_run:
                    from ....utils import safe_write_text
                    safe_write_text(filepath, new_content)
        except (OSError, UnicodeDecodeError) as ex:
            print(c(f"  Skip {rel(filepath)}: {ex}", "yellow"), file=sys.stderr)
            skipped_files += 1

    if skipped_files:
        print(c(f"  Skipped {skipped_files} file(s) due to read/write errors.", "dim"))
    return results


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
                if re.search(r"(?:function\s+\w+|catch|\w+\s*=\s*(?:async\s+)?)\s*$", prev):
                    return True
                if re.search(r"(?:function|catch)\s*\($", prev):
                    return True
                if prev.endswith("("):
                    return True
            return False  # Unmatched ( but not a function/catch context
        if line.strip().endswith((";", "{")):
            break
    return False
