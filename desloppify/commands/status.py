"""status command: score dashboard with per-tier progress."""

import json
from collections import defaultdict

from ..utils import LOC_COMPACT_THRESHOLD, c, get_area, print_table
from ..cli import _state_path, _write_query


def cmd_status(args):
    """Show score dashboard."""
    from ..state import load_state

    sp = _state_path(args)
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
        print(c("No scans yet. Run: desloppify scan", "yellow"))
        return

    from ..utils import check_tool_staleness
    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(c(f"  {stale_warning}", "yellow"))

    score = state.get("score", 0)
    strict_score = state.get("strict_score", 0)
    obj_score = state.get("objective_score")
    obj_strict = state.get("objective_strict")
    dim_scores = state.get("dimension_scores", {})
    by_tier = stats.get("by_tier", {})

    # Header: prefer objective score when available
    if obj_score is not None:
        print(c(f"\n  Desloppify Health: {obj_score:.1f}/100", "bold") +
              c(f"  (strict: {obj_strict:.1f})", "dim"))
    else:
        print(c(f"\n  Desloppify Score: {score}/100", "bold") +
              c(f"  (strict: {strict_score}/100)", "dim"))

    # Codebase metrics
    metrics = state.get("codebase_metrics", {})
    total_files = sum(m.get("total_files", 0) for m in metrics.values())
    total_loc = sum(m.get("total_loc", 0) for m in metrics.values())
    total_dirs = sum(m.get("total_directories", 0) for m in metrics.values())
    if total_files:
        loc_str = f"{total_loc:,}" if total_loc < LOC_COMPACT_THRESHOLD else f"{total_loc // 1000}K"
        print(c(f"  {total_files} files · {loc_str} LOC · {total_dirs} dirs · "
                f"Last scan: {state.get('last_scan', 'never')}", "dim"))
    else:
        print(c(f"  Scans: {state.get('scan_count', 0)} | Last: {state.get('last_scan', 'never')}", "dim"))

    # Completeness indicator
    completeness = state.get("scan_completeness", {})
    incomplete = [lang for lang, s in completeness.items() if s != "full"]
    if incomplete:
        print(c(f"  * Incomplete scan ({', '.join(incomplete)} — slow phases skipped)", "yellow"))

    print(c("  " + "─" * 60, "dim"))

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
            bar = c("█" * filled, "green") + c("░" * (bar_len - filled), "dim")
            rows.append([f"Tier {tier_num}", bar, f"{strict_pct}%",
                         str(t_open), str(t_fixed), str(t_wontfix)])

        print_table(["Tier", "Strict Progress", "%", "Open", "Fixed", "Debt"], rows,
                    [40, 22, 5, 6, 6, 6])

    _show_structural_areas(state)

    # Focus suggestion (lowest-scoring dimension)
    if dim_scores:
        _show_focus_suggestion(dim_scores, state)

    ignores = state.get("config", {}).get("ignore", [])
    if ignores:
        print(c(f"\n  Ignore list ({len(ignores)}):", "dim"))
        for p in ignores[:10]:
            print(c(f"    {p}", "dim"))
    print()

    _write_query({"command": "status", "score": score, "strict_score": strict_score,
                  "objective_score": obj_score, "objective_strict": obj_strict,
                  "dimension_scores": dim_scores,
                  "stats": stats, "scan_count": state.get("scan_count", 0),
                  "last_scan": state.get("last_scan"),
                  "by_tier": by_tier, "ignores": ignores,
                  "potentials": state.get("potentials"),
                  "codebase_metrics": state.get("codebase_metrics")})


def _show_dimension_table(dim_scores: dict):
    """Show dimension health table with dual scores and progress bars."""
    from ..scoring import DIMENSIONS

    print()
    bar_len = 20
    # Header
    print(c(f"  {'Dimension':<22} {'Checks':>7}  {'Health':>6}  {'Strict':>6}  {'Bar':<{bar_len+2}} {'Tier'}", "dim"))
    print(c("  " + "─" * 76, "dim"))

    # Find lowest score for focus arrow
    lowest_name = None
    lowest_score = 101
    for dim in DIMENSIONS:
        ds = dim_scores.get(dim.name)
        if ds and ds["score"] < lowest_score:
            lowest_score = ds["score"]
            lowest_name = dim.name

    for dim in DIMENSIONS:
        ds = dim_scores.get(dim.name)
        if not ds:
            continue
        score_val = ds["score"]
        strict_val = ds.get("strict", score_val)
        checks = ds["checks"]

        filled = round(score_val / 100 * bar_len)
        if score_val >= 98:
            bar = c("█" * filled + "░" * (bar_len - filled), "green")
        elif score_val >= 93:
            bar = c("█" * filled, "green") + c("░" * (bar_len - filled), "dim")
        else:
            bar = c("█" * filled, "yellow") + c("░" * (bar_len - filled), "dim")

        focus = c(" ←", "yellow") if dim.name == lowest_name else "  "
        checks_str = f"{checks:>7,}"
        print(f"  {dim.name:<22} {checks_str}  {score_val:5.1f}%  {strict_val:5.1f}%  {bar}  T{dim.tier}{focus}")

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
        # Estimate impact
        from ..scoring import merge_potentials, compute_score_impact
        potentials = merge_potentials(state.get("potentials", {}))
        # Find the detector with most issues in this dimension
        from ..scoring import DIMENSIONS
        target_dim = next((d for d in DIMENSIONS if d.name == lowest_name), None)
        if target_dim:
            impact = 0.0
            for det in target_dim.detectors:
                # Use the score impact calculation
                impact = compute_score_impact(
                    {k: {"score": v["score"], "tier": v.get("tier", 3),
                          "detectors": v.get("detectors", {})}
                     for k, v in dim_scores.items()
                     if "score" in v},
                    potentials, det, lowest_issues)
                if impact > 0:
                    break

            impact_str = f" for +{impact:.1f} pts" if impact > 0 else ""
            print(c(f"  Focus: {lowest_name} ({lowest_score:.1f}%) — "
                    f"fix {lowest_issues} items{impact_str}", "cyan"))
            print()


def _show_structural_areas(state: dict):
    """Show structural debt grouped by area when T3/T4 debt is significant."""
    findings = state.get("findings", {})

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

    print(c("\n  ── Structural Debt by Area ──", "bold"))
    print(c("  Create a task doc for each area → farm to sub-agents for decomposition", "dim"))
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
        print(c(f"\n  ... and {remaining} more areas", "dim"))

    print(c("\n  Workflow:", "dim"))
    print(c("    1. desloppify show <area> --status wontfix --top 50", "dim"))
    print(c("    2. Create tasks/<date>-<area-name>.md with decomposition plan", "dim"))
    print(c("    3. Farm each task doc to a sub-agent for implementation", "dim"))
    print()
