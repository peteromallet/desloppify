"""move command: move a file or directory and update all import references."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from desloppify import languages as lang_mod
from desloppify.app.commands.move.move_apply import apply_file_move
from desloppify.app.commands.move.move_directory import run_directory_move
from desloppify.app.commands.move.move_language import (
    load_lang_move_module,
    resolve_lang_for_file_move,
    resolve_move_verify_hint,
    supported_ext_hint,
)
from desloppify.app.commands.move.move_planning import (
    compute_replacements,
    resolve_dest,
)
from desloppify.app.commands.move.move_reporting import print_file_move_plan
from desloppify.file_discovery import rel, resolve_path
from desloppify.utils import colorize


def cmd_move(args: argparse.Namespace) -> None:
    """Move a file or directory and update all import references."""
    source_rel = args.source
    source_abs = resolve_path(source_rel)
    source_path = Path(source_abs)

    if source_path.is_dir():
        return _cmd_move_dir(args, source_abs)

    if not source_path.is_file():
        print(colorize(f"Source not found: {rel(source_abs)}", "red"), file=sys.stderr)
        sys.exit(1)

    dest_abs = resolve_dest(source_rel, args.dest, resolve_path)
    if Path(dest_abs).exists():
        print(
            colorize(f"Destination already exists: {rel(dest_abs)}", "red"),
            file=sys.stderr,
        )
        sys.exit(1)

    dry_run = getattr(args, "dry_run", False)

    lang_name = resolve_lang_for_file_move(source_abs, args)
    if not lang_name:
        print(
            colorize(
                (
                    "Cannot detect language. Use --lang or ensure file has one of: "
                    f"{supported_ext_hint()}"
                ),
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    lang = lang_mod.get_lang(lang_name)
    move_mod = load_lang_move_module(lang_name)

    scan_path = Path(resolve_path(lang.default_src))
    importer_changes, self_changes = compute_replacements(
        move_mod,
        source_abs,
        dest_abs,
        lang.build_dep_graph(scan_path),
    )

    print_file_move_plan(source_abs, dest_abs, importer_changes, self_changes)
    if dry_run:
        print(colorize("  Dry run — no files modified.", "yellow"))
        return

    apply_file_move(source_abs, dest_abs, importer_changes, self_changes)

    print(colorize("  Done.", "green"))
    verify_hint = resolve_move_verify_hint(move_mod)
    if verify_hint:
        print(colorize(f"  Run `{verify_hint}` to verify.", "dim"))
    print()


def _cmd_move_dir(args, source_abs: str):
    """Move a directory (package) and update all import references."""
    run_directory_move(args, source_abs, resolve_path)
