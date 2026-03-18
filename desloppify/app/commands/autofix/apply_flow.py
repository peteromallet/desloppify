"""Apply and reporting helpers for autofix command flows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from desloppify import state as state_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.queue_progress import show_score_with_plan_context
from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.app.commands.helpers.state import state_path
from desloppify.base.discovery.file_paths import rel
from desloppify.base.output.terminal import colorize
import desloppify.intelligence.narrative.core as narrative_mod

from .apply_retro import (
    _cascade_unused_import_cleanup,
    _SKIP_REASON_LABELS,
    _print_fix_retro,
    _resolve_fixer_results,
    _warn_uncommitted_changes,
)
from .fixer_selection import _COMMAND_POST_FIX

if TYPE_CHECKING:
    from desloppify.languages.framework import FixerConfig, LangRun


def _detect(fixer: FixerConfig, path: Path) -> list[dict]:
    print(colorize(f"\nDetecting {fixer.label}...", "dim"), file=sys.stderr)
    entries = fixer.detect(path)
    file_count = len(set(entry["file"] for entry in entries))
    print(
        colorize(
            f"  Found {len(entries)} {fixer.label} across {file_count} files\n", "dim"
        ),
        file=sys.stderr,
    )
    return entries


def _print_fix_summary(
    fixer: FixerConfig,
    results: list[dict],
    total_items: int,
    total_lines: int,
    dry_run: bool,
) -> None:
    verb = fixer.dry_verb if dry_run else fixer.verb
    lines_str = f" ({total_lines} lines)" if total_lines else ""
    print(
        colorize(
            f"\n  {verb} {total_items} {fixer.label} across {len(results)} files{lines_str}\n",
            "bold",
        )
    )
    for result in results[:30]:
        removed = result.get("removed", [])
        if removed:
            symbols = ", ".join(removed[:5])
            if len(removed) > 5:
                symbols += f" (+{len(removed) - 5})"
        else:
            symbols = result.get("summary", "fixed")
        extra = f"  ({result['lines_removed']} lines)" if result.get("lines_removed") else ""
        print(f"  {rel(result['file'])}{extra}  →  {symbols}")
    if len(results) > 30:
        print(f"  ... and {len(results) - 30} more files")


def _apply_and_report(
    args: argparse.Namespace,
    path: Path,
    fixer: FixerConfig,
    fixer_name: str,
    entries: list[dict],
    results: list[dict],
    total_items: int,
    lang: LangRun | None,
    skip_reasons: dict[str, int] | None = None,
) -> None:
    state_file = state_path(args)
    state = state_mod.load_state(state_file)
    prev = state_mod.score_snapshot(state)
    resolved_ids = _resolve_fixer_results(state, results, fixer.detector, fixer_name)
    state_mod.save_state(state, state_file)

    new = state_mod.score_snapshot(state)
    print(f"\n  Auto-resolved {len(resolved_ids)} issues in state")
    show_score_with_plan_context(state, prev)

    if fixer.post_fix:
        fixer.post_fix(path, state, prev.overall or 0, False, lang=lang)
        state_mod.save_state(state, state_file)

    if skip_reasons is None:
        skip_reasons = {}
    fix_lang = resolve_lang(args)
    fix_lang_name = fix_lang.name if fix_lang else None
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=fix_lang_name, command="autofix"),
    )
    typecheck_cmd = getattr(lang, "typecheck_cmd", "")
    if typecheck_cmd:
        next_action = f"Run `{typecheck_cmd}` to verify, then `desloppify scan` to update state"
    else:
        next_action = "Run `desloppify scan` to update state"

    write_query(
        {
            "command": "autofix",
            "fixer": fixer_name,
            "files_fixed": len(results),
            "items_fixed": total_items,
            "issues_resolved": len(resolved_ids),
            "overall_score": new.overall,
            "objective_score": new.objective,
            "strict_score": new.strict,
            "prev_overall_score": prev.overall,
            "prev_objective_score": prev.objective,
            "prev_strict_score": prev.strict,
            "skip_reasons": skip_reasons,
            "next_action": next_action,
            "narrative": narrative,
        }
    )
    _print_fix_retro(fixer_name, len(entries), total_items, len(resolved_ids), skip_reasons)


def _report_dry_run(
    args: argparse.Namespace,
    fixer_name: str,
    entries: list[dict],
    results: list[dict],
    total_items: int,
) -> None:
    runtime = command_runtime(args)
    fix_lang = resolve_lang(args)
    fix_lang_name = fix_lang.name if fix_lang else None
    state = runtime.state
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=fix_lang_name, command="autofix"),
    )
    write_query(
        {
            "command": "autofix",
            "fixer": fixer_name,
            "dry_run": True,
            "files_would_fix": len(results),
            "items_would_fix": total_items,
            "narrative": narrative,
        }
    )

    skipped = len(entries) - total_items
    if skipped > 0:
        print(colorize("\n  ── Review ──", "dim"))
        print(
            colorize(
                f"  {total_items} of {len(entries)} entries would be fixed ({skipped} skipped).",
                "dim",
            )
        )
        for question in [
            "Do the sample changes look correct? Any false positives?",
            "Are the skipped items truly unfixable, or could the fixer be improved?",
            "Ready to run without --dry-run? (git push first!)",
        ]:
            print(colorize(f"  - {question}", "dim"))


_COMMAND_POST_FIX["debug-logs"] = _cascade_unused_import_cleanup
_COMMAND_POST_FIX["dead-useeffect"] = _cascade_unused_import_cleanup


__all__ = [
    "_SKIP_REASON_LABELS",
    "_apply_and_report",
    "_detect",
    "_print_fix_summary",
    "_print_fix_retro",
    "_report_dry_run",
    "_resolve_fixer_results",
    "_warn_uncommitted_changes",
]
