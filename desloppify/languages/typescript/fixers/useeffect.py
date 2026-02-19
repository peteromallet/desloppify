"""Dead useEffect fixer: deletes useEffect calls with empty/comment-only bodies."""

from typing import Any

from desloppify.languages.typescript.fixers.common import (
    apply_fixer,
    collapse_blank_lines,
    find_balanced_end,
)


def fix_dead_useeffect(
    entries: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Delete useEffect calls with empty/comment-only bodies.

    Args:
        entries: [{file, line, content}, ...] from smell detector.
        dry_run: If True, don't write files.

    Returns:
        List of {file, removed: [str], lines_removed: int} dicts.
    """

    def transform(
        lines: list[str],
        file_entries: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        lines_to_remove: set[int] = set()

        for e in file_entries:
            line_idx = e["line"] - 1
            if line_idx < 0 or line_idx >= len(lines):
                continue

            end = find_balanced_end(lines, line_idx, track="all")
            if end is None:
                continue

            for idx in range(line_idx, end + 1):
                lines_to_remove.add(idx)

            # Remove preceding comment if orphaned
            if line_idx > 0 and lines[line_idx - 1].strip().startswith("//"):
                lines_to_remove.add(line_idx - 1)

        new_lines = collapse_blank_lines(lines, lines_to_remove)
        return new_lines, ["dead_useeffect"]

    return apply_fixer(entries, transform, dry_run=dry_run)
