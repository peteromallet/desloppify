"""Text-oriented utility helpers split from the main utils facade."""

from __future__ import annotations

import math
from pathlib import Path


def read_code_snippet(
    filepath: str,
    line: int,
    context: int = 1,
    *,
    project_root: Path | str | None = None,
) -> str | None:
    """Read ±context lines around a line number. Returns formatted string or None."""
    try:
        # Local import avoids circular dependency: discovery.paths wraps this helper.
        from desloppify.base.discovery.paths import get_project_root

        root = (
            Path(project_root).resolve()
            if project_root is not None
            # Runtime-aware default; preserves RuntimeContext/project-root overrides.
            else get_project_root()
        )
        full = Path(filepath)
        if not full.is_absolute():
            full = root / full
        content = full.read_text(errors="replace")
    except OSError:
        return None
    lines = content.splitlines()
    if line < 1 or line > len(lines):
        return None
    start = max(0, line - 1 - context)
    end = min(len(lines), line + context)
    parts = []
    for i in range(start, end):
        ln = i + 1
        marker = "→" if ln == line else " "
        text = lines[i]
        if len(text) > 120:
            text = text[:117] + "..."
        parts.append(f"    {marker} {ln:>4} │ {text}")
    return "\n".join(parts)


def _consume_escaped_char(text: str, index: int, out: list[str]) -> int | None:
    if text[index] != "\\" or index + 1 >= len(text):
        return None
    out.append(text[index : index + 2])
    return index + 2


def _skip_comment(text: str, index: int) -> int | None:
    if text[index] != "/" or index + 1 >= len(text):
        return None
    next_char = text[index + 1]
    if next_char == "/":
        newline_at = text.find("\n", index)
        return -1 if newline_at == -1 else newline_at
    if next_char == "*":
        end = text.find("*/", index + 2)
        return -1 if end == -1 else end + 2
    return None


def strip_c_style_comments(text: str) -> str:
    """Strip // and /* */ comments while preserving string literals."""
    result: list[str] = []
    i = 0
    in_str = None
    while i < len(text):
        ch = text[i]
        if in_str:
            escaped_next = _consume_escaped_char(text, i, result)
            if escaped_next is not None:
                i = escaped_next
                continue
            if ch == in_str:
                in_str = None
            result.append(ch)
            i += 1
            continue

        if ch in ('"', "'", "`"):
            in_str = ch
            result.append(ch)
            i += 1
            continue

        skipped_to = _skip_comment(text, i)
        if skipped_to is not None:
            if skipped_to == -1:
                break
            i = skipped_to
            continue

        result.append(ch)
        i += 1
    return "".join(result)


def is_numeric(value: object) -> bool:
    """Return True if *value* is a finite int or float but NOT a bool.

    Python's ``bool`` is a subclass of ``int``, so ``isinstance(True, int)``
    is ``True``.  Many JSON-derived payloads need to distinguish real numbers
    from booleans; this helper centralises that guard.
    """
    if isinstance(value, bool):
        return False
    if not isinstance(value, int | float):
        return False
    return math.isfinite(float(value))


__all__ = [
    "is_numeric",
    "read_code_snippet",
    "strip_c_style_comments",
]
