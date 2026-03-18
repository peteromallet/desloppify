"""autofix command: auto-fix mechanical issues with fixer registry and pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from desloppify.app.commands.autofix.preview import show_fix_dry_run_samples
from desloppify.base.output.terminal import colorize

from .apply_flow import (
    _apply_and_report,
    _detect,
    _print_fix_summary,
    _report_dry_run,
    _warn_uncommitted_changes,
)
from .fixer_selection import resolve_fixer_config


def cmd_autofix(args: argparse.Namespace) -> None:
    """Auto-fix mechanical issues."""
    fixer_name = args.fixer

    dry_run = getattr(args, "dry_run", False)
    path = Path(args.path)

    lang, fixer = resolve_fixer_config(args, fixer_name)

    if not dry_run:
        _warn_uncommitted_changes()
    entries = _detect(fixer, path)
    if not entries:
        print(colorize(f"No {fixer.label} found.", "green"))
        return

    raw = fixer.fix(entries, dry_run=dry_run)
    results = raw.entries
    skip_reasons = raw.skip_reasons
    total_items = sum(len(r["removed"]) if "removed" in r else 1 for r in results)
    total_lines = sum(r.get("lines_removed", 0) for r in results)
    _print_fix_summary(fixer, results, total_items, total_lines, dry_run)

    if dry_run and results:
        show_fix_dry_run_samples(entries, results)

    if not dry_run:
        _apply_and_report(
            args,
            path,
            fixer,
            fixer_name,
            entries,
            results,
            total_items,
            lang,
            skip_reasons,
        )
    else:
        _report_dry_run(args, fixer_name, entries, results, total_items)
    print()
