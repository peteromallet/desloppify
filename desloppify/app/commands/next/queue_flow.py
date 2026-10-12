"""Queue build and rendering flow for the next command."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from desloppify.app.commands.helpers.guardrails import triage_guardrail_messages
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.base.config import target_strict_score_from_config
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.engine._state.filtering import path_scoped_issues
from desloppify.engine._work_queue.context import queue_context
from desloppify.engine._work_queue.core import QueueBuildOptions
from desloppify.engine._work_queue.plan_order import (
    collapse_clusters,
    filter_cluster_focus,
)
from desloppify.engine._work_queue.policy import explain_queue
from desloppify.engine._work_queue.snapshot import build_queue_snapshot
from desloppify.engine.plan_state import load_plan
from desloppify.engine.planning.queue_policy import (
    build_backlog_queue,
    build_execution_queue,
)
from desloppify.engine.planning.scorecard_projection import scorecard_dimensions_payload
from desloppify.intelligence.narrative.core import NarrativeContext, compute_narrative
from desloppify.state_scoring import score_snapshot

from . import output as next_output_mod
from . import render as next_render_mod
from . import render_nudges as next_nudges_mod
from .flow_helpers import merge_potentials_safe as _merge_potentials_safe
from .flow_helpers import plan_queue_context as _plan_queue_context
from .flow_helpers import resolve_cluster_focus as _resolve_cluster_focus
from .options import NextOptions
from .render_support import render_queue_header as _render_queue_header
from .render_support import show_empty_queue as _show_empty_queue


@dataclass(frozen=True, slots=True)
class QueueViewConfig:
    command_name: str
    show_plan_context: bool
    collapse_plan_clusters: bool
    show_execution_prompt: bool


@dataclass(frozen=True, slots=True)
class QueueRenderDeps:
    resolve_lang_fn: Callable[..., object] = resolve_lang
    load_plan_fn: Callable[..., dict] = load_plan
    build_work_queue_fn: Callable[..., dict] = build_execution_queue
    write_query_fn: Callable[..., None] = write_query


EXECUTION_QUEUE_VIEW = QueueViewConfig(
    command_name="next",
    show_plan_context=True,
    collapse_plan_clusters=True,
    show_execution_prompt=True,
)
BACKLOG_QUEUE_VIEW = QueueViewConfig(
    command_name="backlog",
    show_plan_context=False,
    collapse_plan_clusters=False,
    show_execution_prompt=False,
)


def _build_next_payload(
    *,
    queue: dict,
    items: list[dict],
    state: dict,
    narrative: dict,
    plan_data: dict | None,
    command_name: str = "next",
) -> dict:
    payload = next_output_mod.build_query_payload(
        queue, items, command=command_name, narrative=narrative, plan=plan_data
    )
    scores = score_snapshot(state)
    payload["overall_score"] = getattr(scores, "overall", state.get("overall_score"))
    payload["objective_score"] = getattr(
        scores, "objective", state.get("objective_score")
    )
    payload["strict_score"] = getattr(scores, "strict", state.get("strict_score"))
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
    *,
    command_name: str = "next",
) -> bool:
    if opts.output_file:
        if next_output_mod.write_output_file(
            opts.output_file,
            payload,
            len(items),
            safe_write_text_fn=safe_write_text,
            colorize_fn=colorize,
            label=f"{command_name} output",
        ):
            return True
        raise CommandError("Failed to write output file")

    return next_output_mod.emit_non_terminal_output(
        opts.output_format,
        payload,
        items,
        command=command_name,
    )


def _write_next_payload(
    *,
    queue: dict,
    items: list[dict],
    state: dict,
    narrative: dict,
    plan_data: dict | None,
    guardrail_warnings: list[str],
    write_query_fn,
    command_name: str,
    explain_snapshot=None,
    explain_plan: dict | None = None,
) -> dict:
    """Build and persist the payload for the current queue view."""
    payload = _build_next_payload(
        queue=queue,
        items=items,
        state=state,
        narrative=narrative,
        plan_data=plan_data,
        command_name=command_name,
    )
    if guardrail_warnings:
        payload["warnings"] = guardrail_warnings
    if explain_snapshot is not None:
        payload["queue_explanation"] = explain_queue(explain_snapshot, explain_plan)
    write_query_fn(payload)
    return payload


def _render_empty_queue_view(
    *,
    queue: dict,
    items: list[dict],
    state: dict,
    plan_for_queue: dict,
    plan_data: dict | None,
    ctx,
    target_strict: float,
    opts: NextOptions,
    effective_cluster: str | None,
    guardrail_warnings: list[str],
    write_query_fn,
    command_name: str,
    show_plan_context: bool,
    explain_snapshot=None,
) -> None:
    """Render and persist the empty queue state."""
    strict_score = score_snapshot(state).strict
    plan_start_strict = None
    breakdown = None
    if show_plan_context:
        plan_start_strict, breakdown = _plan_queue_context(
            state=state,
            plan_data=plan_for_queue,
            context=ctx,
        )
    _render_queue_header(queue, opts.explain, snapshot=explain_snapshot, plan=plan_for_queue)
    _show_empty_queue(
        queue,
        strict_score,
        plan_start_strict=plan_start_strict,
        target_strict=target_strict,
        scope=opts.scope,
        cluster=effective_cluster,
        status=opts.status,
        full_queue_total=breakdown.queue_total if breakdown else None,
    )
    _write_next_payload(
        queue=queue,
        items=items,
        state=state,
        narrative={},
        plan_data=plan_data,
        guardrail_warnings=guardrail_warnings,
        write_query_fn=write_query_fn,
        command_name=command_name,
        explain_snapshot=explain_snapshot,
        explain_plan=plan_for_queue,
    )


def _render_terminal_queue_view(
    *,
    queue: dict,
    items: list[dict],
    state: dict,
    opts: NextOptions,
    plan_for_queue: dict,
    plan_data: dict | None,
    effective_cluster: str | None,
    target_strict: float,
    ctx,
    show_plan_context: bool,
    show_execution_prompt: bool,
    explain_snapshot=None,
) -> None:
    """Render terminal output for a non-empty queue."""
    dim_scores = state.get("dimension_scores", {})
    issues_scoped = path_scoped_issues(
        (state.get("work_items") or state.get("issues", {})),
        state.get("scan_path"),
    )
    plan_start_strict = None
    breakdown = None
    if show_plan_context:
        plan_start_strict, breakdown = _plan_queue_context(
            state=state,
            plan_data=plan_for_queue,
            context=ctx,
        )
    queue_total = breakdown.queue_total if breakdown else 0

    _render_queue_header(queue, opts.explain, snapshot=explain_snapshot, plan=plan_for_queue)
    strict_score = score_snapshot(state).strict
    if _show_empty_queue(
        queue,
        strict_score,
        plan_start_strict=plan_start_strict,
        target_strict=target_strict,
    ):
        return

    potentials = _merge_potentials_safe(state.get("potentials", {}))
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
    if show_plan_context:
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

    if items and plan_data and show_execution_prompt:
        print_user_message(
            "Start working on the task above. When done:"
            " `desloppify plan resolve`. Full queue:"
            " `desloppify plan show`."
        )


def _plan_data_for_view(plan: dict, *, show_plan_context: bool) -> dict | None:
    if not show_plan_context:
        return None
    if plan.get("queue_order") or plan.get("overrides") or plan.get("clusters"):
        return plan
    return None


def _resolve_queue_items(
    *,
    state: dict,
    config: dict,
    opts: NextOptions,
    plan_for_queue: dict,
    target_strict: float,
    build_work_queue_fn,
) -> tuple[object, dict, list[dict], str | None]:
    ctx = queue_context(
        state,
        target_strict=target_strict,
        config=config,
        plan=plan_for_queue,
    )
    effective_cluster = _resolve_cluster_focus(
        plan_for_queue,
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
    return ctx, queue, queue.get("items", []), effective_cluster


def _apply_queue_view_transforms(
    *,
    items: list[dict],
    queue: dict,
    opts: NextOptions,
    plan_for_queue: dict,
    effective_cluster: str | None,
    collapse_plan_clusters: bool,
) -> list[dict]:
    visible = items
    if collapse_plan_clusters and effective_cluster and plan_for_queue:
        visible = filter_cluster_focus(visible, plan_for_queue, effective_cluster)
    elif (
        collapse_plan_clusters
        and plan_for_queue
        and not effective_cluster
        and not plan_for_queue.get("active_cluster")
    ):
        visible = collapse_clusters(visible, plan_for_queue)

    if opts.count:
        visible = visible[: opts.count]
        queue["items"] = visible
        queue["total"] = len(visible)
    return visible


def _render_non_empty_queue(
    *,
    args: argparse.Namespace,
    state: dict,
    items: list[dict],
    queue: dict,
    plan_data: dict | None,
    guardrail_warnings: list[str],
    write_query_fn,
    view: QueueViewConfig,
    opts: NextOptions,
    plan_for_queue: dict,
    effective_cluster: str | None,
    target_strict: float,
    ctx,
    resolve_lang_fn,
    explain_snapshot=None,
) -> None:
    lang = resolve_lang_fn(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command=view.command_name, plan=plan_data),
    )
    payload = _write_next_payload(
        queue=queue,
        items=items,
        state=state,
        narrative=narrative,
        plan_data=plan_data,
        guardrail_warnings=guardrail_warnings,
        write_query_fn=write_query_fn,
        command_name=view.command_name,
        explain_snapshot=explain_snapshot,
        explain_plan=plan_for_queue,
    )

    if _emit_requested_output(opts, payload, items, command_name=view.command_name):
        return

    _render_terminal_queue_view(
        queue=queue,
        items=items,
        state=state,
        opts=opts,
        plan_for_queue=plan_for_queue,
        plan_data=plan_data,
        effective_cluster=effective_cluster,
        target_strict=target_strict,
        ctx=ctx,
        show_plan_context=view.show_plan_context,
        show_execution_prompt=view.show_execution_prompt,
        explain_snapshot=explain_snapshot,
    )


def _build_and_render_queue_view(
    args: argparse.Namespace,
    state: dict,
    config: dict,
    *,
    deps: QueueRenderDeps,
    view: QueueViewConfig,
) -> None:
    """Build queue payload and render output for a queue surface."""
    opts = NextOptions.from_args(args)
    guardrail_warnings = triage_guardrail_messages(state=state)
    target_strict = target_strict_score_from_config(config)

    plan = deps.load_plan_fn()
    plan_for_queue = plan
    plan_data = _plan_data_for_view(plan, show_plan_context=view.show_plan_context)
    ctx, queue, items, effective_cluster = _resolve_queue_items(
        state=state,
        config=config,
        opts=opts,
        plan_for_queue=plan_for_queue,
        target_strict=target_strict,
        build_work_queue_fn=deps.build_work_queue_fn,
    )
    items = _apply_queue_view_transforms(
        items=items,
        queue=queue,
        opts=opts,
        plan_for_queue=plan_for_queue,
        effective_cluster=effective_cluster,
        collapse_plan_clusters=view.collapse_plan_clusters,
    )

    explain_snapshot = None
    if opts.explain:
        explain_snapshot = build_queue_snapshot(
            state,
            options=QueueBuildOptions(
                scope=opts.scope,
                status=opts.status,
                include_skipped=opts.include_skipped,
                context=ctx,
            ),
            target_strict=target_strict,
        )

    if not items:
        _render_empty_queue_view(
            queue=queue,
            items=items,
            state=state,
            plan_for_queue=plan_for_queue,
            plan_data=plan_data,
            ctx=ctx,
            target_strict=target_strict,
            opts=opts,
            effective_cluster=effective_cluster,
            guardrail_warnings=guardrail_warnings,
            write_query_fn=deps.write_query_fn,
            command_name=view.command_name,
            show_plan_context=view.show_plan_context,
            explain_snapshot=explain_snapshot,
        )
        return

    _render_non_empty_queue(
        args=args,
        state=state,
        items=items,
        queue=queue,
        plan_data=plan_data,
        guardrail_warnings=guardrail_warnings,
        write_query_fn=deps.write_query_fn,
        view=view,
        opts=opts,
        plan_for_queue=plan_for_queue,
        effective_cluster=effective_cluster,
        target_strict=target_strict,
        ctx=ctx,
        resolve_lang_fn=deps.resolve_lang_fn,
        explain_snapshot=explain_snapshot,
    )


def build_and_render_execution_queue(
    args: argparse.Namespace,
    state: dict,
    config: dict,
    *,
    deps: QueueRenderDeps | None = None,
) -> None:
    """Build queue payload and render output for `desloppify next`."""
    build_and_render_queue(
        args,
        state,
        config,
        view=EXECUTION_QUEUE_VIEW,
        deps=deps
        or QueueRenderDeps(
            build_work_queue_fn=build_execution_queue,
        ),
    )


def build_and_render_backlog_queue(
    args: argparse.Namespace,
    state: dict,
    config: dict,
    *,
    deps: QueueRenderDeps | None = None,
) -> None:
    """Build queue payload and render output for `desloppify backlog`."""
    build_and_render_queue(
        args,
        state,
        config,
        view=BACKLOG_QUEUE_VIEW,
        deps=deps
        or QueueRenderDeps(
            build_work_queue_fn=build_backlog_queue,
        ),
    )


def build_and_render_queue(
    args: argparse.Namespace,
    state: dict,
    config: dict,
    *,
    view: QueueViewConfig = EXECUTION_QUEUE_VIEW,
    deps: QueueRenderDeps | None = None,
) -> None:
    """Build queue payload and render output using one stable view contract."""
    _build_and_render_queue_view(
        args,
        state,
        config,
        deps=deps or QueueRenderDeps(build_work_queue_fn=build_execution_queue),
        view=view,
    )


__all__ = [
    "BACKLOG_QUEUE_VIEW",
    "EXECUTION_QUEUE_VIEW",
    "QueueRenderDeps",
    "QueueViewConfig",
    "build_and_render_backlog_queue",
    "build_and_render_execution_queue",
    "build_and_render_queue",
]
