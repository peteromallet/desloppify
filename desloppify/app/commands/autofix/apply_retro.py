"""Retro/checklist and git-safety helpers for autofix apply flow."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from desloppify.base.discovery.file_paths import rel
from desloppify.base.output.terminal import colorize
from desloppify.languages.framework import FixResult

if TYPE_CHECKING:
    from desloppify.languages.framework import LangRun


def _resolve_fixer_results(
    state: dict, results: list[dict], detector: str, fixer_name: str
) -> list[str]:
    resolved_ids = []
    for result in results:
        result_file = rel(result["file"])
        for symbol in result["removed"]:
            issue_id = f"{detector}::{result_file}::{symbol}"
            if issue_id in state["issues"] and state["issues"][issue_id]["status"] == "open":
                state["issues"][issue_id]["status"] = "fixed"
                state["issues"][issue_id]["note"] = (
                    f"auto-fixed by desloppify autofix {fixer_name}"
                )
                resolved_ids.append(issue_id)
    return resolved_ids


def _warn_uncommitted_changes() -> None:
    try:
        git_path = shutil.which("git")
        if not git_path:
            return
        result = subprocess.run(
            [git_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )  # nosec B603
        if result.stdout.strip():
            print(colorize("\n  ⚠ You have uncommitted changes. Consider running:", "yellow"))
            print(
                colorize(
                    "    git add -A && git commit -m 'pre-fix checkpoint' && git push",
                    "yellow",
                )
            )
            print(
                colorize(
                    "    This ensures you can revert if the fixer produces unexpected results.\n",
                    "dim",
                )
            )
    except (OSError, subprocess.TimeoutExpired):
        return


def _cascade_unused_import_cleanup(
    path: Path,
    state: dict,
    _prev_score: float,
    dry_run: bool,
    *,
    lang: LangRun | None = None,
) -> None:
    if not lang or "unused-imports" not in getattr(lang, "fixers", {}):
        print(colorize("  Cascade: no unused-imports fixer for this language", "dim"))
        return

    fixer = lang.fixers["unused-imports"]
    print(colorize("\n  Running cascading import cleanup...", "dim"), file=sys.stderr)
    entries = fixer.detect(path)
    if not entries:
        print(colorize("  Cascade: no orphaned imports found", "dim"))
        return

    raw_results = fixer.fix(entries, dry_run=dry_run)
    results = raw_results.entries if isinstance(raw_results, FixResult) else raw_results

    if not results:
        print(colorize("  Cascade: no orphaned imports found", "dim"))
        return

    removed_count = sum(len(result["removed"]) for result in results)
    removed_lines = sum(result["lines_removed"] for result in results)
    print(
        colorize(
            f"  Cascade: removed {removed_count} now-orphaned imports "
            f"from {len(results)} files ({removed_lines} lines)",
            "green",
        )
    )
    resolved = _resolve_fixer_results(
        state, results, fixer.detector, "cascade-unused-imports"
    )
    if resolved:
        print(f"  Cascade: auto-resolved {len(resolved)} import issues")


_SKIP_REASON_LABELS = {
    "rest_element": "has ...rest (removing changes rest contents)",
    "array_destructuring": "array destructuring (positional — can't remove)",
    "function_param": "function/callback parameter (use `fix unused-params` to prefix with _)",
    "standalone_var_with_call": "standalone variable with function call (may have side effects)",
    "no_destr_context": "destructuring member without context",
    "out_of_range": "line out of range (stale data?)",
    "other": "other patterns (needs manual review)",
}


def _print_fix_retro(
    fixer_name: str,
    detected: int,
    fixed: int,
    resolved: int,
    skip_reasons: dict[str, int] | None = None,
):
    skipped = detected - fixed
    print(colorize("\n  ── Post-fix check ──", "dim"))
    print(
        colorize(
            f"  Fixed {fixed}/{detected} ({skipped} skipped, {resolved} issues resolved)",
            "dim",
        )
    )
    if skip_reasons and skipped > 0:
        print(colorize(f"\n  Skip reasons ({skipped} total):", "dim"))
        for reason, count in sorted(skip_reasons.items(), key=lambda item: -item[1]):
            print(
                colorize(
                    f"    {count:4d}  {_SKIP_REASON_LABELS.get(reason, reason)}", "dim"
                )
            )
        print()

    checklist = [
        "Run your language typecheck/build command — does it still build?",
        "Spot-check a few changed files — do the edits look correct?",
    ]
    if skipped > 0 and not skip_reasons:
        checklist.append(
            f"{skipped} items were skipped. Should the fixer handle more patterns?"
        )
    checklist += [
        "Run `desloppify scan` to update state and refresh issues.",
        "Are there cascading effects? (e.g., removing vars may orphan imports)",
        "`git diff --stat` — review before committing. Anything surprising?",
    ]
    print(colorize("  Checklist:", "dim"))
    for index, item in enumerate(checklist, 1):
        print(colorize(f"  {index}. {item}", "dim"))


__all__ = [
    "_cascade_unused_import_cleanup",
    "_print_fix_retro",
    "_resolve_fixer_results",
    "_warn_uncommitted_changes",
]
