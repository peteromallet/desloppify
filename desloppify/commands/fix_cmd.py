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

    # Check language-specific fixer registry first
    from ..cli import _resolve_lang
    lang = _resolve_lang(args)
    if lang and lang.fixers and fixer_name in lang.fixers:
        fixer_config = lang.fixers[fixer_name]
        fixer = {
            "label": fixer_config.label,
            "detect": fixer_config.detect,
            "fix": fixer_config.fix,
            "detector": fixer_config.detector,
            "verb": fixer_config.verb,
            "dry_verb": fixer_config.dry_verb,
            "post_fix": fixer_config.post_fix,
        }
    else:
        fixer = _get_fixer(fixer_name)
    if fixer is None:
        print(c(f"Unknown fixer: {fixer_name}", "red"))
        sys.exit(1)

    if not dry_run:
        _warn_uncommitted_changes()

    # Step 1: Detect
    print(c(f"\nDetecting {fixer['label']}...", "dim"), file=sys.stderr)
    entries = fixer["detect"](path)
    file_count = len(set(e["file"] for e in entries))
    print(c(f"  Found {len(entries)} {fixer['label']} across {file_count} files\n", "dim"), file=sys.stderr)

    if not entries:
        print(c(f"No {fixer['label']} found.", "green"))
        return

    # Step 2: Fix
    results = fixer["fix"](entries, dry_run=dry_run)
    total_items = sum(len(r["removed"]) for r in results)
    total_lines = sum(r.get("lines_removed", 0) for r in results)
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

    if dry_run and results:
        _show_dry_run_samples(entries, results, fixer_name)

    # Step 3: Resolve in state
    if not dry_run:
        sp = _state_path(args)
        from ..state import load_state, save_state
        state = load_state(sp)
        prev_score = state.get("score", 0)

        resolved_ids = _resolve_fixer_results(state, results, fixer["detector"], fixer_name)
        save_state(state, sp)

        delta = state["score"] - prev_score
        delta_str = f" ({'+' if delta > 0 else ''}{delta})" if delta else ""
        print(f"\n  Auto-resolved {len(resolved_ids)} findings in state")
        print(f"  Score: {state['score']}/100{delta_str}" +
              c(f"  (strict: {state.get('strict_score', 0)}/100)", "dim"))

        post_fix = fixer.get("post_fix")
        if post_fix:
            post_fix(path, state, prev_score, dry_run)
            save_state(state, sp)

        _write_query({"command": "fix", "fixer": fixer_name,
                      "files_fixed": len(results), "items_fixed": total_items,
                      "findings_resolved": len(resolved_ids),
                      "score": state["score"], "strict_score": state.get("strict_score", 0),
                      "prev_score": prev_score,
                      "skip_reasons": getattr(results, "skip_reasons", {}),
                      "next_action": "Run `npx tsc --noEmit` to verify, then `desloppify scan` to update state"})

        skip_reasons = getattr(results, "skip_reasons", {})
        _print_fix_retro(fixer_name, len(entries), total_items, len(resolved_ids), skip_reasons)
    else:
        _write_query({"command": "fix", "fixer": fixer_name, "dry_run": True,
                      "files_would_fix": len(results), "items_would_fix": total_items})

        skipped = len(entries) - total_items
        if skipped > 0:
            print(c(f"\n  ── Review ──", "dim"))
            print(c(f"  {total_items} of {len(entries)} entries would be fixed ({skipped} skipped).", "dim"))
            print(c(f"  1. Do the sample changes look correct? Any false positives?", "dim"))
            print(c(f"  2. Are the skipped items truly unfixable, or could the fixer be improved?", "dim"))
            print(c(f"  3. Ready to run without --dry-run? (git push first!)", "dim"))

    print()


# ── Fixer registry ────────────────────────────────────────


def _get_fixer(name: str) -> dict | None:
    """Lazy-load and return fixer config by name."""
    if name == "unused-imports":
        from ..lang.typescript.detectors.unused import detect_unused
        from ..lang.typescript.fixers import fix_unused_imports
        return {
            "label": "unused imports",
            "detect": lambda path: detect_unused(path, category="imports")[0],
            "fix": fix_unused_imports,
            "detector": "unused",
            "verb": "Removed", "dry_verb": "Would remove",
        }
    elif name == "debug-logs":
        from ..lang.typescript.detectors.logs import detect_logs
        from ..lang.typescript.fixers import fix_debug_logs
        return {
            "label": "tagged debug logs",
            "detect": lambda path: detect_logs(path)[0],
            "fix": _wrap_debug_logs_fix(fix_debug_logs),
            "detector": "logs",
            "verb": "Removed", "dry_verb": "Would remove",
            "post_fix": _cascade_import_cleanup,
        }
    elif name == "dead-exports":
        from ..lang.typescript.detectors.exports import detect_dead_exports
        from ..lang.typescript.fixers import fix_dead_exports
        return {
            "label": "dead exports",
            "detect": lambda path: detect_dead_exports(path)[0],
            "fix": fix_dead_exports,
            "detector": "exports",
            "verb": "De-exported", "dry_verb": "Would de-export",
        }
    elif name == "unused-vars":
        from ..lang.typescript.detectors.unused import detect_unused
        from ..lang.typescript.fixers import fix_unused_vars
        return {
            "label": "unused vars",
            "detect": lambda path: detect_unused(path, category="vars")[0],
            "fix": _wrap_unused_vars_fix(fix_unused_vars),
            "detector": "unused",
            "verb": "Removed", "dry_verb": "Would remove",
        }
    elif name == "unused-params":
        from ..lang.typescript.detectors.unused import detect_unused
        from ..lang.typescript.fixers import fix_unused_params
        return {
            "label": "unused params",
            "detect": lambda path: detect_unused(path, category="vars")[0],
            "fix": fix_unused_params,
            "detector": "unused",
            "verb": "Prefixed", "dry_verb": "Would prefix",
        }
    elif name == "dead-useeffect":
        from ..lang.typescript.fixers import fix_dead_useeffect
        return {
            "label": "dead useEffect calls",
            "detect": lambda path: _detect_smell_flat(path, "dead_useeffect"),
            "fix": fix_dead_useeffect,
            "detector": "smells",
            "verb": "Removed", "dry_verb": "Would remove",
            "post_fix": _cascade_import_cleanup,
        }
    elif name == "empty-if-chain":
        from ..lang.typescript.fixers import fix_empty_if_chain
        return {
            "label": "empty if/else chains",
            "detect": lambda path: _detect_smell_flat(path, "empty_if_chain"),
            "fix": fix_empty_if_chain,
            "detector": "smells",
            "verb": "Removed", "dry_verb": "Would remove",
        }
    return None


# ── Pipeline helpers ──────────────────────────────────────


def _wrap_unused_vars_fix(fix_fn):
    """Wrap unused-vars fixer to attach skip_reasons as attribute on result list."""
    def wrapper(entries, *, dry_run=False):
        results, skip_reasons = fix_fn(entries, dry_run=dry_run)
        results = _ResultsWithMeta(results)
        results.skip_reasons = skip_reasons
        return results
    return wrapper


class _ResultsWithMeta(list):
    """List subclass that carries metadata attributes (e.g. skip_reasons)."""
    skip_reasons: dict[str, int] = {}


def _wrap_debug_logs_fix(fix_fn):
    """Wrap debug-logs fixer to normalize result shape (tags -> removed)."""
    def wrapper(entries, *, dry_run=False):
        results = fix_fn(entries, dry_run=dry_run)
        for r in results:
            r["removed"] = r.get("tags", r.get("removed", []))
        return results
    return wrapper


def _detect_smell_flat(path: Path, smell_id: str) -> list[dict]:
    """Run smell detector and extract flat match list for a specific smell type."""
    from ..lang.typescript.detectors.smells import detect_smells
    entries, _ = detect_smells(path)
    for e in entries:
        if e["id"] == smell_id:
            return e.get("matches", [])
    return []


def _resolve_fixer_results(state: dict, results: list[dict], detector: str, fixer_name: str) -> list[str]:
    """Resolve findings in state for fixer results."""
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
    """Warn if there are uncommitted changes."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            print(c("\n  ⚠ You have uncommitted changes. Consider running:", "yellow"))
            print(c("    git add -A && git commit -m 'pre-fix checkpoint' && git push", "yellow"))
            print(c("    This ensures you can revert if the fixer produces unexpected results.\n", "dim"))
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        pass


def _show_dry_run_samples(entries: list[dict], results: list[dict], fixer_name: str):
    """Show before/after samples for dry-run."""
    import random
    random.seed(42)

    sample_results = random.sample(results, min(5, len(results)))

    print(c("\n  ── Sample changes (before → after) ──", "cyan"))
    for r in sample_results:
        filepath = r["file"]
        removed_set = set(r["removed"])
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else Path(".") / filepath
            lines = p.read_text().splitlines()

            file_entries = [
                e for e in entries
                if e["file"] == filepath and e.get("name", "") in removed_set
            ]
            if not file_entries:
                continue

            shown = 0
            for e in file_entries[:2]:
                line_idx = e.get("line", e.get("detail", {}).get("line", 0)) - 1
                if line_idx < 0 or line_idx >= len(lines):
                    continue

                name = e.get("name", e.get("summary", "?"))
                context_start = max(0, line_idx - 1)
                context_end = min(len(lines), line_idx + 2)

                if shown == 0:
                    print(c(f"\n  {rel(filepath)}:", "cyan"))

                print(c(f"    {name} (line {line_idx + 1}):", "dim"))
                for i in range(context_start, context_end):
                    marker = c("  →", "red") if i == line_idx else "   "
                    print(f"    {marker} {i+1:4d}  {lines[i][:90]}")
                shown += 1
        except (OSError, UnicodeDecodeError):
            continue

    skipped = sum(len(r["removed"]) for r in results)
    detected = len(entries)
    if detected > skipped:
        print(c(f"\n  Note: {detected - skipped} of {detected} entries were skipped (complex patterns, rest elements, etc.)", "dim"))
    print()


def _cascade_import_cleanup(path: Path, state: dict, prev_score: int, dry_run: bool):
    """Post-fix hook: removing debug logs may leave orphaned imports."""
    from ..lang.typescript.detectors.unused import detect_unused
    from ..lang.typescript.fixers import fix_unused_imports

    print(c("\n  Running cascading import cleanup...", "dim"), file=sys.stderr)
    import_entries, _ = detect_unused(path, category="imports")
    if not import_entries:
        print(c("  Cascade: no orphaned imports found", "dim"))
        return

    import_results = fix_unused_imports(import_entries, dry_run=dry_run)
    if not import_results:
        print(c("  Cascade: no orphaned imports found", "dim"))
        return

    import_removed = sum(len(r["removed"]) for r in import_results)
    import_lines = sum(r["lines_removed"] for r in import_results)
    print(c(f"  Cascade: removed {import_removed} now-orphaned imports "
            f"from {len(import_results)} files ({import_lines} lines)", "green"))

    resolved = _resolve_fixer_results(state, import_results, "unused", "debug-logs (cascade)")
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
            label = _SKIP_REASON_LABELS.get(reason, reason)
            print(c(f"    {count:4d}  {label}", "dim"))
        print()

    print(c("  Checklist:", "dim"))
    print(c("  1. Run `npx tsc --noEmit` — does it still build?", "dim"))
    print(c("  2. Spot-check a few changed files — do the edits look correct?", "dim"))
    if skipped > 0 and not skip_reasons:
        print(c(f"  3. {skipped} items were skipped. Should the fixer handle more patterns?", "dim"))
    print(c(f"  3. Run `desloppify scan` to update state. Did score improve as expected?", "dim"))
    print(c(f"  4. Are there cascading effects? (e.g., removing vars may orphan imports)", "dim"))
    print(c(f"  5. `git diff --stat` — review before committing. Anything surprising?", "dim"))
