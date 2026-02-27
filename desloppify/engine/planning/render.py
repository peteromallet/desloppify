"""Markdown plan rendering."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from desloppify.core.registry import dimension_action_type
from desloppify.engine.planning.common import TIER_LABELS
from desloppify.engine.planning.types import PlanState
from desloppify.engine.work_queue import QueueBuildOptions, build_work_queue
from desloppify.scoring import DIMENSIONS, DISPLAY_NAMES
from desloppify.state import get_objective_score, get_overall_score, get_strict_score
from desloppify.core.output_api import LOC_COMPACT_THRESHOLD


def _plan_header(state: PlanState, stats: dict) -> list[str]:
    """Build the plan header: title, score line, and codebase metrics."""
    overall_score = get_overall_score(state)
    objective_score = get_objective_score(state)
    strict_score = get_strict_score(state)

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
        loc_str = (
            f"{total_loc:,}"
            if total_loc < LOC_COMPACT_THRESHOLD
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
    static_names: set[str] = set()
    rendered_names: set[str] = set()
    subjective_display_names = {
        display.lower() for display in DISPLAY_NAMES.values()
    }

    def _looks_subjective(name: str, data: dict) -> bool:
        detectors = data.get("detectors", {})
        if "subjective_assessment" in detectors:
            return True
        lowered = name.strip().lower()
        return lowered in subjective_display_names or lowered.startswith("elegance")

    for dim in DIMENSIONS:
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
        action = dimension_action_type(dim.name)
        lines.append(
            f"| {bold}{dim.name}{bold} | T{dim.tier} | "
            f"{checks:,} | {issues} | {score_val:.1f}% | {strict_val:.1f}% | {action} |"
        )

    from desloppify.engine.planning.dimension_rows import scorecard_dimension_rows

    scorecard_rows = scorecard_dimension_rows(state)
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
        action = dimension_action_type(name)
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

    queue = build_work_queue(
        queue_state,
        options=QueueBuildOptions(
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


def _plan_user_ordered_section(
    items: list[dict],
    plan: dict,
) -> list[str]:
    """Render the user-ordered queue section, grouped by cluster."""
    queue_order: list[str] = plan.get("queue_order", [])
    skipped_ids: set[str] = set(plan.get("skipped", {}).keys())
    overrides: dict = plan.get("overrides", {})
    clusters: dict = plan.get("clusters", {})

    ordered_ids = set(queue_order) - skipped_ids
    if not ordered_ids:
        return []

    by_id = {item.get("id"): item for item in items}

    lines: list[str] = [
        "---",
        f"## User-Ordered Queue ({len(ordered_ids)} items)",
        "",
    ]

    # Group by cluster: clustered items first, then unclustered
    emitted: set[str] = set()
    for cluster_name, cluster in clusters.items():
        member_ids = [
            fid for fid in cluster.get("finding_ids", [])
            if fid in ordered_ids and fid in by_id
        ]
        if not member_ids:
            continue
        desc = cluster.get("description") or ""
        lines.append(f"### Cluster: {cluster_name}")
        if desc:
            lines.append(f"> {desc}")
        lines.append("")
        for fid in member_ids:
            item = by_id.get(fid)
            if item:
                lines.extend(_render_plan_item(item, overrides.get(fid, {})))
                emitted.add(fid)
        lines.append("")

    # Unclustered ordered items
    unclustered = [
        fid for fid in queue_order
        if fid in ordered_ids and fid not in emitted and fid in by_id
    ]
    if unclustered:
        if any(c.get("finding_ids") for c in clusters.values()):
            lines.append("### (unclustered ordered items)")
            lines.append("")
        for fid in unclustered:
            item = by_id.get(fid)
            if item:
                lines.extend(_render_plan_item(item, overrides.get(fid, {})))
        lines.append("")

    return lines


def _plan_skipped_section(items: list[dict], plan: dict) -> list[str]:
    """Render the skipped items section, grouped by kind."""
    skipped = plan.get("skipped", {})
    if not skipped:
        return []

    by_id = {item.get("id"): item for item in items}
    overrides = plan.get("overrides", {})

    # Group by kind
    by_kind: dict[str, list[str]] = {"temporary": [], "permanent": [], "false_positive": []}
    for fid, entry in skipped.items():
        kind = entry.get("kind", "temporary")
        by_kind.setdefault(kind, []).append(fid)

    kind_labels = {
        "temporary": "Skipped Temporarily",
        "permanent": "Wontfix (permanent)",
        "false_positive": "False Positives",
    }

    lines: list[str] = [
        "---",
        f"## Skipped ({len(skipped)} items)",
        "",
    ]

    for kind in ("temporary", "permanent", "false_positive"):
        ids = by_kind.get(kind, [])
        if not ids:
            continue
        lines.append(f"### {kind_labels[kind]} ({len(ids)})")
        lines.append("")
        for fid in ids:
            entry = skipped.get(fid, {})
            item = by_id.get(fid)
            if item:
                lines.extend(_render_plan_item(item, overrides.get(fid, {})))
            else:
                lines.append(f"- ~~{fid}~~ (not in current queue)")
            reason = entry.get("reason")
            if reason:
                lines.append(f"      Reason: {reason}")
            note = entry.get("note")
            if note and not overrides.get(fid, {}).get("note"):
                lines.append(f"      Note: {note}")
            review_after = entry.get("review_after")
            if review_after:
                skipped_at = entry.get("skipped_at_scan", 0)
                lines.append(f"      Review after: scan {skipped_at + review_after}")
        lines.append("")

    return lines


def _plan_superseded_section(plan: dict) -> list[str]:
    """Render the superseded items section."""
    superseded = plan.get("superseded", {})
    if not superseded:
        return []

    lines: list[str] = [
        "---",
        f"## Superseded ({len(superseded)} items — may need remap)",
        "",
    ]
    for fid, entry in superseded.items():
        summary = entry.get("original_summary", "")
        summary_str = f" — {summary}" if summary else ""
        lines.append(f"- ~~{fid}~~{summary_str}")
        candidates = entry.get("candidates", [])
        if candidates:
            lines.append(f"  Candidates: {', '.join(candidates[:3])}")
        note = entry.get("note")
        if note:
            lines.append(f"  Note: {note}")
    lines.append("")
    return lines


def _render_plan_item(item: dict, override: dict) -> list[str]:
    """Render a single plan item as markdown lines."""
    tier = int(item.get("effective_tier", item.get("tier", 3)))
    confidence = item.get("confidence", "medium")
    summary = item.get("summary", "")
    item_id = item.get("id", "")

    lines = [f"- [ ] [T{tier}/{confidence}] {summary}"]
    desc = override.get("description")
    if desc:
        lines.append(f"      → {desc}")
    lines.append(f"      `{item_id}`")
    note = override.get("note")
    if note:
        lines.append(f"      Note: {note}")
    return lines


def generate_plan_md(state: PlanState, plan: dict | None = None) -> str:
    """Generate a prioritized markdown plan from state.

    When *plan* is provided (or auto-loaded from disk), user-ordered
    items, clusters, skipped, and superseded sections are rendered.
    When no plan exists, output is identical to the previous behavior.
    """
    findings = state["findings"]
    stats = state.get("stats", {})

    # Auto-load plan if not provided
    if plan is None:
        try:
            from desloppify.engine.plan import load_plan
            plan = load_plan()
        except Exception:
            plan = {}

    has_plan = bool(
        plan
        and (
            plan.get("queue_order")
            or plan.get("skipped")
            or plan.get("clusters")
        )
    )

    lines = _plan_header(state, stats)
    lines.extend(_plan_dimension_table(state))
    lines.extend(_tier_summary_lines(stats))

    if has_plan:
        # Build full queue for item lookup
        queue = build_work_queue(
            state,
            options=QueueBuildOptions(
                count=None,
                scan_path=state.get("scan_path"),
                status="open",
                include_subjective=True,
                no_tier_fallback=True,
            ),
        )
        all_items = queue.get("items", [])
        lines.extend(_plan_user_ordered_section(all_items, plan))

        # Remaining: items NOT in queue_order or skipped
        ordered_ids = set(plan.get("queue_order", []))
        skipped_ids = set(plan.get("skipped", {}).keys())
        plan_ids = ordered_ids | skipped_ids
        remaining = [item for item in all_items if item.get("id") not in plan_ids]
        if remaining:
            lines.append("---")
            lines.append(f"## Remaining (mechanical order, {len(remaining)} items)")
            lines.append("")

        lines.extend(_plan_tier_sections(findings, state=state))
        lines.extend(_plan_skipped_section(all_items, plan))
        lines.extend(_plan_superseded_section(plan))
    else:
        lines.extend(_plan_tier_sections(findings, state=state))

    lines.extend(_addressed_section(findings))

    return "\n".join(lines)
