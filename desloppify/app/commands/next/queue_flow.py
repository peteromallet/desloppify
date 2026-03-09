"""Queue build and rendering flow for the next command."""

from __future__ import annotations

import argparse

from desloppify import state as state_mod
from desloppify.app.commands.helpers.guardrails import triage_guardrail_messages
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.base.config import target_strict_score_from_config
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.core import QueueBuildOptions, build_work_queue
from desloppify.engine._work_queue.plan_order import (
    collapse_clusters,
    filter_cluster_focus,
)
from desloppify.engine.plan import load_plan
from desloppify.engine.planning.scorecard_projection import scorecard_dimensions_payload
from desloppify.intelligence.narrative.core import NarrativeContext, compute_narrative

from . import output as next_output_mod
from . import render as next_render_mod
from . import render_nudges as next_nudges_mod
from .flow_helpers import merge_potentials_safe as _merge_potentials_safe
from .flow_helpers import plan_queue_context as _plan_queue_context
from .flow_helpers import resolve_cluster_focus as _resolve_cluster_focus
from .options import NextOptions
from .render_support import render_queue_header as _render_queue_header
from .render_support import show_empty_queue as _show_empty_queue


def _build_next_payload(
    *,
    queue: dict,
    items: list[dict],
    state: dict,
    narrative: dict,
    plan_data: dict | None,
) -> dict:
    payload = next_output_mod.build_query_payload(
        queue, items, command="next", narrative=narrative, plan=plan_data
    )
    scores = state_mod.score_snapshot(state)
    payload["overall_score"] = scores.overall
    payload["objective_score"] = scores.objective
    payload["strict_score"] = scores.strict
    payload["scorecard_dimensions"] = scorecard_dimensions_payload(
        state,
        dim_scores=state.get("dimension_scores", {}),
    )
    payload["subjective_measures"] = [
        row for row in payload["scorecard_dimensions"] if row.get("subjective")
    ]
    return payload


def _emit_requested_output(
    opts: NextOptions,
    payload: dict,
    items: list[dict],
) -> bool:
    if opts.output_file:
        if next_output_mod.write_output_file(
            opts.output_file,
            payload,
            len(items),
            safe_write_text_fn=safe_write_text,
            colorize_fn=colorize,
        ):
            return True
        raise CommandError("Failed to write output file")

    return next_output_mod.emit_non_terminal_output(opts.output_format, payload, items)


def build_and_render_queue(
    args: argparse.Namespace,
    state: dict,
    config: dict,
    *,
    resolve_lang_fn=resolve_lang,
    load_plan_fn=load_plan,
    build_work_queue_fn=build_work_queue,
    write_query_fn=write_query,
) -> None:
    """Build queue payload and render output for `desloppify next`."""
    opts = NextOptions.from_args(args)

    # Triage guardrail: for terminal, print; for JSON, embed as warnings.
    guardrail_warnings = triage_guardrail_messages(state=state)

    target_strict = target_strict_score_from_config(config)

    plan = load_plan_fn()
    plan_data: dict | None = None
    if plan.get("queue_order") or plan.get("overrides") or plan.get("clusters"):
        plan_data = plan

    # Build a single queue context so policy and plan interpretation are aligned.
    ctx = queue_context(
        state,
        config=config,
        plan=plan_data,
        target_strict=target_strict,
    )

    effective_cluster = _resolve_cluster_focus(
        plan_data,
        cluster_arg=opts.cluster,
        scope=opts.scope,
    )

    queue = build_work_queue_fn(
        state,
        options=QueueBuildOptions(
            count=None,
            scope=opts.scope,
            status=opts.status,
            include_subjective=True,
            subjective_threshold=target_strict,
            explain=opts.explain,
            include_skipped=opts.include_skipped,
            context=ctx,
        ),
    )
    items = queue.get("items", [])

    if effective_cluster and plan_data:
        items = filter_cluster_focus(items, plan_data, effective_cluster)

    if plan_data and not effective_cluster and not plan_data.get("active_cluster"):
        items = collapse_clusters(items, plan_data)

    if opts.count:
        items = items[: opts.count]
        queue["items"] = items
        queue["total"] = len(items)

    if not items:
        strict_score = state_mod.score_snapshot(state).strict
        plan_start_strict = None
        if plan_data:
            plan_start_strict, _ = _plan_queue_context(
                state=state,
                plan_data=plan_data,
                context=ctx,
            )
        _render_queue_header(queue, opts.explain)
        _show_empty_queue(
            queue,
            strict_score,
            plan_start_strict=plan_start_strict,
            target_strict=target_strict,
        )
        payload = _build_next_payload(
            queue=queue,
            items=items,
            state=state,
            narrative={},
            plan_data=plan_data,
        )
        if guardrail_warnings:
            payload["warnings"] = guardrail_warnings
        write_query_fn(payload)
        return

    lang = resolve_lang_fn(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command="next", plan=plan_data),
    )

    payload = _build_next_payload(
        queue=queue,
        items=items,
        state=state,
        narrative=narrative,
        plan_data=plan_data,
    )
    if guardrail_warnings:
        payload["warnings"] = guardrail_warnings
    write_query_fn(payload)

    if _emit_requested_output(opts, payload, items):
        return

    dim_scores = state.get("dimension_scores", {})
    issues_scoped = state_mod.path_scoped_issues(
        state.get("issues", {}),
        state.get("scan_path"),
    )

    plan_start_strict, breakdown = _plan_queue_context(
        state=state,
        plan_data=plan_data,
        context=ctx,
    )
    queue_total = breakdown.queue_total if breakdown else 0

    _render_queue_header(queue, opts.explain)
    strict_score = state_mod.score_snapshot(state).strict
    if _show_empty_queue(
        queue,
        strict_score,
        plan_start_strict=plan_start_strict,
        target_strict=target_strict,
    ):
        return

    raw_potentials = state.get("potentials", {})
    potentials = _merge_potentials_safe(raw_potentials)
    next_render_mod.render_terminal_items(
        items,
        dim_scores,
        issues_scoped,
        group=opts.group,
        explain=opts.explain,
        potentials=potentials,
        plan=plan_data,
        cluster_filter=effective_cluster,
    )
    next_nudges_mod.render_single_item_resolution_hint(items)
    next_nudges_mod.render_uncommitted_reminder(plan_data)
    next_nudges_mod.render_followup_nudges(
        state,
        dim_scores,
        issues_scoped,
        strict_score=strict_score,
        target_strict_score=target_strict,
        queue_total=queue_total,
        plan_start_strict=plan_start_strict,
        breakdown=breakdown,
    )
    print()

    if items and plan_data:
        print_user_message(
            "Start working on the task above. When done:"
            " `desloppify plan resolve`. Full queue:"
            " `desloppify plan show`."
        )


__all__ = ["build_and_render_queue"]
