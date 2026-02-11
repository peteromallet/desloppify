"""scan command: run all detectors, update persistent state, show diff."""

from pathlib import Path

from ..utils import c
from ..cli import _state_path, _write_query


def cmd_scan(args):
    """Run all detectors, update persistent state, show diff."""
    from ..state import load_state, save_state, merge_scan
    from ..plan import generate_findings

    sp = _state_path(args)
    state = load_state(sp)
    path = Path(args.path)
    include_slow = not getattr(args, "skip_slow", False)

    # Persist --exclude in state so subsequent commands reuse it
    exclude = getattr(args, "exclude", None)
    if exclude:
        state.setdefault("config", {})["exclude"] = list(exclude)

    # Resolve language config
    from ..cli import _resolve_lang
    lang = _resolve_lang(args)
    lang_label = f" ({lang.name})" if lang else ""

    print(c(f"\nDesloppify Scan{lang_label}\n", "bold"))
    findings, potentials = generate_findings(path, include_slow=include_slow, lang=lang)

    # Collect codebase metrics for this language
    codebase_metrics = None
    if lang and lang.file_finder:
        files = lang.file_finder(path)
        total_loc = 0
        dirs = set()
        for f in files:
            try:
                total_loc += len(Path(f).read_text().splitlines())
                dirs.add(str(Path(f).parent))
            except (OSError, UnicodeDecodeError):
                pass
        codebase_metrics = {
            "total_files": len(files),
            "total_loc": total_loc,
            "total_directories": len(dirs),
        }

    # Only store potentials for full scans (not path-scoped)
    from ..utils import rel, _extra_exclusions, PROJECT_ROOT
    scan_path_rel = rel(str(path))
    is_full_scan = (path.resolve() == PROJECT_ROOT.resolve() or
                    scan_path_rel == lang.default_src if lang else False)

    prev_score = state.get("score", 0)
    prev_strict = state.get("strict_score", 0)
    prev_obj = state.get("objective_score")
    prev_obj_strict = state.get("objective_strict")
    prev_dim_scores = state.get("dimension_scores", {})
    diff = merge_scan(state, findings,
                      lang=lang.name if lang else None,
                      scan_path=scan_path_rel,
                      force_resolve=getattr(args, "force_resolve", False),
                      exclude=_extra_exclusions,
                      potentials=potentials if is_full_scan else None,
                      codebase_metrics=codebase_metrics if is_full_scan else None)
    save_state(state, sp)

    new_score = state["score"]
    new_strict = state.get("strict_score", 0)
    stats = state["stats"]
    print(c("\n  Scan complete", "bold"))
    print(c("  " + "─" * 50, "dim"))

    # Diff summary
    diff_parts = []
    if diff["new"]:
        diff_parts.append(c(f"+{diff['new']} new", "yellow"))
    if diff["auto_resolved"]:
        diff_parts.append(c(f"-{diff['auto_resolved']} resolved", "green"))
    if diff["reopened"]:
        diff_parts.append(c(f"↻{diff['reopened']} reopened", "red"))
    if diff_parts:
        print(f"  {' · '.join(diff_parts)}")
    else:
        print(c("  No changes since last scan", "dim"))
    if diff.get("suspect_detectors"):
        print(c(f"  ⚠ Skipped auto-resolve for: {', '.join(diff['suspect_detectors'])} (returned 0 — likely transient)", "yellow"))

    # Score — prefer objective score when available
    new_obj = state.get("objective_score")
    new_obj_strict = state.get("objective_strict")
    if new_obj is not None:
        obj_delta = new_obj - prev_obj if prev_obj is not None else 0
        obj_delta_str = f" ({'+' if obj_delta > 0 else ''}{obj_delta:.1f})" if obj_delta != 0 else ""
        obj_color = "green" if obj_delta > 0 else ("red" if obj_delta < 0 else "dim")
        strict_obj_delta = new_obj_strict - prev_obj_strict if prev_obj_strict is not None else 0
        strict_obj_delta_str = f" ({'+' if strict_obj_delta > 0 else ''}{strict_obj_delta:.1f})" if strict_obj_delta != 0 else ""
        strict_obj_color = "green" if strict_obj_delta > 0 else ("red" if strict_obj_delta < 0 else "dim")
        print(f"  Health: {c(f'{new_obj:.1f}/100{obj_delta_str}', obj_color)}" +
              c(f"  strict: {new_obj_strict:.1f}/100{strict_obj_delta_str}", strict_obj_color) +
              c(f"  |  {stats['open']} open / {stats['total']} total", "dim"))
    else:
        delta = new_score - prev_score
        delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if delta != 0 else ""
        color = "green" if delta > 0 else ("red" if delta < 0 else "dim")
        strict_delta = new_strict - prev_strict
        strict_delta_str = f" ({'+' if strict_delta > 0 else ''}{strict_delta:.1f})" if strict_delta != 0 else ""
        strict_color = "green" if strict_delta > 0 else ("red" if strict_delta < 0 else "dim")
        print(f"  Score: {c(f'{new_score:.1f}/100{delta_str}', color)}" +
              c(f"  (strict: {new_strict:.1f}/100{strict_delta_str})", strict_color) +
              c(f"  |  {stats['open']} open / {stats['total']} total", "dim"))

    # Per-detector progress
    _show_detector_progress(state)

    # Dimension deltas (show which dimensions moved)
    new_dim_scores = state.get("dimension_scores", {})
    if new_dim_scores and prev_dim_scores:
        _show_dimension_deltas(prev_dim_scores, new_dim_scores)

    # Post-scan analysis
    warnings = []
    next_action = None

    if diff["reopened"] > 5:
        warnings.append(f"{diff['reopened']} findings reopened — was a previous fix reverted? Check: git log --oneline -5")
    if diff["new"] > 10 and diff["auto_resolved"] < 3:
        warnings.append(f"{diff['new']} new findings with few resolutions — likely cascading from recent fixes. Run fixers again.")
    if diff.get("chronic_reopeners", 0) > 0:
        n = diff["chronic_reopeners"]
        warnings.append(f"⟳ {n} chronic reopener{'s' if n != 1 else ''} (reopened 2+ times). "
                        f"These keep bouncing — fix properly or wontfix. "
                        f"Run: `desloppify show --chronic` to see them.")

    by_tier = stats.get("by_tier", {})
    next_action = _suggest_next_action(by_tier)

    if warnings:
        for w in warnings:
            print(c(f"  {w}", "yellow"))
        print()

    if next_action:
        print(c(f"  Suggested next: {next_action}", "cyan"))
        print()

    # Reflection prompts
    print(c("  ── Reflect ──", "dim"))
    print(c("  1. Any new findings from cascading? (exports removed → vars now unused?)", "dim"))
    print(c("  2. Did score move as expected? If not, check reopened/new counts above.", "dim"))
    print(c("  3. Are there quick wins? Check `desloppify status` for tier breakdown.", "dim"))
    print()

    _write_query({"command": "scan", "score": new_score, "strict_score": new_strict,
                  "prev_score": prev_score, "diff": diff, "stats": stats,
                  "warnings": warnings, "next_action": next_action,
                  "objective_score": state.get("objective_score"),
                  "objective_strict": state.get("objective_strict"),
                  "dimension_scores": state.get("dimension_scores"),
                  "potentials": state.get("potentials")})


def _show_detector_progress(state: dict):
    """Show per-detector progress bars — the heartbeat of a scan."""
    findings = state["findings"]
    if not findings:
        return

    STRUCTURAL_MERGE = {"large", "complexity", "gods", "concerns"}
    by_det: dict[str, dict] = {}
    for f in findings.values():
        det = f.get("detector", "unknown")
        if det in STRUCTURAL_MERGE:
            det = "structural"
        if det not in by_det:
            by_det[det] = {"open": 0, "total": 0}
        by_det[det]["total"] += 1
        if f["status"] == "open":
            by_det[det]["open"] += 1

    DET_ORDER = ["logs", "unused", "exports", "deprecated", "structural", "props",
                 "single_use", "coupling", "cycles", "orphaned", "patterns", "naming",
                 "smells", "react", "dupes"]
    order_map = {d: i for i, d in enumerate(DET_ORDER)}
    sorted_dets = sorted(by_det.items(), key=lambda x: order_map.get(x[0], 99))

    print(c("  " + "─" * 50, "dim"))
    bar_len = 15
    for det, ds in sorted_dets:
        total = ds["total"]
        open_count = ds["open"]
        addressed = total - open_count
        pct = round(addressed / total * 100) if total else 100

        filled = round(pct / 100 * bar_len)
        if pct == 100:
            bar = c("█" * bar_len, "green")
        elif open_count <= 2:
            bar = c("█" * filled, "green") + c("░" * (bar_len - filled), "dim")
        else:
            bar = c("█" * filled, "yellow") + c("░" * (bar_len - filled), "dim")

        det_label = det.replace("_", " ").ljust(12)
        if open_count > 0:
            open_str = c(f"{open_count:3d} open", "yellow")
        else:
            open_str = c("  ✓", "green")

        print(f"  {det_label} {bar} {pct:3d}%  {open_str}  {c(f'/ {total}', 'dim')}")

    print()


def _show_dimension_deltas(prev: dict, current: dict):
    """Show which dimensions changed between scans."""
    from ..scoring import DIMENSIONS
    moved = []
    for dim in DIMENSIONS:
        p = prev.get(dim.name, {})
        n = current.get(dim.name, {})
        if not p or not n:
            continue
        old_score = p.get("score", 100)
        new_score = n.get("score", 100)
        delta = new_score - old_score
        if abs(delta) >= 0.1:
            moved.append((dim.name, old_score, new_score, delta))

    if not moved:
        return

    print(c("  Moved:", "dim"))
    for name, old, new, delta in sorted(moved, key=lambda x: x[3]):
        sign = "+" if delta > 0 else ""
        color = "green" if delta > 0 else "red"
        print(c(f"    {name:<22} {old:.1f}% → {new:.1f}%  ({sign}{delta:.1f}%)", color))
    print()


def _suggest_next_action(by_tier: dict) -> str | None:
    """Suggest the highest-value next command based on tier breakdown."""
    t1 = by_tier.get("1", {})
    t2 = by_tier.get("2", {})
    t1_open = t1.get("open", 0)
    t2_open = t2.get("open", 0)

    if t1_open > 0:
        return f"`desloppify fix debug-logs --dry-run` or `fix unused-imports --dry-run` ({t1_open} T1 items)"
    if t2_open > 0:
        return (f"`desloppify fix unused-vars --dry-run` or `fix unused-params --dry-run` "
                f"or `fix dead-useeffect --dry-run` ({t2_open} T2 items)")

    t3_open = by_tier.get("3", {}).get("open", 0)
    t4_open = by_tier.get("4", {}).get("open", 0)
    structural_open = t3_open + t4_open
    if structural_open > 0:
        return (f"{structural_open} structural items open (T3: {t3_open}, T4: {t4_open}). "
                f"Run `desloppify show structural --status open` to review by area, "
                f"then create per-area task docs in tasks/ for sub-agent decomposition.")

    t3_debt = by_tier.get("3", {}).get("wontfix", 0)
    t4_debt = by_tier.get("4", {}).get("wontfix", 0)
    structural_debt = t3_debt + t4_debt
    if structural_debt > 0:
        return (f"{structural_debt} structural items remain as debt (T3: {t3_debt}, T4: {t4_debt}). "
                f"Run `desloppify status` for area breakdown. "
                f"Create per-area task docs and farm to sub-agents for decomposition.")

    return None
