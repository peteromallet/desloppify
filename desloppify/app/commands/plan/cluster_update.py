"""Cluster update command handler with dependency-injected side effects."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    append_log_entry,
    load_plan,
    normalize_step,
    parse_steps_file,
    plan_lock,
    save_plan,
    step_summary,
)
from desloppify.state import utc_now

from .cluster_update_flow import (
    AppendLogFn,
    ClusterUpdateServices,
    ColorizeFn,
    LoadPlanFn,
    NormalizeStepFn,
    ParseStepsFn,
    SavePlanFn,
    StepSummaryFn,
    UtcNowFn,
    build_request,
    print_no_update_warning,
    run_cluster_update_locked,
)


def cmd_cluster_update(
    args: argparse.Namespace,
    *,
    load_plan_fn: LoadPlanFn = load_plan,
    save_plan_fn: SavePlanFn = save_plan,
    append_log_entry_fn: AppendLogFn = append_log_entry,
    plan_lock_fn=plan_lock,
    parse_steps_file_fn: ParseStepsFn = parse_steps_file,
    normalize_step_fn: NormalizeStepFn = normalize_step,
    step_summary_fn: StepSummaryFn = step_summary,
    utc_now_fn: UtcNowFn = utc_now,
    colorize_fn: ColorizeFn = colorize,
) -> None:
    """Update cluster description, steps, and/or priority."""
    request = build_request(args)
    if not request.has_updates():
        print_no_update_warning(colorize_fn=colorize_fn)
        return

    services = ClusterUpdateServices(
        load_plan_fn=load_plan_fn,
        save_plan_fn=save_plan_fn,
        append_log_entry_fn=append_log_entry_fn,
        parse_steps_file_fn=parse_steps_file_fn,
        normalize_step_fn=normalize_step_fn,
        step_summary_fn=step_summary_fn,
        utc_now_fn=utc_now_fn,
        colorize_fn=colorize_fn,
    )

    with plan_lock_fn():
        run_cluster_update_locked(request, services=services)


__all__ = ["cmd_cluster_update"]
