"""Directory-move orchestration for the move command."""

from __future__ import annotations

import sys
from pathlib import Path

from desloppify import languages as lang_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.move.move_apply import apply_directory_move
from desloppify.app.commands.move.move_language import (
    detect_lang_from_dir,
    load_lang_move_module,
    resolve_move_verify_hint,
    supported_ext_hint,
)
from desloppify.app.commands.move.move_planning import (
    build_directory_move_plan,
    build_internal_directory_changes,
    collect_source_files,
)
from desloppify.app.commands.move.move_reporting import print_directory_move_plan
from desloppify.file_discovery import rel
from desloppify.utils import colorize


def run_directory_move(args, source_abs: str, resolve_path_fn) -> None:
    """Move a directory and update all import references."""
    source_path = Path(source_abs)
    dest_abs = resolve_path_fn(args.dest)
    dry_run = getattr(args, "dry_run", False)

    if Path(dest_abs).exists():
        print(
            colorize(f"Destination already exists: {rel(dest_abs)}", "red"),
            file=sys.stderr,
        )
        sys.exit(1)

    lang_name = None
    if getattr(args, "lang", None):
        lang = resolve_lang(args)
        if lang:
            lang_name = lang.name
    else:
        lang_name = detect_lang_from_dir(source_abs)

    if not lang_name:
        lang = resolve_lang(args)
        if lang:
            lang_name = lang.name
    if not lang_name:
        print(
            colorize(
                (
                    "Cannot detect language from directory contents. Use --lang "
                    f"(supported extensions: {supported_ext_hint()})."
                ),
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    lang = lang_mod.get_lang(lang_name)
    move_mod = load_lang_move_module(lang_name)

    source_files = collect_source_files(source_path, list(lang.extensions))
    if not source_files:
        print(
            colorize(f"No {lang_name} files found in {rel(source_abs)}", "yellow"),
            file=sys.stderr,
        )
        sys.exit(1)

    scan_path = Path(resolve_path_fn(lang.default_src))
    graph = lang.build_dep_graph(scan_path)
    plan = build_directory_move_plan(
        source_abs=source_abs,
        source_path=source_path,
        dest_abs=dest_abs,
        source_files=source_files,
        move_mod=move_mod,
        graph=graph,
    )

    print_directory_move_plan(source_abs, dest_abs, plan)
    if dry_run:
        print(colorize("  Dry run — no files modified.", "yellow"))
        return

    apply_directory_move(
        source_abs=source_abs,
        dest_abs=dest_abs,
        source_path=source_path,
        external_changes=plan.external_changes,
        internal_changes=build_internal_directory_changes(plan),
    )

    print(colorize("  Done.", "green"))
    verify_hint = resolve_move_verify_hint(move_mod)
    if verify_hint:
        print(colorize(f"  Run `{verify_hint}` to verify.", "dim"))
    print()


__all__ = ["run_directory_move"]
