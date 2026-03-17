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
from desloppify.engine._state.issue_semantics import (
    is_review_finding,
    is_assessment_request,
)
from desloppify.engine._work_queue.helpers import (
    is_auto_fix_item,
    workflow_stage_name,
)

from .render_support import is_auto_fix_command
from .render_support import render_cluster_item as _render_cluster_item
from .render_support import render_compact_item as _render_compact_item
from .render_support import render_grouped as _render_grouped
from .render_scoring import render_item_explain as _render_item_explain_impl
from .render_scoring import render_score_impact as _render_score_impact_impl
from .render_workflow import render_workflow_action as _render_workflow_action_impl
from .render_workflow import render_workflow_stage as _render_workflow_stage_impl
from .render_workflow import step_full as _step_full_impl
from .render_workflow import step_text as _step_text_impl


def _step_text(step: str | dict) -> str:
    return _step_text_impl(step)


def _step_full(step: str | dict, *, indent: str = "    ") -> list[str]:
    return _step_full_impl(step, indent=indent)


def _render_workflow_stage(item: dict) -> None:
    _render_workflow_stage_impl(
        item,
        colorize_fn=colorize,
        workflow_stage_name_fn=workflow_stage_name,
    )


def _render_workflow_action(item: dict) -> None:
    _render_workflow_action_impl(item, colorize_fn=colorize)


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


def _normalize_issue_detail(raw_detail: object) -> dict:
    if isinstance(raw_detail, str):
        raw_detail = {"suggestion": raw_detail}
    detail = dict(raw_detail) if isinstance(raw_detail, dict) else {}
    detail.setdefault("lines", [])
    detail.setdefault("line", None)
    detail.setdefault("category", None)
    detail.setdefault("importers", None)
    detail.setdefault("count", 0)
    return detail


def _render_plan_cluster_detail(
    item: dict,
    *,
    single_item: bool,
    header_showed_plan: bool,
) -> None:
    plan_cluster = item.get("plan_cluster")
    if not isinstance(plan_cluster, dict):
        return
    cluster_name = plan_cluster.get("name", "")
    cluster_desc = plan_cluster.get("description") or ""
    total = plan_cluster.get("total_items", 0)
    desc_str = f' — "{cluster_desc}"' if cluster_desc else ""
    print(colorize(f"  Cluster: {cluster_name}{desc_str} ({total} items)", "dim"))
    steps = plan_cluster.get("action_steps") or []
    if not steps:
        return

    # Find steps relevant to this item (via issue_refs)
    item_id = item.get("id", "")
    item_hash = item_id.rsplit("::", 1)[-1] if item_id else ""
    relevant = [
        (idx, step) for idx, step in enumerate(steps, 1)
        if isinstance(step, dict) and (
            item_id in step.get("issue_refs", [])
            or any(item_hash and ref.endswith(item_hash) for ref in step.get("issue_refs", []))
        )
    ]

    if relevant:
        # Show full detail for relevant steps — this is the execution view
        print(colorize("\n  Your step(s):", "bold"))
        for idx, step in relevant:
            for line in _step_full(step, indent="    "):
                print(colorize(line, "dim"))
    elif single_item and not header_showed_plan:
        # No matching steps — show the full plan as context
        print(colorize("\n  Steps:", "dim"))
        for idx, step in enumerate(steps, 1):
            print(colorize(f"    {idx}. {_step_text(step)}", "dim"))


def _render_issue_metadata(item: dict, detail: dict) -> None:
    file_val = item.get("file", "")
    if detail.get("route"):
        print(f"  Route: {detail['route']}")
        if detail.get("persona"):
            print(f"  Persona: {detail['persona']}")
        if detail.get("scenario"):
            print(f"  Scenario: {detail['scenario']}")
    elif file_val and file_val != ".":
        print(f"  File: {file_val}")
    print(colorize(f"  ID:   {item.get('id', '')}", "dim"))

    lines = detail.get("lines")
    if lines:
        print(f"  Lines: {', '.join(str(line_no) for line_no in lines[:8])}")
    for label, value in (
        ("Category", detail.get("category")),
        ("Active importers", detail.get("importers")),
    ):
        if value:
            print(f"  {label}: {value}")
    suggestion = detail.get("suggestion")
    if suggestion:
        print(colorize(f"\n  Suggestion: {suggestion}", "dim"))


def _render_issue_snippet(item: dict, detail: dict) -> None:
    target_line = detail.get("line") or (detail.get("lines", [None]) or [None])[0]
    file_path = item.get("file")
    if not target_line or file_path in (".", ""):
        return
    snippet = read_code_snippet(file_path, target_line)
    if not snippet:
        return
    print(colorize("\n  Code:", "dim"))
    print(snippet)


def _render_issue_detail(
    item: dict, *, single_item: bool = False, header_showed_plan: bool = False,
) -> dict:
    """Render plan overrides, file info, and detail fields. Returns parsed detail dict."""
    plan_description = item.get("plan_description")
    if plan_description:
        print(colorize(f"  → {plan_description}", "cyan"))

    _render_plan_cluster_detail(
        item,
        single_item=single_item,
        header_showed_plan=header_showed_plan,
    )

    plan_note = item.get("plan_note")
    if plan_note:
        print(colorize(f"  Note: {plan_note}", "dim"))

    detail = _normalize_issue_detail(item.get("detail", {}))
    _render_issue_metadata(item, detail)
    _render_issue_snippet(item, detail)

    return detail


def _render_score_impact(
    item: dict, dim_scores: dict, potentials: dict | None,
) -> None:
    _render_score_impact_impl(
        item,
        dim_scores,
        potentials,
        colorize_fn=colorize,
        log_fn=log,
        compute_health_breakdown_fn=compute_health_breakdown,
        compute_score_impact_fn=compute_score_impact,
        get_dimension_for_detector_fn=get_dimension_for_detector,
    )


_KIND_RENDERERS = {
    "cluster": _render_cluster_item,
    "workflow_stage": _render_workflow_stage,
    "workflow_action": _render_workflow_action,
}


def _render_item_type(item: dict) -> None:
    if is_review_finding(item):
        print(colorize("  Type: Design review (requires judgment)", "dim"))
        return
    if is_assessment_request(item):
        print(colorize("  Type: Assessment request", "dim"))
        return
    if is_auto_fix_item(item):
        print(colorize("  Type: Auto-fixable", "dim"))


def _render_auto_fix_batch_hint(item: dict, issues_scoped: dict) -> None:
    auto_fix_command = item.get("primary_command")
    if not is_auto_fix_item(item) or not is_auto_fix_command(auto_fix_command):
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
    _render_item_explain_impl(
        item,
        detail,
        confidence,
        dim_scores,
        colorize_fn=colorize,
        get_dimension_for_detector_fn=get_dimension_for_detector,
    )


def _render_item(
    item: dict, dim_scores: dict, issues_scoped: dict, explain: bool,
    potentials: dict | None = None,
    single_item: bool = False,
    header_showed_plan: bool = False,
) -> None:
    # Kind-specific items that bypass the standard issue card
    kind = item.get("kind")
    kind_renderer = _KIND_RENDERERS.get(kind)
    if kind_renderer is not None:
        kind_renderer(item)
        return
    if item.get("kind", "issue") == "subjective_dimension":
        _render_subjective_dimension(item, explain=explain)
        return

    # Standard issue header
    confidence = item.get("confidence", "medium")
    print(colorize(f"  ({confidence} confidence)", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")
    _render_item_type(item)

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


def _render_cluster_drill_header(
    *,
    items: list[dict],
    plan: dict,
    cluster_name: str,
) -> bool:
    clusters = plan.get("clusters", {})
    cluster_data = clusters.get(cluster_name, {})
    total = len(cluster_data.get("issue_ids", []))
    desc = cluster_data.get("description") or ""
    print(colorize(f"\n  ┌─ Cluster: {cluster_name} ({len(items)} of {total} remaining) ─┐", "cyan"))
    if desc:
        print(colorize(f"  │ {desc}", "cyan"))
    steps = cluster_data.get("action_steps") or []
    if steps:
        print(colorize("  │", "cyan"))
        print(colorize("  │ Steps:", "cyan"))
        for idx, step in enumerate(steps, 1):
            done = isinstance(step, dict) and step.get("done", False)
            marker = "[x]" if done else "[ ]"
            print(colorize(f"  │   {idx}. {marker} {_step_text(step)}", "cyan"))
    print(colorize("  └" + "─" * 60 + "┘", "cyan"))
    print(colorize("  Back to full queue: desloppify next", "dim"))
    if steps:
        print(colorize(f"  Step detail: desloppify plan cluster show {cluster_name}", "dim"))
        print(colorize(f"  Mark step done: desloppify plan cluster update {cluster_name} --done-step N", "dim"))
    return bool(steps)


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
    header_showed_plan = False
    effective_cluster = cluster_filter or (plan and plan.get("active_cluster"))
    if effective_cluster and plan:
        header_showed_plan = _render_cluster_drill_header(
            items=items,
            plan=plan,
            cluster_name=effective_cluster,
        )

    if group != "item":
        _render_grouped(items, group)
        return

    is_cluster_drill = len(items) > 1 and bool(effective_cluster)

    for idx, item in enumerate(items):
        if idx > 0:
            print()
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
