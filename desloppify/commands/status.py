"""status command: score dashboard with per-tier progress."""

import json
from collections import defaultdict

from ..utils import LOC_COMPACT_THRESHOLD, colorize, get_area, print_table
from ._helpers import state_path, _write_query


def cmd_status(args):
    """Show score dashboard."""
    from ..state import load_state

    sp = state_path(args)
    state = load_state(sp)
    stats = state.get("stats", {})

    if getattr(args, "json", False):
        print(json.dumps({"score": state.get("score", 0),
                          "strict_score": state.get("strict_score", 0),
                          "objective_score": state.get("objective_score"),
                          "objective_strict": state.get("objective_strict"),
                          "dimension_scores": state.get("dimension_scores"),
                          "potentials": state.get("potentials"),
                          "codebase_metrics": state.get("codebase_metrics"),
                          "stats": stats,
                          "scan_count": state.get("scan_count", 0),
                          "last_scan": state.get("last_scan")}, indent=2))
        return

    if not state.get("last_scan"):
        print(colorize("No scans yet. Run: desloppify scan", "yellow"))
        return

    from ..utils import check_tool_staleness
    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))

    score = state.get("score", 0)
    strict_score = state.get("strict_score", 0)
    obj_score = state.get("objective_score")
    obj_strict = state.get("objective_strict")
    dim_scores = state.get("dimension_scores", {})
    by_tier = stats.get("by_tier", {})

    # Header: prefer objective score when available
    if obj_score is not None:
        print(colorize(f"\n  Desloppify Health: {obj_score:.1f}/100", "bold") +
              colorize(f"  (strict: {obj_strict:.1f})", "dim"))
    else:
        print(colorize(f"\n  Desloppify Score: {score}/100", "bold") +
              colorize(f"  (strict: {strict_score}/100)", "dim"))
        print(colorize("  ⚠ Dimension-based scoring unavailable (potentials missing). "
                "Run a full scan to fix: desloppify scan --path <source-root>", "yellow"))

    # Codebase metrics
    metrics = state.get("codebase_metrics", {})
    total_files = sum(m.get("total_files", 0) for m in metrics.values())
    total_loc = sum(m.get("total_loc", 0) for m in metrics.values())
    total_dirs = sum(m.get("total_directories", 0) for m in metrics.values())
    if total_files:
        loc_str = f"{total_loc:,}" if total_loc < LOC_COMPACT_THRESHOLD else f"{total_loc // 1000}K"
        print(colorize(f"  {total_files} files · {loc_str} LOC · {total_dirs} dirs · "
                f"Last scan: {state.get('last_scan', 'never')}", "dim"))
    else:
        print(colorize(f"  Scans: {state.get('scan_count', 0)} | Last: {state.get('last_scan', 'never')}", "dim"))

    # Completeness indicator
    completeness = state.get("scan_completeness", {})
    incomplete = [lang for lang, s in completeness.items() if s != "full"]
    if incomplete:
        print(colorize(f"  * Incomplete scan ({', '.join(incomplete)} — slow phases skipped)", "yellow"))

    print(colorize("  " + "─" * 60, "dim"))

    # Dimension table (when available)
    if dim_scores:
        _show_dimension_table(dim_scores)
    else:
        # Fall back to tier-based display
        rows = []
        for tier_num in [1, 2, 3, 4]:
            ts = by_tier.get(str(tier_num), {})
            t_open = ts.get("open", 0)
            t_fixed = ts.get("fixed", 0) + ts.get("auto_resolved", 0)
            t_fp = ts.get("false_positive", 0)
            t_wontfix = ts.get("wontfix", 0)
            t_total = sum(ts.values())
            strict_pct = round((t_fixed + t_fp) / t_total * 100) if t_total else 100
            bar_len = 20
            filled = round(strict_pct / 100 * bar_len)
            bar = colorize("█" * filled, "green") + colorize("░" * (bar_len - filled), "dim")
            rows.append([f"Tier {tier_num}", bar, f"{strict_pct}%",
                         str(t_open), str(t_fixed), str(t_wontfix)])

        print_table(["Tier", "Strict Progress", "%", "Open", "Fixed", "Debt"], rows,
                    [40, 22, 5, 6, 6, 6])

    _show_structural_areas(state)
    _show_review_summary(state)

    # Focus suggestion (lowest-scoring dimension)
    if dim_scores:
        _show_focus_suggestion(dim_scores, state)

    # Computed narrative headline
    from ..narrative import compute_narrative
    from ._helpers import resolve_lang
    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(state, lang=lang_name, command="status")
    if narrative.get("headline"):
        print(colorize(f"  → {narrative['headline']}", "cyan"))
        print()

    ignores = args._config.get("ignore", [])
    if ignores:
        print(colorize(f"\n  Ignore list ({len(ignores)}):", "dim"))
        for p in ignores[:10]:
            print(colorize(f"    {p}", "dim"))

    review_age = args._config.get("review_max_age_days", 30)
    if review_age != 30:
        label = "never" if review_age == 0 else f"{review_age} days"
        print(colorize(f"  Review staleness: {label}", "dim"))
    print()

    _write_query({"command": "status", "score": score, "strict_score": strict_score,
                  "objective_score": obj_score, "objective_strict": obj_strict,
                  "dimension_scores": dim_scores,
                  "stats": stats, "scan_count": state.get("scan_count", 0),
                  "last_scan": state.get("last_scan"),
                  "by_tier": by_tier, "ignores": ignores,
                  "potentials": state.get("potentials"),
                  "codebase_metrics": state.get("codebase_metrics"),
                  "narrative": narrative})


def _show_dimension_table(dim_scores: dict):
    """Show dimension health table with dual scores and progress bars."""
    from ..scoring import DIMENSIONS
    from ..registry import dimension_action_type

    print()
    bar_len = 20
    # Header
    print(colorize(f"  {'Dimension':<22} {'Checks':>7}  {'Health':>6}  {'Strict':>6}  {'Bar':<{bar_len+2}} {'Tier'}  {'Action'}", "dim"))
    print(colorize("  " + "─" * 86, "dim"))

    # Find lowest score for focus arrow (includes subjective dimensions)
    lowest_name = None
    lowest_score = 101
    for name, ds in dim_scores.items():
        if ds["score"] < lowest_score:
            lowest_score = ds["score"]
            lowest_name = name

    for dim in DIMENSIONS:
        ds = dim_scores.get(dim.name)
        if not ds:
            continue
        score_val = ds["score"]
        strict_val = ds.get("strict", score_val)
        checks = ds["checks"]

        filled = round(score_val / 100 * bar_len)
        if score_val >= 98:
            bar = colorize("█" * filled + "░" * (bar_len - filled), "green")
        elif score_val >= 93:
            bar = colorize("█" * filled, "green") + colorize("░" * (bar_len - filled), "dim")
        else:
            bar = colorize("█" * filled, "yellow") + colorize("░" * (bar_len - filled), "dim")

        focus = colorize(" ←", "yellow") if dim.name == lowest_name else "  "
        checks_str = f"{checks:>7,}"
        action = dimension_action_type(dim.name)
        print(f"  {dim.name:<22} {checks_str}  {score_val:5.1f}%  {strict_val:5.1f}%  {bar}  T{dim.tier}  {action}{focus}")


    # Subjective dimensions (not in DIMENSIONS list)
    static_names = {d.name for d in DIMENSIONS}
    assessment_dims = [(name, ds) for name, ds in sorted(dim_scores.items())
                       if name not in static_names]
    if assessment_dims:
        print(colorize("  ── Subjective Dimensions ─────────────────────────────────────────────", "dim"))
        for name, ds in assessment_dims:
            score_val = ds["score"]
            strict_val = ds.get("strict", score_val)
            tier = ds.get("tier", 4)

            filled = round(score_val / 100 * bar_len)
            if score_val >= 98:
                bar = colorize("█" * filled + "░" * (bar_len - filled), "green")
            elif score_val >= 93:
                bar = colorize("█" * filled, "green") + colorize("░" * (bar_len - filled), "dim")
            else:
                bar = colorize("█" * filled, "yellow") + colorize("░" * (bar_len - filled), "dim")

            focus = colorize(" ←", "yellow") if name == lowest_name else "  "
            checks_str = f"{'—':>7}"
            print(f"  {name:<22} {checks_str}  {score_val:5.1f}%  {strict_val:5.1f}%  {bar}  T{tier}  {'review'}{focus}")
    print(colorize("  Health = open penalized | Strict = open + wontfix penalized", "dim"))
    print(colorize("  Action: fix=auto-fixer | move=reorganize | refactor=manual rewrite | manual=review & fix", "dim"))
    print()


def _show_focus_suggestion(dim_scores: dict, state: dict):
    """Show the lowest-scoring dimension as the focus area."""
    lowest_name = None
    lowest_score = 101
    lowest_issues = 0
    for name, ds in dim_scores.items():
        if ds["score"] < lowest_score:
            lowest_score = ds["score"]
            lowest_name = name
            lowest_issues = ds["issues"]

    if lowest_name and lowest_score < 100:
        ds = dim_scores[lowest_name]
        # Subjective dimensions have "subjective_assessment" as their only detector
        is_subjective = "subjective_assessment" in ds.get("detectors", {})
        if is_subjective:
            suffix = ""
            if lowest_issues:
                suffix = f", {lowest_issues} review finding{'s' if lowest_issues != 1 else ''}"
            print(colorize(f"  Focus: {lowest_name} ({lowest_score:.1f}%) — "
                    f"re-review to improve{suffix}", "cyan"))
            print()
            return

        # Mechanical dimension — estimate impact
        from ..scoring import merge_potentials, compute_score_impact
        potentials = merge_potentials(state.get("potentials", {}))
        from ..scoring import DIMENSIONS
        target_dim = next((d for d in DIMENSIONS if d.name == lowest_name), None)
        if target_dim:
            impact = 0.0
            for det in target_dim.detectors:
                impact = compute_score_impact(
                    {k: {"score": v["score"], "tier": v.get("tier", 3),
                          "detectors": v.get("detectors", {})}
                     for k, v in dim_scores.items()
                     if "score" in v},
                    potentials, det, lowest_issues)
                if impact > 0:
                    break

            impact_str = f" for +{impact:.1f} pts" if impact > 0 else ""
            print(colorize(f"  Focus: {lowest_name} ({lowest_score:.1f}%) — "
                    f"fix {lowest_issues} items{impact_str}", "cyan"))
            print()


def _show_structural_areas(state: dict):
    """Show structural debt grouped by area when T3/T4 debt is significant."""
    from ..state import path_scoped_findings
    findings = path_scoped_findings(state.get("findings", {}), state.get("scan_path"))

    structural = [f for f in findings.values()
                  if f["tier"] in (3, 4) and f["status"] in ("open", "wontfix")]

    if len(structural) < 5:
        return

    areas: dict[str, list] = defaultdict(list)
    for f in structural:
        areas[get_area(f["file"])].append(f)

    if len(areas) < 2:
        return

    sorted_areas = sorted(areas.items(),
                          key=lambda x: -sum(f["tier"] for f in x[1]))

    print(colorize("\n  ── Structural Debt by Area ──", "bold"))
    print(colorize("  Create a task doc for each area → farm to sub-agents for decomposition", "dim"))
    print()

    rows = []
    for area, area_findings in sorted_areas[:15]:
        t3 = sum(1 for f in area_findings if f["tier"] == 3)
        t4 = sum(1 for f in area_findings if f["tier"] == 4)
        open_count = sum(1 for f in area_findings if f["status"] == "open")
        debt_count = sum(1 for f in area_findings if f["status"] == "wontfix")
        weight = sum(f["tier"] for f in area_findings)
        rows.append([area, str(len(area_findings)), f"T3:{t3} T4:{t4}",
                      str(open_count), str(debt_count), str(weight)])

    print_table(["Area", "Items", "Tiers", "Open", "Debt", "Weight"], rows,
                [42, 6, 10, 5, 5, 7])

    remaining = len(sorted_areas) - 15
    if remaining > 0:
        print(colorize(f"\n  ... and {remaining} more areas", "dim"))

    print(colorize("\n  Workflow:", "dim"))
    print(colorize("    1. desloppify show <area> --status wontfix --top 50", "dim"))
    print(colorize("    2. Create tasks/<date>-<area-name>.md with decomposition plan", "dim"))
    print(colorize("    3. Farm each task doc to a sub-agent for implementation", "dim"))
    print()


def _show_review_summary(state: dict):
    """Show review findings summary if any exist."""
    findings = state.get("findings", {})
    review_open = [f for f in findings.values()
                   if f.get("status") == "open" and f.get("detector") == "review"]
    if not review_open:
        return
    uninvestigated = sum(1 for f in review_open
                         if not f.get("detail", {}).get("investigation"))
    parts = [f"{len(review_open)} finding{'s' if len(review_open) != 1 else ''} open"]
    if uninvestigated:
        parts.append(f"{uninvestigated} uninvestigated")
    print(colorize(f"  Review: {', '.join(parts)} — `desloppify issues`", "cyan"))
    # Explain relationship between audit coverage dimension and review findings
    dim_scores = state.get("dimension_scores", {})
    if "Test health" in dim_scores:
        print(colorize("  Test health tracks coverage + review; review findings track issues found.", "dim"))
    print()
