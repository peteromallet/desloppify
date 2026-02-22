"""Unused params fixer: prefixes unused function/callback params with _."""

import re

from desloppify.languages.typescript.fixers.common import apply_fixer


def fix_unused_params(entries: list[dict], *, dry_run: bool = False) -> list[dict]:
    """Prefix unused function/callback/catch parameters with _ to signal intentional non-use."""

    def _transform(lines: list[str], file_entries: list[dict]):
        removed_names: list[str] = []
        for entry in file_entries:
            removed_name = _rewrite_unused_param(lines, entry)
            if removed_name:
                removed_names.append(removed_name)
        return lines, removed_names

    return apply_fixer(entries, _transform, dry_run=dry_run)


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
