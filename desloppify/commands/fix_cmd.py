"""fix command: auto-fix mechanical issues with fixer registry and pipeline."""

import sys
from pathlib import Path

from ..utils import c, rel
from ..cli import _state_path, _write_query


def cmd_fix(args):
    """Auto-fix mechanical issues."""
    fixer_name = args.fixer
    dry_run = getattr(args, "dry_run", False)
    path = Path(args.path)

    fixer = _load_fixer(args, fixer_name)

    if not dry_run:
        _warn_uncommitted_changes()

    entries = _detect(fixer, path)
    if not entries:
        print(c(f"No {fixer['label']} found.", "green"))
        return

    results = fixer["fix"](entries, dry_run=dry_run)
    total_items = sum(len(r["removed"]) for r in results)
    total_lines = sum(r.get("lines_removed", 0) for r in results)
    _print_fix_summary(fixer, results, total_items, total_lines, dry_run)

    if dry_run and results:
        _show_dry_run_samples(entries, results)

    if not dry_run:
        _apply_and_report(args, path, fixer, fixer_name, entries, results, total_items)
    else:
        _report_dry_run(fixer_name, entries, results, total_items)
    print()


def _load_fixer(args, fixer_name: str) -> dict:
    """Resolve fixer from language plugin or built-in registry, or exit."""
    from ..cli import _resolve_lang
    lang = _resolve_lang(args)
    if lang and lang.fixers and fixer_name in lang.fixers:
        fc = lang.fixers[fixer_name]
        return {k: getattr(fc, k) for k in
                ("label", "detect", "fix", "detector", "verb", "dry_verb", "post_fix")}
    fixer = _get_fixer(fixer_name)
    if fixer is None:
        print(c(f"Unknown fixer: {fixer_name}", "red"))
        sys.exit(1)
    return fixer


def _detect(fixer: dict, path: Path) -> list[dict]:
    """Run detection and print summary."""
    print(c(f"\nDetecting {fixer['label']}...", "dim"), file=sys.stderr)
    entries = fixer["detect"](path)
    file_count = len(set(e["file"] for e in entries))
    print(c(f"  Found {len(entries)} {fixer['label']} across {file_count} files\n", "dim"), file=sys.stderr)
    return entries


def _print_fix_summary(fixer, results, total_items, total_lines, dry_run):
    """Print the per-file fix summary table."""
    verb = fixer.get("dry_verb", "Would fix") if dry_run else fixer.get("verb", "Fixed")
    lines_str = f" ({total_lines} lines)" if total_lines else ""
    print(c(f"\n  {verb} {total_items} {fixer['label']} across {len(results)} files{lines_str}\n", "bold"))
    for r in results[:30]:
        syms = ", ".join(r["removed"][:5])
        if len(r["removed"]) > 5:
            syms += f" (+{len(r['removed']) - 5})"
        extra = f"  ({r['lines_removed']} lines)" if r.get("lines_removed") else ""
        print(f"  {rel(r['file'])}{extra}  →  {syms}")
    if len(results) > 30:
        print(f"  ... and {len(results) - 30} more files")


def _apply_and_report(args, path, fixer, fixer_name, entries, results, total_items):
    """Resolve findings in state, run post-fix hooks, and print retro."""
    from ..state import load_state, save_state
    sp = _state_path(args)
    state = load_state(sp)
    prev_score = state.get("score", 0)
    resolved_ids = _resolve_fixer_results(state, results, fixer["detector"], fixer_name)
    save_state(state, sp)

    delta = state["score"] - prev_score
    delta_str = f" ({'+' if delta > 0 else ''}{delta})" if delta else ""
    print(f"\n  Auto-resolved {len(resolved_ids)} findings in state")
    print(f"  Score: {state['score']}/100{delta_str}" +
          c(f"  (strict: {state.get('strict_score', 0)}/100)", "dim"))

    if fixer.get("post_fix"):
        fixer["post_fix"](path, state, prev_score, False)
        save_state(state, sp)

    skip_reasons = getattr(results, "skip_reasons", {})
    _write_query({"command": "fix", "fixer": fixer_name,
                  "files_fixed": len(results), "items_fixed": total_items,
                  "findings_resolved": len(resolved_ids),
                  "score": state["score"], "strict_score": state.get("strict_score", 0),
                  "prev_score": prev_score, "skip_reasons": skip_reasons,
                  "next_action": "Run `npx tsc --noEmit` to verify, then `desloppify scan` to update state"})
    _print_fix_retro(fixer_name, len(entries), total_items, len(resolved_ids), skip_reasons)


def _report_dry_run(fixer_name, entries, results, total_items):
    """Write dry-run query and print review prompts."""
    _write_query({"command": "fix", "fixer": fixer_name, "dry_run": True,
                  "files_would_fix": len(results), "items_would_fix": total_items})
    skipped = len(entries) - total_items
    if skipped > 0:
        print(c(f"\n  ── Review ──", "dim"))
        print(c(f"  {total_items} of {len(entries)} entries would be fixed ({skipped} skipped).", "dim"))
        for q in ["Do the sample changes look correct? Any false positives?",
                   "Are the skipped items truly unfixable, or could the fixer be improved?",
                   "Ready to run without --dry-run? (git push first!)"]:
            print(c(f"  - {q}", "dim"))


def _detect_unused(path, category):
    from ..lang.typescript.detectors.unused import detect_unused
    return detect_unused(path, category=category)[0]

def _detect_logs(path):
    from ..lang.typescript.detectors.logs import detect_logs
    return detect_logs(path)[0]

def _detect_dead_exports(path):
    from ..lang.typescript.detectors.exports import detect_dead_exports
    return detect_dead_exports(path)[0]

def _detect_smell_flat(path, smell_id):
    from ..lang.typescript.detectors.smells import detect_smells
    return next((e.get("matches", []) for e in detect_smells(path)[0] if e["id"] == smell_id), [])

def _get_fixer(name: str) -> dict | None:
    """Lazy-load and return fixer config by name."""
    from ..lang.typescript import fixers as F
    _udet = lambda cat: lambda p: _detect_unused(p, cat)
    R, DV = "Removed", "Would remove"
    registry = {
        "unused-imports": {"label": "unused imports", "detector": "unused",
                           "detect": _udet("imports"), "fix": F.fix_unused_imports,
                           "verb": R, "dry_verb": DV},
        "debug-logs": {"label": "tagged debug logs", "detector": "logs",
                       "detect": _detect_logs, "fix": _wrap_debug_logs_fix(F.fix_debug_logs),
                       "verb": R, "dry_verb": DV, "post_fix": _cascade_import_cleanup},
        "dead-exports": {"label": "dead exports", "detector": "exports",
                         "detect": _detect_dead_exports, "fix": F.fix_dead_exports,
                         "verb": "De-exported", "dry_verb": "Would de-export"},
        "unused-vars": {"label": "unused vars", "detector": "unused",
                        "detect": _udet("vars"),
                        "fix": _wrap_unused_vars_fix(F.fix_unused_vars),
                        "verb": R, "dry_verb": DV},
        "unused-params": {"label": "unused params", "detector": "unused",
                          "detect": _udet("vars"), "fix": F.fix_unused_params,
                          "verb": "Prefixed", "dry_verb": "Would prefix"},
        "dead-useeffect": {"label": "dead useEffect calls", "detector": "smells",
                           "detect": lambda p: _detect_smell_flat(p, "dead_useeffect"),
                           "fix": F.fix_dead_useeffect,
                           "verb": R, "dry_verb": DV, "post_fix": _cascade_import_cleanup},
        "empty-if-chain": {"label": "empty if/else chains", "detector": "smells",
                           "detect": lambda p: _detect_smell_flat(p, "empty_if_chain"),
                           "fix": F.fix_empty_if_chain, "verb": R, "dry_verb": DV},
    }
    return registry.get(name)

class _ResultsWithMeta(list):
    skip_reasons: dict[str, int] = {}

def _wrap_unused_vars_fix(fix_fn):
    def wrapper(entries, *, dry_run=False):
        results, skip_reasons = fix_fn(entries, dry_run=dry_run)
        results = _ResultsWithMeta(results)
        results.skip_reasons = skip_reasons
        return results
    return wrapper

def _wrap_debug_logs_fix(fix_fn):
    def wrapper(entries, *, dry_run=False):
        results = fix_fn(entries, dry_run=dry_run)
        for r in results:
            r["removed"] = r.get("tags", r.get("removed", []))
        return results
    return wrapper

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
            print(c("\n  ⚠ You have uncommitted changes. Consider running:", "yellow"))
            print(c("    git add -A && git commit -m 'pre-fix checkpoint' && git push", "yellow"))
            print(c("    This ensures you can revert if the fixer produces unexpected results.\n", "dim"))
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        pass

def _show_dry_run_samples(entries, results):
    import random
    random.seed(42)
    print(c("\n  ── Sample changes (before → after) ──", "cyan"))
    for r in random.sample(results, min(5, len(results))):
        _print_file_sample(r, entries)
    skipped = sum(len(r["removed"]) for r in results)
    if len(entries) > skipped:
        print(c(f"\n  Note: {len(entries) - skipped} of {len(entries)} entries were skipped "
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
            print(c(f"\n  {rel(filepath)}:", "cyan"))
        name = e.get("name", e.get("summary", "?"))
        ctx_s, ctx_e = max(0, line_idx - 1), min(len(lines), line_idx + 2)
        print(c(f"    {name} (line {line_idx + 1}):", "dim"))
        for i in range(ctx_s, ctx_e):
            marker = c("  →", "red") if i == line_idx else "   "
            print(f"    {marker} {i+1:4d}  {lines[i][:90]}")
        shown += 1

def _cascade_import_cleanup(path: Path, state: dict, prev_score: int, dry_run: bool):
    """Post-fix hook: removing debug logs may leave orphaned imports."""
    from ..lang.typescript.detectors.unused import detect_unused
    from ..lang.typescript.fixers import fix_unused_imports
    print(c("\n  Running cascading import cleanup...", "dim"), file=sys.stderr)
    entries, _ = detect_unused(path, category="imports")
    results = fix_unused_imports(entries, dry_run=dry_run) if entries else []
    if not results:
        print(c("  Cascade: no orphaned imports found", "dim"))
        return
    n_removed = sum(len(r["removed"]) for r in results)
    n_lines = sum(r["lines_removed"] for r in results)
    print(c(f"  Cascade: removed {n_removed} now-orphaned imports "
            f"from {len(results)} files ({n_lines} lines)", "green"))
    resolved = _resolve_fixer_results(state, results, "unused", "debug-logs (cascade)")
    if resolved:
        print(f"  Cascade: auto-resolved {len(resolved)} import findings")


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
    print(c("\n  ── Post-fix check ──", "dim"))
    print(c(f"  Fixed {fixed}/{detected} ({skipped} skipped, {resolved} findings resolved)", "dim"))
    if skip_reasons and skipped > 0:
        print(c(f"\n  Skip reasons ({skipped} total):", "dim"))
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            print(c(f"    {count:4d}  {_SKIP_REASON_LABELS.get(reason, reason)}", "dim"))
        print()
    checklist = ["Run `npx tsc --noEmit` — does it still build?",
                 "Spot-check a few changed files — do the edits look correct?"]
    if skipped > 0 and not skip_reasons:
        checklist.append(f"{skipped} items were skipped. Should the fixer handle more patterns?")
    checklist += ["Run `desloppify scan` to update state. Did score improve as expected?",
                  "Are there cascading effects? (e.g., removing vars may orphan imports)",
                  "`git diff --stat` — review before committing. Anything surprising?"]
    print(c("  Checklist:", "dim"))
    for i, item in enumerate(checklist, 1):
        print(c(f"  {i}. {item}", "dim"))
