"""status command: score dashboard with per-tier progress."""

import json
from collections import defaultdict

from ..utils import c, get_area, print_table
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
    by_tier = stats.get("by_tier", {})

    print(c(f"\n  Desloppify Score: {score}/100", "bold") + c(f"  (strict: {strict_score}/100)", "dim"))
    print(c(f"  Scans: {state.get('scan_count', 0)} | Last: {state.get('last_scan', 'never')}", "dim"))
    print(c("  " + "─" * 60, "dim"))

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

    ignores = state.get("config", {}).get("ignore", [])
    if ignores:
        print(c(f"\n  Ignore list ({len(ignores)}):", "dim"))
        for p in ignores[:10]:
            print(c(f"    {p}", "dim"))
    print()

    _write_query({"command": "status", "score": score, "strict_score": strict_score,
                  "stats": stats, "scan_count": state.get("scan_count", 0),
                  "last_scan": state.get("last_scan"),
                  "by_tier": by_tier, "ignores": ignores})


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
