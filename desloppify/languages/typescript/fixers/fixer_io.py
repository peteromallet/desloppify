"""File-grouped write pipeline for TypeScript fixer transforms."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.base.discovery.file_paths import rel, safe_write_text
from desloppify.base.output.terminal import colorize
from desloppify.base.discovery.paths import get_project_root

logger = logging.getLogger(__name__)


def _group_entries(entries: list[dict], file_key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        filepath = entry.get(file_key)
        if not isinstance(filepath, str) or not filepath:
            continue
        grouped.setdefault(filepath, []).append(entry)
    return grouped


def apply_fixer(
    entries: list[dict], transform_fn, *, dry_run: bool = False, file_key: str = "file"
) -> list[dict]:
    """Shared file-loop template for fixers."""
    by_file = _group_entries(entries, file_key)
    results = []
    skipped_files: list[tuple[str, str]] = []
    for filepath, file_entries in sorted(by_file.items()):
        try:
            changed = _process_fixer_file(
                filepath,
                file_entries,
                transform_fn=transform_fn,
                dry_run=dry_run,
            )
            if changed is not None:
                results.append(changed)
        except (OSError, UnicodeDecodeError) as ex:
            skipped_files.append((filepath, str(ex)))
            print(colorize(f"  Skip {rel(filepath)}: {ex}", "yellow"), file=sys.stderr)

    if skipped_files:
        log_best_effort_failure(
            logger,
            f"apply TypeScript fixer across {len(skipped_files)} skipped file(s)",
            OSError(
                "; ".join(f"{path}: {reason}" for path, reason in skipped_files[:5])
            ),
        )

    return results


def _process_fixer_file(
    filepath: str,
    file_entries: list[dict],
    *,
    transform_fn,
    dry_run: bool,
) -> dict[str, object] | None:
    path = Path(filepath) if Path(filepath).is_absolute() else get_project_root() / filepath
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    new_lines, removed_names = transform_fn(lines, file_entries)
    new_content = "".join(new_lines)
    if new_content == original:
        return None

    if not dry_run:
        _write_fixer_content(path, new_content)

    lines_removed = len(original.splitlines()) - len(new_content.splitlines())
    return {
        "file": filepath,
        "removed": removed_names,
        "lines_removed": lines_removed,
    }


def _write_fixer_content(path: Path, content: str) -> None:
    try:
        safe_write_text(path, content)
    except OSError as exc:
        log_best_effort_failure(logger, f"write TypeScript fixer output {path}", exc)
        raise


__all__ = ["apply_fixer"]
