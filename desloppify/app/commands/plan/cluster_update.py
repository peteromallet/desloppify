"""Cluster update command handler."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_state import (
    load_plan,
    plan_lock,
    save_plan,
)
from desloppify.engine.plan_ops import (
    append_log_entry,
    normalize_step,
    parse_steps_file,
    step_summary,
)
from desloppify.state_io import utc_now

from .cluster_update_flow import (
    ClusterUpdateServices,
    build_request,
    print_no_update_warning,
    run_cluster_update_locked,
)


def cmd_cluster_update(
    args: argparse.Namespace,
    *,
    services: ClusterUpdateServices | None = None,
    plan_lock_fn=plan_lock,
) -> None:
    """Update cluster description, steps, and/or priority."""
    request = build_request(args)
    resolved_services = services or ClusterUpdateServices(
        load_plan_fn=load_plan,
        save_plan_fn=save_plan,
        append_log_entry_fn=append_log_entry,
        parse_steps_file_fn=parse_steps_file,
        normalize_step_fn=normalize_step,
        step_summary_fn=step_summary,
        utc_now_fn=utc_now,
        colorize_fn=colorize,
    )
    if not request.has_updates():
        print_no_update_warning(colorize_fn=resolved_services.colorize_fn)
        return

    with plan_lock_fn():
        run_cluster_update_locked(request, services=resolved_services)


__all__ = ["cmd_cluster_update"]
