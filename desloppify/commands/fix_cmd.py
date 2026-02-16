"""fix command: auto-fix mechanical issues with fixer registry and pipeline."""

import logging
import sys
from pathlib import Path

from ..lang.base import FixerConfig, FixResult
from ..utils import colorize, rel
from ._helpers import show_narrative_plan, show_narrative_reminders, state_path, _write_query
from ._show_terminal import show_fix_dry_run_samples

LOGGER = logging.getLogger(__name__)


def cmd_fix(args) -> None:
    """Auto-fix mechanical issues."""
    fixer_name = args.fixer

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
        _apply_and_report(args, path, fixer, fixer_name, entries, results, total_items, lang, skip_reasons)
    else:
        _report_dry_run(args, fixer_name, entries, results, total_items)
    print()


_COMMAND_POST_FIX: dict[str, object] = {}  # populated after _cascade_unused_import_cleanup is defined


def _load_fixer(args, fixer_name: str) -> tuple[object, FixerConfig]:
    """Resolve fixer from language plugin registry, or exit."""
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    if not lang:
        print(colorize("Could not detect language. Use --lang to specify.", "red"))
        sys.exit(1)
    if not lang.fixers:
        print(colorize(f"No auto-fixers available for {lang.name}.", "red"))
        sys.exit(1)
    if fixer_name not in lang.fixers:
        available = ", ".join(sorted(lang.fixers.keys()))
        print(colorize(f"Unknown fixer: {fixer_name}", "red"))
        print(colorize(f"  Available: {available}", "dim"))
        sys.exit(1)
    fc = lang.fixers[fixer_name]
    if fixer_name in _COMMAND_POST_FIX and not fc.post_fix:
        fc.post_fix = _COMMAND_POST_FIX[fixer_name]
    return lang, fc


def _detect(fixer: FixerConfig, path: Path) -> list[dict]:
    """Run detection and print summary."""
    print(colorize(f"\nDetecting {fixer.label}...", "dim"), file=sys.stderr)
    entries = fixer.detect(path)
    file_count = len(set(e["file"] for e in entries))
    print(colorize(f"  Found {len(entries)} {fixer.label} across {file_count} files\n", "dim"), file=sys.stderr)
    return entries


def _print_fix_summary(fixer: FixerConfig, results, total_items, total_lines, dry_run):
    """Print the per-file fix summary table."""
    verb = fixer.dry_verb if dry_run else fixer.verb
    lines_str = f" ({total_lines} lines)" if total_lines else ""
    print(colorize(f"\n  {verb} {total_items} {fixer.label} across {len(results)} files{lines_str}\n", "bold"))
    for r in results[:30]:
        syms = ", ".join(r["removed"][:5])
        if len(r["removed"]) > 5:
            syms += f" (+{len(r['removed']) - 5})"
        extra = f"  ({r['lines_removed']} lines)" if r.get("lines_removed") else ""
        print(f"  {rel(r['file'])}{extra}  →  {syms}")
    if len(results) > 30:
        print(f"  ... and {len(results) - 30} more files")


def _apply_and_report(args, path, fixer, fixer_name, entries, results, total_items,
                      lang, skip_reasons=None):
    """Resolve findings in state, run post-fix hooks, and print retro."""
    from ..state import (
        load_state,
        save_state,
        get_overall_score,
        get_objective_score,
        get_strict_score,
    )
    sp = state_path(args)
    state = load_state(sp)
    prev_overall = get_overall_score(state)
    prev_objective = get_objective_score(state)
    prev_strict = get_strict_score(state)
    resolved_ids = _resolve_fixer_results(state, results, fixer.detector, fixer_name)
    save_state(state, sp)

    new_overall = get_overall_score(state)
    new_objective = get_objective_score(state)
    new_strict = get_strict_score(state)
    print(f"\n  Auto-resolved {len(resolved_ids)} findings in state")
    if new_overall is not None and new_objective is not None and new_strict is not None:
        overall_delta = new_overall - (prev_overall or 0)
        delta_str = f" ({'+' if overall_delta > 0 else ''}{overall_delta:.1f})" if overall_delta else ""
        print(
            f"  Scores: overall {new_overall:.1f}/100{delta_str}"
            + colorize(f"  objective {new_objective:.1f}/100", "dim")
            + colorize(f"  strict {new_strict:.1f}/100", "dim")
        )
    else:
        print(colorize("  Scores unavailable — run `desloppify scan`.", "yellow"))

    if fixer.post_fix:
        try:
            fixer.post_fix(path, state, prev_overall or 0, False, lang=lang)
        except TypeError:
            fixer.post_fix(path, state, prev_overall or 0, False)
        save_state(state, sp)

    if skip_reasons is None:
        skip_reasons = {}
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    fix_lang = resolve_lang(args)
    fix_lang_name = fix_lang.name if fix_lang else None
    narrative = compute_narrative(
        state,
        lang=fix_lang_name,
        command="fix",
        config=getattr(args, "_config", None),
    )
    typecheck_cmd = getattr(lang, "typecheck_cmd", "")
    if typecheck_cmd:
        next_action = f"Run `{typecheck_cmd}` to verify, then `desloppify scan` to update state"
    else:
        next_action = "Run `desloppify scan` to update state"
    _write_query({
        "command": "fix", "fixer": fixer_name, "files_fixed": len(results), "items_fixed": total_items,
        "findings_resolved": len(resolved_ids), "overall_score": new_overall, "objective_score": new_objective,
        "strict_score": new_strict, "prev_overall_score": prev_overall, "prev_objective_score": prev_objective,
        "prev_strict_score": prev_strict, "skip_reasons": skip_reasons, "next_action": next_action, "narrative": narrative,
    })
    show_narrative_plan(narrative, max_risks=1)
    show_narrative_reminders(narrative, limit=2, skip_types={"report_scores", "review_findings_pending"})
    _print_fix_retro(fixer_name, len(entries), total_items, len(resolved_ids), skip_reasons)


def _report_dry_run(args, fixer_name, entries, results, total_items):
    """Write dry-run query and print review prompts."""
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    fix_lang = resolve_lang(args)
    fix_lang_name = fix_lang.name if fix_lang else None
    state = getattr(args, "_preloaded_state", {})
    narrative = compute_narrative(
        state,
        lang=fix_lang_name,
        command="fix_dry_run",
        config=getattr(args, "_config", None),
    )
    _write_query({
        "command": "fix", "fixer": fixer_name, "dry_run": True,
        "files_would_fix": len(results), "items_would_fix": total_items, "narrative": narrative,
    })
    show_narrative_plan(narrative, max_risks=1)
    show_narrative_reminders(narrative, limit=2, skip_types={"report_scores", "rescan_needed", "review_findings_pending"})
    skipped = len(entries) - total_items
    if skipped > 0:
        print(colorize("\n  ── Review ──", "dim"))
        print(colorize(f"  {total_items} of {len(entries)} entries would be fixed ({skipped} skipped).", "dim"))
        for q in [
            "Do the sample changes look correct? Any false positives?",
            "Are the skipped items truly unfixable, or could the fixer be improved?",
            "Ready to run without --dry-run? (git push first!)",
        ]:
            print(colorize(f"  - {q}", "dim"))


def _resolve_fixer_results(state, results, detector, fixer_name):
    """Mark matching open findings as fixed, return resolved IDs."""
    resolved_ids = []
    for r in results:
        rfile = rel(r["file"])
        for sym in r["removed"]:
            fid = f"{detector}::{rfile}::{sym}"
            if fid in state["findings"] and state["findings"][fid]["status"] == "open":
                state["findings"][fid]["status"] = "fixed"
                state["findings"][fid]["note"] = f"auto-fixed by desloppify fix {fixer_name}"
                resolved_ids.append(fid)
    return resolved_ids

def _warn_uncommitted_changes():
    import subprocess
    try:
        r = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5)
        if r.stdout.strip():
            print(colorize("\n  ⚠ You have uncommitted changes. Consider running:", "yellow"))
            print(colorize("    git add -A && git commit -m 'pre-fix checkpoint' && git push", "yellow"))
            print(colorize("    This ensures you can revert if the fixer produces unexpected results.\n", "dim"))
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.debug("Could not determine git working tree status", exc_info=exc)

def _cascade_unused_import_cleanup(
    path: Path, state: dict, prev_score: int, dry_run: bool, *, lang=None,
):
    """Post-fix hook: run language's unused-import fixer after structural edits."""
    _ = prev_score  # hook contract includes it; not needed in this hook
    if not lang or "unused-imports" not in getattr(lang, "fixers", {}):
        print(colorize("  Cascade: no unused-imports fixer for this language", "dim"))
        return

    fixer = lang.fixers["unused-imports"]
    print(colorize("\n  Running cascading import cleanup...", "dim"), file=sys.stderr)
    entries = fixer.detect(path)
    if not entries:
        print(colorize("  Cascade: no orphaned imports found", "dim"))
        return

    raw = fixer.fix(entries, dry_run=dry_run)
    if isinstance(raw, FixResult):
        results = raw.entries
    else:
        results = raw

    if not results:
        print(colorize("  Cascade: no orphaned imports found", "dim"))
        return
    n_removed = sum(len(r["removed"]) for r in results)
    n_lines = sum(r["lines_removed"] for r in results)
    print(colorize(f"  Cascade: removed {n_removed} now-orphaned imports from {len(results)} files ({n_lines} lines)", "green"))
    resolved = _resolve_fixer_results(state, results, fixer.detector, "cascade-unused-imports")
    if resolved:
        print(f"  Cascade: auto-resolved {len(resolved)} import findings")


# Attach command-level post-fix hooks now that _cascade_unused_import_cleanup is defined
_COMMAND_POST_FIX["debug-logs"] = _cascade_unused_import_cleanup
_COMMAND_POST_FIX["dead-useeffect"] = _cascade_unused_import_cleanup


_SKIP_REASON_LABELS = {
    "rest_element": "has ...rest (removing changes rest contents)",
    "array_destructuring": "array destructuring (positional — can't remove)",
    "function_param": "function/callback parameter (use `fix unused-params` to prefix with _)",
    "standalone_var_with_call": "standalone variable with function call (may have side effects)",
    "no_destr_context": "destructuring member without context",
    "out_of_range": "line out of range (stale data?)",
    "other": "other patterns (needs manual review)",
}

def _print_fix_retro(fixer_name: str, detected: int, fixed: int, resolved: int,
                     skip_reasons: dict[str, int] | None = None):
    """Print post-fix reflection prompts with skip reason breakdown."""
    skipped = detected - fixed
    print(colorize("\n  ── Post-fix check ──", "dim"))
    print(colorize(f"  Fixed {fixed}/{detected} ({skipped} skipped, {resolved} findings resolved)", "dim"))
    if skip_reasons and skipped > 0:
        print(colorize(f"\n  Skip reasons ({skipped} total):", "dim"))
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            print(colorize(f"    {count:4d}  {_SKIP_REASON_LABELS.get(reason, reason)}", "dim"))
        print()
    checklist = [
        "Run your language typecheck/build command — does it still build?",
        "Spot-check a few changed files — do the edits look correct?",
    ]
    if skipped > 0 and not skip_reasons:
        checklist.append(f"{skipped} items were skipped. Should the fixer handle more patterns?")
    checklist += [
        "Run `desloppify scan` to update state. Did score improve as expected?",
        "Are there cascading effects? (e.g., removing vars may orphan imports)",
        "`git diff --stat` — review before committing. Anything surprising?",
    ]
    print(colorize("  Checklist:", "dim"))
    for i, item in enumerate(checklist, 1):
        print(colorize(f"  {i}. {item}", "dim"))
