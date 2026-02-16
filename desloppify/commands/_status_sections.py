"""Display sections for status output: dimensions, focus, and debt areas."""

from __future__ import annotations

from collections import defaultdict

from ..command_vocab import REVIEW_PREPARE
from ..registry import dimension_action_type
from ..scoring import DIMENSIONS, compute_score_impact, merge_potentials
from ..state import path_scoped_findings
from ..utils import colorize, get_area, print_table


def _score_bar(score: float, bar_len: int) -> str:
    filled = round(score / 100 * bar_len)
    if score >= 98:
        return colorize("█" * filled + "░" * (bar_len - filled), "green")
    if score >= 93:
        return colorize("█" * filled, "green") + colorize("░" * (bar_len - filled), "dim")
    return colorize("█" * filled, "yellow") + colorize("░" * (bar_len - filled), "dim")


def show_dimension_table(dim_scores: dict) -> None:
    """Show dimension health table with dual scores and progress bars."""

    print()
    bar_len = 20
    print(colorize(f"  {'Dimension':<22} {'Checks':>7}  {'Health':>6}  {'Strict':>6}  {'Bar':<{bar_len + 2}} {'Tier'}  {'Action'}", "dim"))
    print(colorize("  " + "─" * 86, "dim"))

    lowest_name = None
    lowest_score = 101
    for name, score_data in dim_scores.items():
        strict_val = score_data.get("strict", score_data["score"])
        if strict_val < lowest_score:
            lowest_score = strict_val
            lowest_name = name

    for dim in DIMENSIONS:
        score_data = dim_scores.get(dim.name)
        if not score_data:
            continue
        score = score_data["score"]
        strict = score_data.get("strict", score)
        focus = colorize(" ←", "yellow") if dim.name == lowest_name else "  "
        checks_str = f"{score_data['checks']:>7,}"
        action = dimension_action_type(dim.name)
        print(f"  {dim.name:<22} {checks_str}  {score:5.1f}%  {strict:5.1f}%  {_score_bar(score, bar_len)}  T{dim.tier}  {action}{focus}")

    static_names = {dim.name for dim in DIMENSIONS}
    subjective = [(name, data) for name, data in sorted(dim_scores.items()) if name not in static_names]
    if subjective:
        print(colorize("  ── Subjective Dimensions ─────────────────────────────────────────────", "dim"))
        for name, score_data in subjective:
            score = score_data["score"]
            strict = score_data.get("strict", score)
            tier = score_data.get("tier", 4)
            focus = colorize(" ←", "yellow") if name == lowest_name else "  "
            print(f"  {name:<22} {'—':>7}  {score:5.1f}%  {strict:5.1f}%  {_score_bar(score, bar_len)}  T{tier}  review{focus}")

    print(colorize("  Health = open penalized | Strict = open + wontfix penalized", "dim"))
    print(colorize("  Action: fix=auto-fixer | move=reorganize | refactor=manual rewrite | manual=review & fix", "dim"))
    print()


def show_focus_suggestion(dim_scores: dict, state: dict) -> None:
    """Show the lowest-scoring dimension as the focus area."""
    lowest_name = None
    lowest_score = 101
    lowest_issues = 0
    for name, score_data in dim_scores.items():
        strict = score_data.get("strict", score_data["score"])
        if strict < lowest_score:
            lowest_name = name
            lowest_score = strict
            lowest_issues = score_data["issues"]

    if not lowest_name or lowest_score >= 100:
        return

    score_data = dim_scores[lowest_name]
    is_subjective = "subjective_assessment" in score_data.get("detectors", {})
    if is_subjective:
        has_prior_review = bool((state.get("review_cache", {}) or {}).get("files")) or bool(
            state.get("subjective_assessments") or state.get("review_assessments")
        )
        suffix = f", {lowest_issues} review finding{'s' if lowest_issues != 1 else ''}" if lowest_issues else ""
        action_text = "re-review to improve" if has_prior_review else "run subjective review to improve"
        print(colorize(f"  Focus: {lowest_name} ({lowest_score:.1f}%) — {action_text}{suffix} — `{REVIEW_PREPARE}`", "cyan"))
        print()
        return

    target_dim = next((dim for dim in DIMENSIONS if dim.name == lowest_name), None)
    if target_dim is None:
        return

    simulated_dims = {
        name: {"score": data["score"], "tier": data.get("tier", 3), "detectors": data.get("detectors", {})}
        for name, data in dim_scores.items()
        if "score" in data
    }
    potentials = merge_potentials(state.get("potentials", {}))
    impact = 0.0
    for detector in target_dim.detectors:
        impact = compute_score_impact(simulated_dims, potentials, detector, lowest_issues)
        if impact > 0:
            break

    impact_str = f" for +{impact:.1f} pts" if impact > 0 else ""
    print(colorize(f"  Focus: {lowest_name} ({lowest_score:.1f}%) — fix {lowest_issues} items{impact_str}", "cyan"))
    print()


def show_structural_areas(state: dict) -> None:
    """Show structural debt grouped by area when T3/T4 debt is significant."""
    findings = path_scoped_findings(state.get("findings", {}), state.get("scan_path"))
    structural = [
        finding
        for finding in findings.values()
        if finding["tier"] in (3, 4) and finding["status"] in ("open", "wontfix")
    ]
    if len(structural) < 5:
        return

    areas: dict[str, list] = defaultdict(list)
    for finding in structural:
        areas[get_area(finding["file"])].append(finding)
    if len(areas) < 2:
        return

    sorted_areas = sorted(areas.items(), key=lambda item: -sum(f["tier"] for f in item[1]))
    print(colorize("\n  ── Structural Debt by Area ──", "bold"))
    print(colorize("  Create a task doc for each area → farm to sub-agents for decomposition", "dim"))
    print()

    rows = []
    for area, area_findings in sorted_areas[:15]:
        t3 = sum(1 for finding in area_findings if finding["tier"] == 3)
        t4 = sum(1 for finding in area_findings if finding["tier"] == 4)
        rows.append(
            [
                area,
                str(len(area_findings)),
                f"T3:{t3} T4:{t4}",
                str(sum(1 for finding in area_findings if finding["status"] == "open")),
                str(sum(1 for finding in area_findings if finding["status"] == "wontfix")),
                str(sum(finding["tier"] for finding in area_findings)),
            ]
        )
    print_table(["Area", "Items", "Tiers", "Open", "Debt", "Weight"], rows, [42, 6, 10, 5, 5, 7])

    remaining = len(sorted_areas) - 15
    if remaining > 0:
        print(colorize(f"\n  ... and {remaining} more areas", "dim"))

    print(colorize("\n  Workflow:", "dim"))
    print(colorize("    1. desloppify show <area> --status wontfix --top 50", "dim"))
    print(colorize("    2. Create tasks/<date>-<area-name>.md with decomposition plan", "dim"))
    print(colorize("    3. Farm each task doc to a sub-agent for implementation", "dim"))
    print()


def show_review_summary(state: dict) -> None:
    """Show review findings summary if any exist."""
    review_open = [
        finding
        for finding in state.get("findings", {}).values()
        if finding.get("status") == "open" and finding.get("detector") == "review"
    ]
    if not review_open:
        return

    uninvestigated = sum(1 for finding in review_open if not finding.get("detail", {}).get("investigation"))
    parts = [f"{len(review_open)} finding{'s' if len(review_open) != 1 else ''} open"]
    if uninvestigated:
        parts.append(f"{uninvestigated} uninvestigated")
    print(colorize(f"  Review: {', '.join(parts)} — `desloppify issues`", "cyan"))

    if "Test health" in state.get("dimension_scores", {}):
        print(colorize("  Test health tracks coverage + review; review findings track issues found.", "dim"))
    print()
