"""File writing and rollback-safe application helpers for move command."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from desloppify.core.fallbacks import restore_files_best_effort, warn_best_effort
from desloppify.file_discovery import rel
from desloppify.file_discovery import safe_write_text
from desloppify.utils import colorize


def _rollback_written_files(written_files: dict[str, str]) -> None:
    failed = restore_files_best_effort(written_files, safe_write_text)
    for filepath in failed:
        warn_best_effort(f"Could not restore {rel(filepath)}")


def _rollback_move_target(dest_abs: str, source_abs: str, *, target_name: str) -> None:
    if not (Path(dest_abs).exists() and not Path(source_abs).exists()):
        return
    try:
        shutil.move(dest_abs, source_abs)
    except OSError:
        warn_best_effort(f"Could not move {target_name} back to {rel(source_abs)}")


def apply_file_move(
    source_abs: str,
    dest_abs: str,
    importer_changes: dict[str, list[tuple[str, str]]],
    self_changes: list[tuple[str, str]],
) -> None:
    """Move a file and apply import replacements with rollback on failure."""
    new_contents: dict[str, str] = {}
    if self_changes:
        content = Path(source_abs).read_text()
        for old_str, new_str in self_changes:
            content = content.replace(old_str, new_str)
        new_contents[dest_abs] = content

    for filepath, replacements in importer_changes.items():
        content = Path(filepath).read_text()
        for old_str, new_str in replacements:
            content = content.replace(old_str, new_str)
        new_contents[filepath] = content

    Path(dest_abs).parent.mkdir(parents=True, exist_ok=True)
    written_files: dict[str, str] = {}
    try:
        shutil.move(source_abs, dest_abs)

        if dest_abs in new_contents:
            written_files[dest_abs] = Path(dest_abs).read_text()
            safe_write_text(dest_abs, new_contents[dest_abs])

        for filepath in importer_changes:
            if filepath in new_contents:
                written_files[filepath] = Path(filepath).read_text()
                safe_write_text(filepath, new_contents[filepath])

    except (OSError, UnicodeDecodeError, shutil.Error) as ex:
        print(colorize(f"\n  Error during move: {ex}", "red"), file=sys.stderr)
        print(colorize("  Rolling back...", "yellow"), file=sys.stderr)
        _rollback_written_files(written_files)
        _rollback_move_target(dest_abs, source_abs, target_name="file")
        raise


def apply_directory_move(
    source_abs: str,
    dest_abs: str,
    source_path: Path,
    external_changes: dict[str, list[tuple[str, str]]],
    internal_changes: dict[str, list[tuple[str, str]]],
) -> None:
    """Move a directory and apply external/internal import replacements."""
    Path(dest_abs).parent.mkdir(parents=True, exist_ok=True)
    written_files: dict[str, str] = {}
    try:
        shutil.move(source_abs, dest_abs)

        for src_file, changes in internal_changes.items():
            rel_in_dir = Path(src_file).relative_to(source_path)
            dest_file = Path(dest_abs) / rel_in_dir
            original = dest_file.read_text()
            content = original
            for old_str, new_str in changes:
                content = content.replace(old_str, new_str)
            written_files[str(dest_file)] = original
            safe_write_text(dest_file, content)

        for filepath, replacements in external_changes.items():
            original = Path(filepath).read_text()
            content = original
            for old_str, new_str in replacements:
                content = content.replace(old_str, new_str)
            written_files[filepath] = original
            safe_write_text(filepath, content)

    except (OSError, UnicodeDecodeError, shutil.Error) as ex:
        print(
            colorize(f"\n  Error during directory move: {ex}", "red"), file=sys.stderr
        )
        print(colorize("  Rolling back...", "yellow"), file=sys.stderr)
        _rollback_written_files(written_files)
        _rollback_move_target(dest_abs, source_abs, target_name="directory")
        raise


__all__ = ["apply_directory_move", "apply_file_move"]
