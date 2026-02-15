"""fix command: auto-fix mechanical issues with fixer registry and pipeline."""

import sys
from pathlib import Path

from ..lang.base import FixerConfig, FixResult
from ..utils import colorize, rel
from ._helpers import state_path, _write_query


def cmd_fix(args):
    """Auto-fix mechanical issues."""
    fixer_name = args.fixer
    if fixer_name == "review":
        return _cmd_fix_review(args)

    dry_run = getattr(args, "dry_run", False)
    path = Path(args.path)

    fixer = _load_fixer(args, fixer_name)

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
        _show_dry_run_samples(entries, results)

    if not dry_run:
        _apply_and_report(args, path, fixer, fixer_name, entries, results,
                          total_items, skip_reasons)
    else:
        _report_dry_run(args, fixer_name, entries, results, total_items)
    print()


def _cmd_fix_review(args):
    """Prepare structured review data with dimension templates for AI evaluation."""
    from ._helpers import resolve_lang, state_path
    from ..state import load_state
    from ..review import prepare_review, LANG_GUIDANCE
    from .review_cmd import _setup_lang

    lang = resolve_lang(args)
    if not lang:
        print(colorize("Error: could not detect language. Use --lang.", "red"))
        sys.exit(1)

    sp = state_path(args)
    state = load_state(sp)
    path = Path(args.path)

    found_files = _setup_lang(lang, path, state)
    data = prepare_review(path, lang, state, files=found_files or None)

    if data["total_candidates"] == 0:
        print(colorize("\n  All production files have been reviewed. Nothing to do.", "green"))
        return

    # Print review guide to terminal
    print(colorize(f"\n  {data['total_candidates']} files need design review\n", "bold"))

    dims = data.get("dimensions", [])
    prompts = data.get("dimension_prompts", {})
    for dim in dims:
        prompt = prompts.get(dim)
        if not prompt:
            continue
        print(colorize(f"  {dim}", "cyan"))
        print(colorize(f"    {prompt['description']}", "dim"))
        print(colorize("    Look for:", "dim"))
        for item in prompt.get("look_for", []):
            print(colorize(f"      - {item}", "dim"))
        skip = prompt.get("skip", [])
        if skip:
            print(colorize("    Skip:", "dim"))
            for item in skip:
                print(colorize(f"      - {item}", "dim"))
        print()

    lang_guide = data.get("lang_guidance") or LANG_GUIDANCE.get(lang.name, {})
    if lang_guide:
        print(colorize(f"  Language: {lang.name}", "cyan"))
        if lang_guide.get("naming"):
            print(colorize(f"    Naming: {lang_guide['naming']}", "dim"))
        for pattern in lang_guide.get("patterns", []):
            print(colorize(f"    - {pattern}", "dim"))
        print()

    _write_query(data)
    print(colorize("  Review data written to .desloppify/query.json", "dim"))
    print(colorize("\n  Next steps:", "cyan"))
    print(colorize("  1. Read query.json — it contains file contents and context", "dim"))
    print(colorize("  2. Evaluate each file against the dimensions above", "dim"))
    print(colorize("  3. Write findings as JSON array to a file (e.g. findings.json)", "dim"))
    print(colorize("  4. Import: desloppify review --import findings.json", "dim"))
    print(colorize("  5. For codebase-wide review: desloppify review --prepare --holistic", "dim"))
    print()


_COMMAND_POST_FIX: dict[str, object] = {}  # populated after _cascade_import_cleanup is defined


def _load_fixer(args, fixer_name: str) -> FixerConfig:
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
    # Attach command-level post-fix hooks (e.g. cascading import cleanup)
    if fixer_name in _COMMAND_POST_FIX and not fc.post_fix:
        fc.post_fix = _COMMAND_POST_FIX[fixer_name]
    return fc


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
                      skip_reasons=None):
    """Resolve findings in state, run post-fix hooks, and print retro."""
    from ..state import load_state, save_state
    sp = state_path(args)
    state = load_state(sp)
    prev_score = state.get("score", 0)
    resolved_ids = _resolve_fixer_results(state, results, fixer.detector, fixer_name)
    save_state(state, sp)

    delta = state["score"] - prev_score
    delta_str = f" ({'+' if delta > 0 else ''}{delta})" if delta else ""
    print(f"\n  Auto-resolved {len(resolved_ids)} findings in state")
    print(f"  Score: {state['score']}/100{delta_str}" +
          colorize(f"  (strict: {state.get('strict_score', 0)}/100)", "dim"))

    if fixer.post_fix:
        fixer.post_fix(path, state, prev_score, False)
        save_state(state, sp)

    if skip_reasons is None:
        skip_reasons = {}
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    fix_lang = resolve_lang(args)
    fix_lang_name = fix_lang.name if fix_lang else None
    narrative = compute_narrative(state, lang=fix_lang_name, command="fix")
    _write_query({"command": "fix", "fixer": fixer_name,
                  "files_fixed": len(results), "items_fixed": total_items,
                  "findings_resolved": len(resolved_ids),
                  "score": state["score"], "strict_score": state.get("strict_score", 0),
                  "prev_score": prev_score, "skip_reasons": skip_reasons,
                  "next_action": "Run `npx tsc --noEmit` to verify, then `desloppify scan` to update state",
                  "narrative": narrative})
    _print_fix_retro(fixer_name, len(entries), total_items, len(resolved_ids), skip_reasons)


def _report_dry_run(args, fixer_name, entries, results, total_items):
    """Write dry-run query and print review prompts."""
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    fix_lang = resolve_lang(args)
    fix_lang_name = fix_lang.name if fix_lang else None
    state = getattr(args, "_preloaded_state", {})
    narrative = compute_narrative(state, lang=fix_lang_name, command="fix")
    _write_query({"command": "fix", "fixer": fixer_name, "dry_run": True,
                  "files_would_fix": len(results), "items_would_fix": total_items,
                  "narrative": narrative})
    skipped = len(entries) - total_items
    if skipped > 0:
        print(colorize(f"\n  ── Review ──", "dim"))
        print(colorize(f"  {total_items} of {len(entries)} entries would be fixed ({skipped} skipped).", "dim"))
        for q in ["Do the sample changes look correct? Any false positives?",
                   "Are the skipped items truly unfixable, or could the fixer be improved?",
                   "Ready to run without --dry-run? (git push first!)"]:
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
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        pass

def _show_dry_run_samples(entries, results):
    import random
    random.seed(42)
    print(colorize("\n  ── Sample changes (before → after) ──", "cyan"))
    for r in random.sample(results, min(5, len(results))):
        _print_file_sample(r, entries)
    skipped = sum(len(r["removed"]) for r in results)
    if len(entries) > skipped:
        print(colorize(f"\n  Note: {len(entries) - skipped} of {len(entries)} entries were skipped "
                "(complex patterns, rest elements, etc.)", "dim"))
    print()

def _print_file_sample(result, entries):
    filepath, removed_set = result["file"], set(result["removed"])
    try:
        p = Path(filepath) if Path(filepath).is_absolute() else Path(".") / filepath
        lines = p.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return
    file_entries = [e for e in entries
                    if e["file"] == filepath and e.get("name", "") in removed_set]
    shown = 0
    for e in file_entries[:2]:
        line_idx = e.get("line", e.get("detail", {}).get("line", 0)) - 1
        if line_idx < 0 or line_idx >= len(lines):
            continue
        if shown == 0:
            print(colorize(f"\n  {rel(filepath)}:", "cyan"))
        name = e.get("name", e.get("summary", "?"))
        ctx_s, ctx_e = max(0, line_idx - 1), min(len(lines), line_idx + 2)
        print(colorize(f"    {name} (line {line_idx + 1}):", "dim"))
        for i in range(ctx_s, ctx_e):
            marker = colorize("  →", "red") if i == line_idx else "   "
            print(f"    {marker} {i+1:4d}  {lines[i][:90]}")
        shown += 1

def _cascade_import_cleanup(path: Path, state: dict, prev_score: int, dry_run: bool):
    """Post-fix hook: removing debug logs may leave orphaned imports."""
    from ..lang.typescript.detectors.unused import detect_unused
    from ..lang.typescript.fixers import fix_unused_imports
    print(colorize("\n  Running cascading import cleanup...", "dim"), file=sys.stderr)
    entries, _ = detect_unused(path, category="imports")
    results = fix_unused_imports(entries, dry_run=dry_run) if entries else []
    if not results:
        print(colorize("  Cascade: no orphaned imports found", "dim"))
        return
    n_removed = sum(len(r["removed"]) for r in results)
    n_lines = sum(r["lines_removed"] for r in results)
    print(colorize(f"  Cascade: removed {n_removed} now-orphaned imports "
            f"from {len(results)} files ({n_lines} lines)", "green"))
    resolved = _resolve_fixer_results(state, results, "unused", "debug-logs (cascade)")
    if resolved:
        print(f"  Cascade: auto-resolved {len(resolved)} import findings")


# Attach command-level post-fix hooks now that _cascade_import_cleanup is defined
_COMMAND_POST_FIX["debug-logs"] = _cascade_import_cleanup
_COMMAND_POST_FIX["dead-useeffect"] = _cascade_import_cleanup


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
    checklist = ["Run `npx tsc --noEmit` — does it still build?",
                 "Spot-check a few changed files — do the edits look correct?"]
    if skipped > 0 and not skip_reasons:
        checklist.append(f"{skipped} items were skipped. Should the fixer handle more patterns?")
    checklist += ["Run `desloppify scan` to update state. Did score improve as expected?",
                  "Are there cascading effects? (e.g., removing vars may orphan imports)",
                  "`git diff --stat` — review before committing. Anything surprising?"]
    print(colorize("  Checklist:", "dim"))
    for i, item in enumerate(checklist, 1):
        print(colorize(f"  {i}. {item}", "dim"))
