"""Terminal rendering helpers for the `next` command."""

from __future__ import annotations

from desloppify.base.output.terminal import colorize, log
from desloppify.base.output.user_message import print_user_message
from desloppify.base.discovery.paths import read_code_snippet
from desloppify.engine._scoring.results.core import (
    compute_health_breakdown,
    compute_score_impact,
    get_dimension_for_detector,
)
from desloppify.engine._work_queue.helpers import workflow_stage_name

from .render_support import is_auto_fix_command
from .render_support import render_cluster_item as _render_cluster_item
from .render_support import render_compact_item as _render_compact_item
from .render_support import render_grouped as _render_grouped


def _normalized_dimension_key(value: str | None) -> str:
    return str(value or "").lower().replace(" ", "_")


def _render_workflow_stage(item: dict) -> None:
    """Render a triage workflow stage item."""
    blocked = item.get("is_blocked", False)
    detail = item.get("detail", {})
    stage = workflow_stage_name(item)
    tag = " [blocked]" if blocked else ""
    style = "dim" if blocked else "bold"
    print(colorize(f"  (Planning stage: {stage}{tag})", style))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")
    total = detail.get("total_review_issues", 0)
    if total:
        print(colorize(f"  {total} review issues to analyze", "dim"))
    if blocked:
        blocked_by = item.get("blocked_by", [])
        deps = ", ".join(b.replace("triage::", "") for b in blocked_by)
        print(colorize(f"  Blocked by: {deps}", "dim"))
        first_dep = blocked_by[0] if blocked_by else ""
        dep_name = first_dep.replace("triage::", "")
        if dep_name:
            print(colorize(f"  Next step: desloppify plan triage --stage {dep_name}", "dim"))
    else:
        print(colorize(f"\n  Action: {item.get('primary_command', '')}", "cyan"))


def _render_workflow_action(item: dict) -> None:
    """Render a workflow action item (e.g. create-plan).

    Side-effect only: prints a formatted card to stdout for terminal display.
    Called from _render_item when item kind is 'workflow_action'.
    """
    print(colorize("  (Workflow step)", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")
    print(colorize(f"\n  Action: {item.get('primary_command', '')}", "cyan"))


def _render_subjective_dimension(item: dict, *, explain: bool) -> None:
    """Render a subjective dimension re-review item."""
    detail = item.get("detail", {})
    subjective_score = float(
        detail.get("strict_score", item.get("subjective_score", 100.0))
    )
    print(f"  Dimension: {detail.get('dimension_name', 'unknown')}")
    print(f"  Score: {subjective_score:.1f}%")
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
    print_user_message(
        "Hey — this is a subjective review item. Run"
        " `desloppify review --run-batches --dry-run`"
        " to generate prompt files (one per batch)."
        " Launch one subagent per prompt, all in"
        " parallel. Then import with `--import-run"
        " <run-dir> --scan-after-import`. Batches are"
        " pre-defined — do NOT regroup them yourself."
    )
    if explain:
        reason = item.get("explain", {}).get(
            "policy",
            "subjective items sort after mechanical items at the same level.",
        )
        print(colorize(f"  explain: {reason}", "dim"))


def _render_issue_detail(
    item: dict, *, single_item: bool = False, header_showed_plan: bool = False,
) -> dict:
    """Render plan overrides, file info, and detail fields. Returns parsed detail dict."""
    if item.get("plan_description"):
        print(colorize(f"  → {item['plan_description']}", "cyan"))
    plan_cluster = item.get("plan_cluster")
    if isinstance(plan_cluster, dict):
        cluster_name = plan_cluster.get("name", "")
        cluster_desc = plan_cluster.get("description") or ""
        total = plan_cluster.get("total_items", 0)
        desc_str = f' — "{cluster_desc}"' if cluster_desc else ""
        print(colorize(f"  Cluster: {cluster_name}{desc_str} ({total} items)", "dim"))
        steps = plan_cluster.get("action_steps") or []
        if steps and single_item and not header_showed_plan:
            print(colorize("\n  Steps:", "dim"))
            for i, step in enumerate(steps, 1):
                print(colorize(f"    {i}. {step}", "dim"))
    if item.get("plan_note"):
        print(colorize(f"  Note: {item['plan_note']}", "dim"))

    print(f"  File: {item.get('file', '')}")
    print(colorize(f"  ID:   {item.get('id', '')}", "dim"))

    detail = item.get("detail", {})
    if isinstance(detail, str):
        detail = {"suggestion": detail}
    if isinstance(detail, dict):
        detail.setdefault("lines", [])
        detail.setdefault("line", None)
        detail.setdefault("category", None)
        detail.setdefault("importers", None)
        detail.setdefault("count", 0)
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

    return detail


def _render_dimension_context(detector: str, dim_scores: dict) -> None:
    if not dim_scores:
        return
    dimension = get_dimension_for_detector(detector)
    if not dimension or dimension.name not in dim_scores:
        return
    dimension_score = dim_scores[dimension.name]
    strict_val = dimension_score.get("strict", dimension_score["score"])
    print(
        colorize(
            f"\n  Dimension: {dimension.name} — {dimension_score['score']:.1f}% "
            f"(strict: {strict_val:.1f}%) "
            f"({dimension_score.get('failing', 0)} of {dimension_score['checks']:,} checks failing)",
            "dim",
        )
    )


def _render_detector_impact_estimate(
    detector: str, dim_scores: dict, potentials: dict,
) -> None:
    try:
        impact = compute_score_impact(dim_scores, potentials, detector, issues_to_fix=1)
        if impact > 0:
            print(colorize(f"  Impact: fixing this is worth ~+{impact:.1f} pts on overall score", "cyan"))
            return

        dimension = get_dimension_for_detector(detector)
        if not dimension or dimension.name not in dim_scores:
            return
        issues = dim_scores[dimension.name].get("failing", 0)
        if issues <= 1:
            return
        bulk = compute_score_impact(dim_scores, potentials, detector, issues_to_fix=issues)
        if bulk > 0:
            print(colorize(
                f"  Impact: fixing all {issues} {detector} issues → ~+{bulk:.1f} pts",
                "cyan",
            ))
    except (ImportError, TypeError, ValueError, KeyError) as exc:
        log(f"  score impact estimate skipped: {exc}")


def _render_review_dimension_drag(item: dict, dim_scores: dict) -> None:
    try:
        dim_key = item.get("detail", {}).get("dimension", "")
        if not dim_key:
            return
        breakdown = compute_health_breakdown(dim_scores)
        target_key = _normalized_dimension_key(dim_key)
        for entry in breakdown.get("entries", []):
            if not isinstance(entry, dict):
                continue
            if _normalized_dimension_key(entry.get("name", "")) != target_key:
                continue
            drag = float(entry.get("overall_drag", 0) or 0)
            if drag > 0.01:
                print(colorize(
                    f"  Dimension drag: {entry['name']} costs -{drag:.2f} pts on overall score",
                    "cyan",
                ))
            return
    except (ImportError, TypeError, ValueError, KeyError) as exc:
        log(f"  dimension drag estimate skipped: {exc}")


def _render_score_impact(
    item: dict, dim_scores: dict, potentials: dict | None,
) -> None:
    """Render dimension score context and impact estimates."""
    detector = item.get("detector", "")
    _render_dimension_context(detector, dim_scores)
    if potentials and detector and dim_scores:
        _render_detector_impact_estimate(detector, dim_scores, potentials)
        return
    if detector == "review" and dim_scores:
        _render_review_dimension_drag(item, dim_scores)


_KIND_RENDERERS = {
    "cluster": _render_cluster_item,
    "workflow_stage": _render_workflow_stage,
    "workflow_action": _render_workflow_action,
}


def _render_item_type(item: dict) -> None:
    detector = item.get("detector")
    if detector == "review":
        print(colorize("  Type: Design review (requires judgment)", "dim"))
        return
    if is_auto_fix_command(item.get("primary_command")):
        print(colorize("  Type: Auto-fixable", "dim"))


def _render_auto_fix_batch_hint(item: dict, issues_scoped: dict) -> None:
    auto_fix_command = item.get("primary_command")
    if not is_auto_fix_command(auto_fix_command):
        return
    detector_name = item.get("detector", "")
    similar_count = sum(
        1
        for issue in issues_scoped.values()
        if issue.get("detector") == detector_name and issue["status"] == "open"
    )
    if similar_count <= 1:
        return
    print(
        colorize(
            f"\n  Auto-fixable: {similar_count} similar issues. "
            f"Run `{auto_fix_command}` to fix all at once.",
            "cyan",
        )
    )


def _render_item_explain(
    item: dict, detail: dict, confidence: str, dim_scores: dict,
) -> None:
    explanation = item.get("explain", {})
    count_weight = explanation.get("count", int(detail.get("count", 0) or 0))
    detector = item.get("detector", "")
    base = (
        f"ranked by confidence={confidence}, "
        f"count={count_weight}, id={item.get('id', '')}"
    )
    if dim_scores and detector:
        dimension = get_dimension_for_detector(detector)
        if dimension and dimension.name in dim_scores:
            ds = dim_scores[dimension.name]
            base += (
                f". Dimension: {dimension.name} at {ds['score']:.1f}% "
                f"({ds.get('failing', 0)} open issues)"
            )
    if item.get("detector") == "review" and dim_scores:
        dim_key = _normalized_dimension_key(item.get("detail", {}).get("dimension", ""))
        if dim_key:
            for ds_name, ds_data in dim_scores.items():
                if _normalized_dimension_key(ds_name) != dim_key:
                    continue
                score_val = ds_data.get("score", "?")
                if isinstance(score_val, int | float):
                    score_str = f"{score_val:.1f}"
                else:
                    score_str = str(score_val)
                base += f". Subjective dimension: {ds_name} at {score_str}%"
                break
    policy = explanation.get("policy")
    if policy:
        base = f"{base}. {policy}"
    print(colorize(f"  explain: {base}", "dim"))


def _render_item(
    item: dict, dim_scores: dict, issues_scoped: dict, explain: bool,
    potentials: dict | None = None,
    single_item: bool = False,
    header_showed_plan: bool = False,
) -> None:
    kind = item.get("kind")
    kind_renderer = _KIND_RENDERERS.get(kind)
    if kind_renderer is not None:
        kind_renderer(item)
        return

    confidence = item.get("confidence", "medium")
    print(colorize(f"  ({confidence} confidence)", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")
    _render_item_type(item)

    if item.get("kind", "issue") == "subjective_dimension":
        _render_subjective_dimension(item, explain=explain)
        return

    detail = _render_issue_detail(
        item, single_item=single_item, header_showed_plan=header_showed_plan,
    )
    _render_score_impact(item, dim_scores, potentials)
    _render_auto_fix_batch_hint(item, issues_scoped)
    if explain:
        _render_item_explain(item, detail, confidence, dim_scores)


def _item_label(item: dict, idx: int, total: int) -> str:
    queue_pos = item.get("queue_position")
    if queue_pos and total > 1:
        return f"  [#{queue_pos}]"
    if total > 1:
        return f"  [{idx + 1}/{total}]"
    pos_str = f"  (#{ queue_pos} in queue)" if queue_pos else ""
    return f"  Next item{pos_str}"


def render_terminal_items(
    items: list[dict],
    dim_scores: dict,
    issues_scoped: dict,
    *,
    group: str,
    explain: bool,
    potentials: dict | None = None,
    plan: dict | None = None,
    cluster_filter: str | None = None,
) -> None:
    # Show focus header if plan has active cluster or cluster filter
    effective_cluster = cluster_filter or (plan and plan.get("active_cluster"))
    header_showed_plan = False
    if effective_cluster and plan:
        cluster_name = effective_cluster
        clusters = plan.get("clusters", {})
        cluster_data = clusters.get(cluster_name, {})
        total = len(cluster_data.get("issue_ids", []))
        print(colorize(f"\n  Focused on: {cluster_name} ({len(items)} of {total} remaining)", "cyan"))
        steps = cluster_data.get("action_steps") or []
        if steps:
            print(colorize("\n  Cluster plan:", "dim"))
            for i, step in enumerate(steps, 1):
                print(colorize(f"    {i}. {step}", "dim"))
            header_showed_plan = True

    if group != "item":
        _render_grouped(items, group)
        return

    # Detect cluster drill-in: multiple items with cluster focus active
    is_cluster_drill = len(items) > 1 and (
        cluster_filter or (plan and plan.get("active_cluster"))
    )

    for idx, item in enumerate(items):
        if idx > 0:
            print()
        # Full card for first item, compact for rest in cluster drill-in
        if is_cluster_drill and idx > 0:
            _render_compact_item(item, idx, len(items))
            continue
        label = _item_label(item, idx, len(items))
        print(colorize(label, "bold"))
        _render_item(
            item, dim_scores, issues_scoped, explain=explain, potentials=potentials,
            single_item=len(items) == 1,
            header_showed_plan=header_showed_plan,
        )


__all__ = [
    "render_terminal_items",
]
