"""Debug log fixer: removes tagged console.log lines and cleans up aftermath."""

from __future__ import annotations

import sys

from desloppify.base.discovery.file_paths import rel
from desloppify.base.output.terminal import colorize
from desloppify.languages._framework.base.types import FixResult
from desloppify.languages.typescript.fixers.fixer_io import apply_fixer
from desloppify.languages.typescript.fixers.logs_cleanup import (
    find_dead_log_variables,
    mark_orphaned_comments,
    remove_empty_blocks,
)
from desloppify.languages.typescript.fixers.logs_context import (
    is_logger_wrapper_context,
)
from desloppify.languages.typescript.fixers.syntax_scan import (
    collapse_blank_lines,
    find_balanced_end,
)


def fix_debug_logs(entries: list[dict], *, dry_run: bool = False) -> FixResult:
    """Remove tagged console.log lines and clean up aftermath (dead vars, empty blocks)."""
    entries_by_file: dict[str, list[dict]] = {}
    for entry in entries:
        entries_by_file.setdefault(entry["file"], []).append(entry)

    def _transform(lines: list[str], file_entries: list[dict]):
        lines_to_remove: set[int] = set()
        for entry in file_entries:
            start = entry["line"] - 1
            if start < 0 or start >= len(lines):
                continue
            if is_logger_wrapper_context(lines, start):
                continue
            end = find_balanced_end(lines, start, track="parens")
            if end is None:
                print(
                    colorize(
                        (
                            f"  Warn: skipping {rel(entry['file'])}:{entry['line']} "
                            "— could not find statement end"
                        ),
                        "yellow",
                    ),
                    file=sys.stderr,
                )
                continue
            for idx in range(start, end + 1):
                lines_to_remove.add(idx)
            mark_orphaned_comments(lines, start, lines_to_remove)

        lines_to_remove |= find_dead_log_variables(lines, lines_to_remove)
        new_lines = collapse_blank_lines(lines, lines_to_remove)
        new_lines = remove_empty_blocks(new_lines)
        tags = sorted(set(entry.get("tag", "") for entry in file_entries))
        return new_lines, tags

    raw_results = apply_fixer(entries, _transform, dry_run=dry_run)
    return FixResult(
        entries=[
            {
                "file": result["file"],
                "removed": result["removed"],
                "tags": result["removed"],
                "lines_removed": result["lines_removed"],
                "log_count": len(entries_by_file.get(result["file"], [])),
            }
            for result in raw_results
        ]
    )


__all__ = ["fix_debug_logs"]
