"""Markdown plan rendering."""

from __future__ import annotations

import importlib
from collections import defaultdict
from datetime import date

from desloppify.engine.planning.common import TIER_LABELS
from desloppify.engine.planning.types import PlanState


def _plan_header(state: PlanState, stats: dict) -> list[str]:
    """Build the plan header: title, score line, and codebase metrics."""
    schema_mod = importlib.import_module("desloppify.engine.state_internal.schema")

    overall_score = schema_mod.get_overall_score(state)
    objective_score = schema_mod.get_objective_score(state)
    strict_score = schema_mod.get_strict_score(state)

    if (
        overall_score is not None
        and objective_score is not None
        and strict_score is not None
    ):
        header_score = (
            f"**Health:** overall {overall_score:.1f}/100 | "
            f"objective {objective_score:.1f}/100 | "
            f"strict {strict_score:.1f}/100"
        )
    elif overall_score is not None:
        header_score = f"**Score: {overall_score:.1f}/100**"
    else:
        header_score = "**Scores unavailable**"

    metrics = state.get("codebase_metrics", {})
    total_files = sum(metric.get("total_files", 0) for metric in metrics.values())
    total_loc = sum(metric.get("total_loc", 0) for metric in metrics.values())
    total_dirs = sum(metric.get("total_directories", 0) for metric in metrics.values())

    lines = [
        f"# Desloppify Plan — {date.today().isoformat()}",
        "",
        f"{header_score} | "
        f"{stats.get('open', 0)} open | "
        f"{stats.get('fixed', 0)} fixed | "
        f"{stats.get('wontfix', 0)} wontfix | "
        f"{stats.get('auto_resolved', 0)} auto-resolved",
        "",
    ]

    if total_files:
        utils_mod = importlib.import_module("desloppify.utils")

        loc_str = (
            f"{total_loc:,}"
            if total_loc < utils_mod.LOC_COMPACT_THRESHOLD
            else f"{total_loc // 1000}K"
        )
        lines.append(
            f"\n{total_files} files · {loc_str} LOC · {total_dirs} directories\n"
        )

    return lines


def _plan_dimension_table(state: PlanState) -> list[str]:
    """Build the dimension health table rows (empty list when no data)."""
    dim_scores = state.get("dimension_scores", {})
    if not dim_scores:
        return []

    lines = [
        "## Health by Dimension",
        "",
        "| Dimension | Tier | Checks | Issues | Health | Strict | Action |",
        "|-----------|------|--------|--------|--------|--------|--------|",
    ]
    registry_mod = importlib.import_module("desloppify.core.registry")
    scoring_mod = importlib.import_module("desloppify.scoring")

    static_names: set[str] = set()
    rendered_names: set[str] = set()
    subjective_display_names = {
        display.lower() for display in scoring_mod.DISPLAY_NAMES.values()
    }

    def _looks_subjective(name: str, data: dict) -> bool:
        detectors = data.get("detectors", {})
        if "subjective_assessment" in detectors:
            return True
        lowered = name.strip().lower()
        return lowered in subjective_display_names or lowered.startswith("elegance")

    for dim in scoring_mod.DIMENSIONS:
        ds = dim_scores.get(dim.name)
        if not ds:
            continue
        static_names.add(dim.name)
        rendered_names.add(dim.name)
        checks = ds.get("checks", 0)
        issues = ds.get("issues", 0)
        score_val = ds.get("score", 100)
        strict_val = ds.get("strict", score_val)
        bold = "**" if score_val < 93 else ""
        action = registry_mod.dimension_action_type(dim.name)
        lines.append(
            f"| {bold}{dim.name}{bold} | T{dim.tier} | "
            f"{checks:,} | {issues} | {score_val:.1f}% | {strict_val:.1f}% | {action} |"
        )

    scorecard_projection_mod = importlib.import_module(
        "desloppify.app.output.scorecard_parts.projection"
    )
    scorecard_rows = scorecard_projection_mod.scorecard_dimension_rows(state)
    scorecard_subjective_rows = [
        (name, ds) for name, ds in scorecard_rows if _looks_subjective(name, ds)
    ]
    scorecard_subjective_names = {name for name, _ in scorecard_subjective_rows}

    # Show custom dimensions not present in scorecard.png in the main table.
    custom_non_subjective_rows: list[tuple[str, dict]] = []
    for name, ds in sorted(dim_scores.items(), key=lambda item: str(item[0]).lower()):
        if name in rendered_names or not isinstance(ds, dict):
            continue
        if _looks_subjective(name, ds):
            continue
        custom_non_subjective_rows.append((name, ds))
        rendered_names.add(name)

    for name, ds in custom_non_subjective_rows:
        checks = ds.get("checks", 0)
        issues = ds.get("issues", 0)
        score_val = ds.get("score", 100)
        strict_val = ds.get("strict", score_val)
        tier = int(ds.get("tier", 3) or 3)
        bold = "**" if score_val < 93 else ""
        action = registry_mod.dimension_action_type(name)
        lines.append(
            f"| {bold}{name}{bold} | T{tier} | "
            f"{checks:,} | {issues} | {score_val:.1f}% | {strict_val:.1f}% | {action} |"
        )

    extra_subjective_rows = [
        (name, ds)
        for name, ds in sorted(
            dim_scores.items(), key=lambda item: str(item[0]).lower()
        )
        if (
            isinstance(ds, dict)
            and name not in scorecard_subjective_names
            and name.strip().lower() not in subjective_display_names
            and name.strip().lower() not in {"elegance", "elegance (combined)"}
            and _looks_subjective(name, ds)
        )
    ]
    subjective_rows = [*scorecard_subjective_rows, *extra_subjective_rows]

    if subjective_rows:
        lines.append("| **Subjective Measures (matches scorecard.png)** | | | | | | |")
        for name, ds in subjective_rows:
            issues = ds.get("issues", 0)
            score_val = ds.get("score", 100)
            strict_val = ds.get("strict", score_val)
            tier = ds.get("tier", 4)
            bold = "**" if score_val < 93 else ""
            lines.append(
                f"| {bold}{name}{bold} | T{tier} | "
                f"— | {issues} | {score_val:.1f}% | {strict_val:.1f}% | review |"
            )

    lines.append("")
    return lines


def _plan_tier_sections(findings: dict, *, state: PlanState | None = None) -> list[str]:
    """Build per-tier sections from the shared work-queue backend."""
    work_queue_mod = importlib.import_module("desloppify.engine.work_queue_internal.core")

    queue_state: PlanState | dict = state or {"findings": findings}
    scan_path = state.get("scan_path") if state else None
    raw_target = (
        (state or {}).get("config", {}).get("target_strict_score", 95)
        if isinstance(state, dict)
        else 95
    )
    try:
        subjective_threshold = float(raw_target)
    except (TypeError, ValueError):
        subjective_threshold = 95.0
    subjective_threshold = max(0.0, min(100.0, subjective_threshold))
    if "findings" not in queue_state:
        queue_state = {**queue_state, "findings": findings}

    queue = work_queue_mod.build_work_queue(
        queue_state,
        options=work_queue_mod.QueueBuildOptions(
            count=None,
            scan_path=scan_path,
            status="open",
            include_subjective=True,
            subjective_threshold=subjective_threshold,
            no_tier_fallback=True,
        ),
    )
    open_items = queue.get("items", [])
    by_tier_file: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for item in open_items:
        tier = int(item.get("effective_tier", item.get("tier", 3)))
        by_tier_file[tier][item.get("file", ".")].append(item)

    lines: list[str] = []
    for tier_num in [1, 2, 3, 4]:
        tier_files = by_tier_file.get(tier_num, {})
        if not tier_files:
            continue

        label = TIER_LABELS.get(tier_num, f"Tier {tier_num}")
        tier_count = sum(len(file_findings) for file_findings in tier_files.values())
        lines.extend(
            [
                "---",
                f"## Tier {tier_num}: {label} ({tier_count} open)",
                "",
            ]
        )

        sorted_files = sorted(
            tier_files.items(), key=lambda item: (-len(item[1]), item[0])
        )
        for filepath, file_items in sorted_files:
            display_path = "Codebase-wide" if filepath == "." else filepath
            lines.append(f"### `{display_path}` ({len(file_items)} findings)")
            lines.append("")
            for item in file_items:
                if item.get("kind") == "subjective_dimension":
                    lines.append(f"- [ ] [subjective] {item.get('summary', '')}")
                    lines.append(f"      `{item.get('id', '')}`")
                    if item.get("primary_command"):
                        lines.append(f"      action: `{item['primary_command']}`")
                    continue

                conf_badge = f"[{item.get('confidence', 'medium')}]"
                lines.append(f"- [ ] {conf_badge} {item.get('summary', '')}")
                lines.append(f"      `{item.get('id', '')}`")
            lines.append("")

    return lines


def _tier_summary_lines(stats: dict) -> list[str]:
    lines: list[str] = []
    by_tier = stats.get("by_tier", {})
    for tier_num in [1, 2, 3, 4]:
        tier_stats = by_tier.get(str(tier_num), {})
        open_count = tier_stats.get("open", 0)
        total = sum(tier_stats.values())
        addressed = total - open_count
        pct = round(addressed / total * 100) if total else 100
        label = TIER_LABELS.get(tier_num, f"Tier {tier_num}")
        lines.append(
            f"- **Tier {tier_num}** ({label}): {open_count} open / {total} total ({pct}% addressed)"
        )
    lines.append("")
    return lines


def _addressed_section(findings: dict) -> list[str]:
    addressed = [
        finding for finding in findings.values() if finding["status"] != "open"
    ]
    if not addressed:
        return []

    lines: list[str] = ["---", "## Addressed", ""]
    by_status: dict[str, int] = defaultdict(int)
    for finding in addressed:
        by_status[finding["status"]] += 1
    for status, count in sorted(by_status.items()):
        lines.append(f"- **{status}**: {count}")

    wontfix = [
        finding
        for finding in addressed
        if finding["status"] == "wontfix" and finding.get("note")
    ]
    if wontfix:
        lines.extend(["", "### Wontfix (with explanations)", ""])
        for finding in wontfix[:30]:
            lines.append(f"- `{finding['id']}` — {finding['note']}")

    lines.append("")
    return lines


def generate_plan_md(state: PlanState) -> str:
    """Generate a prioritized markdown plan from state."""
    findings = state["findings"]
    stats = state.get("stats", {})

    lines = _plan_header(state, stats)
    lines.extend(_plan_dimension_table(state))
    lines.extend(_tier_summary_lines(stats))
    lines.extend(_plan_tier_sections(findings, state=state))
    lines.extend(_addressed_section(findings))

    return "\n".join(lines)
