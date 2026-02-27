"""Terminal rendering helpers for the `next` command."""

from __future__ import annotations

from desloppify import scoring as scoring_mod
from desloppify.app.commands.scan.scan_reporting_subjective import (
    build_subjective_followup,
)
from desloppify.engine.planning.scorecard_projection import (
    scorecard_subjective_entries,
)
from desloppify.engine.work_queue import ATTEST_EXAMPLE, group_queue_items
from desloppify.intelligence.integrity import (
    is_holistic_subjective_finding,
    subjective_review_open_breakdown,
    unassessed_subjective_dimensions,
)
from desloppify.core.output_api import colorize
from desloppify.core.paths_api import read_code_snippet


def scorecard_subjective(
    state: dict,
    dim_scores: dict,
) -> list[dict]:
    """Return scorecard-aligned subjective entries for current dimension scores."""
    if not dim_scores:
        return []
    return scorecard_subjective_entries(
        state,
        dim_scores=dim_scores,
    )


def subjective_coverage_breakdown(
    findings_scoped: dict,
) -> tuple[int, dict[str, int], dict[str, int]]:
    """Return open subjective-review count plus reason and holistic-reason breakdowns."""
    return subjective_review_open_breakdown(findings_scoped)


def _tier_label(tier: int) -> str:
    return f"T{tier}"


def _render_tier_navigator(queue: dict) -> None:
    counts = queue.get("tier_counts", {})
    print(colorize("\n  Tier Navigator", "bold"))
    print(
        colorize(
            f"    Open: T1:{counts.get(1, 0)} T2:{counts.get(2, 0)} "
            f"T3:{counts.get(3, 0)} T4:{counts.get(4, 0)}",
            "dim",
        )
    )
    print(
        colorize(
            "    Switch: `desloppify next --tier 1` | `desloppify next --tier 2` | "
            "`desloppify next --tier 3` | `desloppify next --tier 4`",
            "dim",
        )
    )


def _render_grouped(items: list[dict], group: str) -> None:
    grouped = group_queue_items(items, group)
    for key, grouped_items in grouped.items():
        print(colorize(f"\n  {key} ({len(grouped_items)})", "cyan"))
        for item in grouped_items:
            tier = int(item.get("effective_tier", item.get("tier", 3)))
            tag = _effort_tag(item)
            tag_str = f" {tag}" if tag else ""
            print(
                f"    {_tier_label(tier)} [{item.get('confidence', 'medium')}]{tag_str} {item.get('summary', '')}"
            )


def is_auto_fix_command(command: str | None) -> bool:
    cmd = (command or "").strip()
    return cmd.startswith("desloppify fix ") and "--dry-run" in cmd


def _effort_tag(item: dict) -> str:
    """Return a short effort/type tag for a queue item."""
    if item.get("detector") == "review":
        return "[review]"
    if is_auto_fix_command(item.get("primary_command")):
        return "[auto]"
    return ""


_ACTION_TYPE_LABELS = {
    "auto_fix": "Auto-fixable batch",
    "reorganize": "Reorganize batch",
    "refactor": "Refactor batch",
    "manual_fix": "Grouped task",
}


def _render_cluster_item(item: dict) -> None:
    """Render an auto-cluster task card."""
    member_count = int(item.get("member_count", 0))
    action_type = item.get("action_type", "manual_fix")
    cluster_name = item.get("id", "")
    if cluster_name == "auto/initial-review":
        type_label = "Initial subjective review"
    elif cluster_name == "auto/stale-review":
        type_label = "Stale subjective review"
    else:
        type_label = _ACTION_TYPE_LABELS.get(action_type, "Grouped task")
    print(colorize(f"  ({type_label}, {member_count} findings)", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")

    # Show breakdown by file (compact) + representative members
    members = item.get("members", [])
    if members:
        # File distribution
        from collections import Counter
        file_counts = Counter(m.get("file", "?") for m in members)
        if len(file_counts) <= 5:
            print(colorize("\n  Files:", "dim"))
            for f, c in file_counts.most_common():
                print(f"    {f} ({c})")
        else:
            print(colorize(f"\n  Spread across {len(file_counts)} files:", "dim"))
            for f, c in file_counts.most_common(3):
                print(f"    {f} ({c})")
            remaining = len(file_counts) - 3
            print(colorize(f"    ... and {remaining} more files", "dim"))

        # Sample IDs
        print(colorize("\n  Sample:", "dim"))
        for m in members[:3]:
            print(f"    - {m.get('id', '')}")
        if len(members) > 3:
            print(colorize(f"    ... and {len(members) - 3} more", "dim"))

    # Action
    cluster_name = item.get("id", "")
    primary_command = item.get("primary_command")
    if primary_command:
        print(colorize(f"\n  Action: {primary_command}", "cyan"))

    # Resolution hints
    print(colorize(f'\n  Resolve all:   desloppify plan done "{cluster_name}" '
                   f'--note "<what>" --attest "{ATTEST_EXAMPLE}"', "dim"))
    print(colorize(f"  Drill in:      desloppify next --cluster {cluster_name} --count 10",
                   "dim"))
    print(colorize(f"  Skip cluster:  desloppify plan skip {cluster_name}", "dim"))


def _render_item(
    item: dict, dim_scores: dict, findings_scoped: dict, explain: bool,
    potentials: dict | None = None,
) -> None:
    # Delegate to cluster renderer for cluster meta-items
    if item.get("kind") == "cluster":
        _render_cluster_item(item)
        return

    tier = int(item.get("effective_tier", item.get("tier", 3)))
    confidence = item.get("confidence", "medium")
    print(colorize(f"  (Tier {tier}, {confidence} confidence)", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")

    # Effort/type label
    if item.get("detector") == "review":
        print(colorize("  Type: Design review (requires judgment)", "dim"))
    elif is_auto_fix_command(item.get("primary_command")):
        print(colorize("  Type: Auto-fixable", "dim"))

    kind = item.get("kind", "finding")
    if kind == "subjective_dimension":
        detail = item.get("detail", {})
        subjective_score = float(
            detail.get("strict_score", item.get("subjective_score", 100.0))
        )
        print(f"  Dimension: {detail.get('dimension_name', 'unknown')}")
        print(f"  Score: {subjective_score:.1f}% (always queued as T4)")
        print(
            colorize(
                f"  Action: {item.get('primary_command', 'desloppify review --prepare')}",
                "cyan",
            )
        )
        print(colorize(
            "  Note: re-review scores what it finds — scores can go down if issues are discovered.",
            "dim",
        ))
        if explain:
            reason = item.get("explain", {}).get(
                "policy",
                "subjective items are fixed at T4 and do not outrank mechanical T1/T2/T3.",
            )
            print(colorize(f"  explain: {reason}", "dim"))
        return

    # Plan overrides: description, cluster, note
    if item.get("plan_description"):
        print(colorize(f"  → {item['plan_description']}", "cyan"))
    plan_cluster = item.get("plan_cluster")
    if isinstance(plan_cluster, dict):
        cluster_name = plan_cluster.get("name", "")
        cluster_desc = plan_cluster.get("description") or ""
        total = plan_cluster.get("total_items", 0)
        desc_str = f' — "{cluster_desc}"' if cluster_desc else ""
        print(colorize(f"  Cluster: {cluster_name}{desc_str} ({total} items)", "dim"))
    if item.get("plan_note"):
        print(colorize(f"  Note: {item['plan_note']}", "dim"))

    print(f"  File: {item.get('file', '')}")
    print(colorize(f"  ID:   {item.get('id', '')}", "dim"))

    detail = item.get("detail", {})
    if detail.get("lines"):
        print(f"  Lines: {', '.join(str(line_no) for line_no in detail['lines'][:8])}")
    if detail.get("category"):
        print(f"  Category: {detail['category']}")
    if detail.get("importers") is not None:
        print(f"  Active importers: {detail['importers']}")
    if detail.get("suggestion"):
        print(colorize(f"\n  Suggestion: {detail['suggestion']}", "dim"))

    target_line = detail.get("line") or (detail.get("lines", [None]) or [None])[0]
    if target_line and item.get("file") not in (".", ""):
        snippet = read_code_snippet(item["file"], target_line)
        if snippet:
            print(colorize("\n  Code:", "dim"))
            print(snippet)

    if dim_scores:
        detector = item.get("detector", "")
        dimension = scoring_mod.get_dimension_for_detector(detector)
        if dimension and dimension.name in dim_scores:
            dimension_score = dim_scores[dimension.name]
            strict_val = dimension_score.get("strict", dimension_score["score"])
            print(
                colorize(
                    f"\n  Dimension: {dimension.name} — {dimension_score['score']:.1f}% "
                    f"(strict: {strict_val:.1f}%) "
                    f"({dimension_score['issues']} of {dimension_score['checks']:,} checks failing)",
                    "dim",
                )
            )

    # Score impact estimate
    detector = item.get("detector", "")
    if potentials and detector and dim_scores:
        try:
            from desloppify.scoring import compute_score_impact
            impact = compute_score_impact(dim_scores, potentials, detector, issues_to_fix=1)
            if impact > 0:
                print(colorize(f"  Impact: fixing this is worth ~+{impact:.1f} pts on overall score", "cyan"))
            else:
                # Single-item impact rounds to 0 — try bulk impact for all issues in detector
                dimension = scoring_mod.get_dimension_for_detector(detector)
                if dimension and dimension.name in dim_scores:
                    issues = dim_scores[dimension.name].get("issues", 0)
                    if issues > 1:
                        bulk = compute_score_impact(dim_scores, potentials, detector, issues_to_fix=issues)
                        if bulk > 0:
                            print(colorize(
                                f"  Impact: fixing all {issues} {detector} issues → ~+{bulk:.1f} pts",
                                "cyan",
                            ))
        except (ImportError, TypeError, ValueError, KeyError):
            pass
    elif detector == "review" and dim_scores:
        # Review findings: show dimension drag from breakdown
        try:
            from desloppify.scoring import compute_health_breakdown
            dim_key = item.get("detail", {}).get("dimension", "")
            if dim_key:
                breakdown = compute_health_breakdown(dim_scores)
                for entry in breakdown.get("entries", []):
                    if not isinstance(entry, dict):
                        continue
                    entry_key = str(entry.get("name", "")).lower().replace(" ", "_")
                    if entry_key == dim_key.lower().replace(" ", "_"):
                        drag = float(entry.get("overall_drag", 0) or 0)
                        if drag > 0.01:
                            print(colorize(
                                f"  Dimension drag: {entry['name']} costs -{drag:.2f} pts on overall score",
                                "cyan",
                            ))
                        break
        except (ImportError, TypeError, ValueError, KeyError):
            pass

    detector_name = item.get("detector", "")
    auto_fix_command = item.get("primary_command")
    if is_auto_fix_command(auto_fix_command):
        similar_count = sum(
            1
            for finding in findings_scoped.values()
            if finding.get("detector") == detector_name and finding["status"] == "open"
        )
        if similar_count > 1:
            print(
                colorize(
                    f"\n  Auto-fixable: {similar_count} similar findings. "
                    f"Run `{auto_fix_command}` to fix all at once.",
                    "cyan",
                )
            )
    if explain:
        explanation = item.get("explain", {})
        count_weight = explanation.get("count", int(detail.get("count", 0) or 0))
        base = (
            f"ranked by tier={tier}, confidence={confidence}, "
            f"count={count_weight}, id={item.get('id', '')}"
        )

        # Add dimension context for mechanical detectors
        if dim_scores and detector:
            dimension = scoring_mod.get_dimension_for_detector(detector)
            if dimension and dimension.name in dim_scores:
                ds = dim_scores[dimension.name]
                base += (
                    f". Dimension: {dimension.name} at {ds['score']:.1f}% "
                    f"({ds['issues']} open issues)"
                )

        # For review findings, show subjective dimension context
        if item.get("detector") == "review" and dim_scores:
            dim_key = item.get("detail", {}).get("dimension", "")
            if dim_key:
                for ds_name, ds_data in dim_scores.items():
                    if ds_name.lower().replace(" ", "_") == dim_key.lower().replace(" ", "_"):
                        score_val = ds_data.get("score", "?")
                        score_str = f"{score_val:.1f}" if isinstance(score_val, (int, float)) else str(score_val)
                        base += f". Subjective dimension: {ds_name} at {score_str}%"
                        break

        policy = explanation.get("policy")
        if policy:
            base = f"{base}. {policy}"
        print(colorize(f"  explain: {base}", "dim"))


def render_queue_header(queue: dict, explain: bool) -> None:
    _render_tier_navigator(queue)
    if not queue.get("fallback_reason"):
        return
    print(colorize(f"  {queue['fallback_reason']}", "yellow"))
    if not explain:
        return
    available = queue.get("available_tiers", [])
    if available:
        tiers = ", ".join(f"T{tier_num}" for tier_num in available)
        print(colorize(f"  explain: available tiers are {tiers}", "dim"))


def show_empty_queue(queue: dict, tier: int | None, strict: float | None) -> bool:
    if queue.get("items"):
        return False
    suffix = f" Strict score: {strict:.1f}/100" if strict is not None else ""
    print(colorize(f"\n  Nothing to do!{suffix}", "green"))
    if tier is not None:
        print(colorize(f"  Requested tier: T{tier}", "dim"))
        available = queue.get("available_tiers", [])
        if available:
            commands = " | ".join(
                f"desloppify next --tier {tier_num}" for tier_num in available
            )
            print(colorize(f"  Try: {commands}", "dim"))
    return True


def render_terminal_items(
    items: list[dict],
    dim_scores: dict,
    findings_scoped: dict,
    *,
    group: str,
    explain: bool,
    potentials: dict | None = None,
    plan: dict | None = None,
) -> None:
    # Show focus header if plan has active cluster
    if plan and plan.get("active_cluster"):
        cluster_name = plan["active_cluster"]
        clusters = plan.get("clusters", {})
        cluster_data = clusters.get(cluster_name, {})
        total = len(cluster_data.get("finding_ids", []))
        print(colorize(f"\n  Focused on: {cluster_name} ({len(items)} of {total} remaining)", "cyan"))

    if group != "item":
        _render_grouped(items, group)
        return
    for idx, item in enumerate(items):
        if idx > 0:
            print()
        queue_pos = item.get("queue_position")
        if queue_pos and len(items) > 1:
            label = f"  [#{queue_pos}]"
        elif len(items) > 1:
            label = f"  [{idx + 1}/{len(items)}]"
        else:
            pos_str = f"  (#{ queue_pos} in queue)" if queue_pos else ""
            label = f"  Next item{pos_str}"
        print(colorize(label, "bold"))
        _render_item(item, dim_scores, findings_scoped, explain=explain, potentials=potentials)


def render_single_item_resolution_hint(items: list[dict]) -> None:
    if len(items) != 1:
        return
    if items[0].get("kind") == "cluster":
        return  # Cluster card already includes resolution hints
    if items[0].get("kind") != "finding":
        return
    item = items[0]
    detector_name = item.get("detector", "")
    if detector_name == "subjective_review":
        print(colorize("\n  Review with:", "dim"))
        primary = item.get(
            "primary_command", "desloppify show subjective"
        )
        print(f"    {primary}")
        if is_holistic_subjective_finding(item):
            print("    desloppify review --prepare")
        return

    primary = item.get("primary_command", "")
    if is_auto_fix_command(primary):
        print(colorize("\n  Fix with:", "dim"))
        print(f"    {primary}")
        print(colorize("  Or resolve individually:", "dim"))
    else:
        print(colorize("\n  Resolve with:", "dim"))

    print(
        f'    desloppify plan done "{item["id"]}" --note "<what you did>" '
        f'--attest "{ATTEST_EXAMPLE}"'
    )
    print(
        f'    desloppify plan skip --permanent "{item["id"]}" --note "<why>" '
        f'--attest "{ATTEST_EXAMPLE}"'
    )


def render_followup_nudges(
    state: dict,
    dim_scores: dict,
    findings_scoped: dict,
    *,
    strict_score: float | None,
    target_strict_score: float,
) -> None:
    subjective_threshold = target_strict_score
    subjective_entries = scorecard_subjective(state, dim_scores)
    followup = build_subjective_followup(
        state,
        subjective_entries,
        threshold=subjective_threshold,
        max_quality_items=3,
        max_integrity_items=5,
    )
    unassessed_subjective = unassessed_subjective_dimensions(dim_scores)
    if strict_score is not None:
        gap = round(float(target_strict_score) - float(strict_score), 1)
        if gap > 0:
            print(
                colorize(
                    f"\n  North star: strict {strict_score:.1f}/100 → target {target_strict_score:.1f} (+{gap:.1f} needed)",
                    "cyan",
                )
            )
        else:
            print(
                colorize(
                    f"\n  North star: strict {strict_score:.1f}/100 meets target {target_strict_score:.1f}",
                    "green",
                )
            )
    # Integrity penalty/warn lines preserved (anti-gaming safeguard, must remain visible).
    for style, message in followup.integrity_lines:
        print(colorize(f"\n  {message}", style))

    # Collapsed subjective summary.
    coverage_open, _coverage_reasons, _holistic_reasons = subjective_coverage_breakdown(
        findings_scoped
    )
    parts: list[str] = []
    low_dims = len(followup.low_assessed)
    unassessed_count = len(unassessed_subjective)
    stale_count = sum(1 for e in subjective_entries if e.get("stale"))
    open_review = [
        f for f in findings_scoped.values()
        if f.get("status") == "open" and f.get("detector") == "review"
    ]
    if low_dims:
        parts.append(f"{low_dims} dimension{'s' if low_dims != 1 else ''} below target")
    if stale_count:
        parts.append(f"{stale_count} stale")
    if unassessed_count:
        parts.append(f"{unassessed_count} unassessed")
    if len(open_review):
        parts.append(f"{len(open_review)} review finding{'s' if len(open_review) != 1 else ''} open")
    if coverage_open > 0:
        parts.append(f"{coverage_open} file{'s' if coverage_open != 1 else ''} need review")

    if parts:
        print(colorize(f"\n  Subjective: {', '.join(parts)}.", "cyan"))
        print(colorize("  Run `desloppify show subjective` for details.", "dim"))


__all__ = [
    "is_auto_fix_command",
    "render_followup_nudges",
    "render_queue_header",
    "render_single_item_resolution_hint",
    "render_terminal_items",
    "scorecard_subjective",
    "show_empty_queue",
    "subjective_coverage_breakdown",
]
