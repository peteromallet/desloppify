"""fix command: auto-fix mechanical issues with fixer registry and pipeline."""

from __future__ import annotations

from pathlib import Path

from desloppify.app.commands._show_terminal import show_fix_dry_run_samples
from desloppify.languages.framework.base.types import FixResult
from desloppify.utils import colorize

from .apply_flow import (
    _apply_and_report,
    _detect,
    _print_fix_summary,
    _report_dry_run,
    _warn_uncommitted_changes,
)
from .options import _load_fixer
from .review_flow import _cmd_fix_review


def cmd_fix(args) -> None:
    """Auto-fix mechanical issues."""
    fixer_name = args.fixer
    if fixer_name == "review":
        _cmd_fix_review(args)
        return

    dry_run = getattr(args, "dry_run", False)
    path = Path(args.path)

    lang, fixer = _load_fixer(args, fixer_name)

    if not dry_run:
        _warn_uncommitted_changes()
    entries = _detect(fixer, path)
    if not entries:
        print(colorize(f"No {fixer.label} found.", "green"))
        return

    raw = fixer.fix(entries, dry_run=dry_run)
    if isinstance(raw, FixResult):
        results = raw.entries
        skip_reasons = raw.skip_reasons
    else:
        results = raw
        skip_reasons = {}
    total_items = sum(len(r["removed"]) for r in results)
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
