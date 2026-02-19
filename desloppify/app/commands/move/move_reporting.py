"""Terminal reporting helpers for move command plans."""

from __future__ import annotations

from desloppify.app.commands.helpers.rendering import print_replacement_groups
from desloppify.app.commands.move.move_planning import (
    DirectoryMovePlan,
    summarize_directory_plan,
)
from desloppify.utils import colorize, rel


def print_file_move_plan(
    source_abs: str,
    dest_abs: str,
    importer_changes: dict[str, list[tuple[str, str]]],
    self_changes: list[tuple[str, str]],
) -> None:
    """Print the move plan: summary, self-imports, and importer changes."""
    total_files = len(importer_changes) + (1 if self_changes else 0)
    total_replacements = sum(len(r) for r in importer_changes.values()) + len(
        self_changes
    )

    print(colorize(f"\n  Move: {rel(source_abs)} → {rel(dest_abs)}", "bold"))
    print(
        colorize(
            f"  {total_replacements} import replacements across {total_files} files\n",
            "dim",
        )
    )

    if self_changes:
        print(colorize(f"  Own imports ({len(self_changes)} changes):", "cyan"))
        for old, new in self_changes:
            print(f"    {old}  →  {new}")
        print()

    if importer_changes:
        print_replacement_groups(
            importer_changes,
            title=f"  Importers ({len(importer_changes)} files):",
        )

    if not importer_changes and not self_changes:
        print(
            colorize(
                "  No import references found — only the file will be moved.", "dim"
            )
        )
        print()


def print_directory_move_plan(
    source_abs: str, dest_abs: str, plan: DirectoryMovePlan
) -> None:
    """Print a directory move summary with grouped replacement breakdowns."""
    total_changes, total_replacements = summarize_directory_plan(plan)

    print(
        colorize(f"\n  Move directory: {rel(source_abs)}/ → {rel(dest_abs)}/", "bold")
    )
    print(colorize(f"  {len(plan.file_moves)} files in package", "dim"))
    print(
        colorize(
            f"  {total_replacements} import replacements across {total_changes} files\n",
            "dim",
        )
    )

    if plan.self_changes:
        self_replacements = sum(len(v) for v in plan.self_changes.values())
        print(
            colorize(
                f"  Own imports ({self_replacements} changes across {len(plan.self_changes)} files):",
                "cyan",
            )
        )
        for src_file, changes in sorted(plan.self_changes.items()):
            print(f"    {rel(src_file)}:")
            for old, new in changes:
                print(f"      {old}  →  {new}")
        print()

    if plan.intra_package_changes:
        intra_replacements = sum(len(v) for v in plan.intra_package_changes.values())
        print_replacement_groups(
            plan.intra_package_changes,
            title=(
                "  Intra-package imports "
                f"({intra_replacements} changes across {len(plan.intra_package_changes)} files):"
            ),
        )

    if plan.external_changes:
        print_replacement_groups(
            plan.external_changes,
            title=f"  External importers ({len(plan.external_changes)} files):",
        )

    if (
        not plan.external_changes
        and not plan.intra_package_changes
        and not plan.self_changes
    ):
        print(
            colorize(
                "  No import references found — only the directory will be moved.",
                "dim",
            )
        )
        print()


__all__ = ["print_directory_move_plan", "print_file_move_plan"]
