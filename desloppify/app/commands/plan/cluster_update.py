"""Cluster update command handler with dependency-injected side effects."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

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

from .cluster_steps import print_step


LoadPlanFn = Callable[[], dict]
SavePlanFn = Callable[[dict], None]
AppendLogFn = Callable[..., None]
PlanLockFn = Callable[[], object]
ParseStepsFn = Callable[[str], list]
NormalizeStepFn = Callable[[str | dict], dict]
StepSummaryFn = Callable[[str | dict], str]
UtcNowFn = Callable[[], str]
ColorizeFn = Callable[[str, str], str]


def cmd_cluster_update(
    args: argparse.Namespace,
    *,
    load_plan_fn: LoadPlanFn = load_plan,
    save_plan_fn: SavePlanFn = save_plan,
    append_log_entry_fn: AppendLogFn = append_log_entry,
    plan_lock_fn: PlanLockFn = plan_lock,
    parse_steps_file_fn: ParseStepsFn = parse_steps_file,
    normalize_step_fn: NormalizeStepFn = normalize_step,
    step_summary_fn: StepSummaryFn = step_summary,
    utc_now_fn: UtcNowFn = utc_now,
    colorize_fn: ColorizeFn = colorize,
) -> None:
    """Update cluster description, steps, and/or priority."""
    cluster_name: str = getattr(args, "cluster_name", "")
    description: str | None = getattr(args, "description", None)
    steps: list[str] | None = getattr(args, "steps", None)
    steps_file: str | None = getattr(args, "steps_file", None)
    add_step: str | None = getattr(args, "add_step", None)
    detail: str | None = getattr(args, "detail", None)
    update_step: int | None = getattr(args, "update_step", None)
    remove_step: int | None = getattr(args, "remove_step", None)
    done_step: int | None = getattr(args, "done_step", None)
    undone_step: int | None = getattr(args, "undone_step", None)
    priority: int | None = getattr(args, "priority", None)
    effort: str | None = getattr(args, "effort", None)
    depends_on: list[str] | None = getattr(args, "depends_on", None)
    issue_refs: list[str] | None = getattr(args, "issue_refs", None)

    has_update = any(
        x is not None
        for x in [
            description,
            steps,
            steps_file,
            add_step,
            update_step,
            remove_step,
            done_step,
            undone_step,
            priority,
            effort,
            depends_on,
            issue_refs,
        ]
    )
    if not has_update:
        print(
            colorize_fn(
                "  Nothing to update. Use --description, --steps, --steps-file, --add-step, --priority, etc.",
                "yellow",
            )
        )
        return

    with plan_lock_fn():
        _run_cluster_update_locked(
            cluster_name=cluster_name,
            description=description,
            steps=steps,
            steps_file=steps_file,
            add_step=add_step,
            detail=detail,
            update_step=update_step,
            remove_step=remove_step,
            done_step=done_step,
            undone_step=undone_step,
            priority=priority,
            effort=effort,
            depends_on=depends_on,
            issue_refs=issue_refs,
            load_plan_fn=load_plan_fn,
            save_plan_fn=save_plan_fn,
            append_log_entry_fn=append_log_entry_fn,
            parse_steps_file_fn=parse_steps_file_fn,
            normalize_step_fn=normalize_step_fn,
            step_summary_fn=step_summary_fn,
            utc_now_fn=utc_now_fn,
            colorize_fn=colorize_fn,
        )


def _run_cluster_update_locked(
    *,
    cluster_name: str,
    description: str | None,
    steps: list[str] | None,
    steps_file: str | None,
    add_step: str | None,
    detail: str | None,
    update_step: int | None,
    remove_step: int | None,
    done_step: int | None,
    undone_step: int | None,
    priority: int | None,
    effort: str | None,
    depends_on: list[str] | None,
    issue_refs: list[str] | None,
    load_plan_fn: LoadPlanFn,
    save_plan_fn: SavePlanFn,
    append_log_entry_fn: AppendLogFn,
    parse_steps_file_fn: ParseStepsFn,
    normalize_step_fn: NormalizeStepFn,
    step_summary_fn: StepSummaryFn,
    utc_now_fn: UtcNowFn,
    colorize_fn: ColorizeFn,
) -> None:
    """Inner body of cluster update, called under a plan lock."""
    plan = load_plan_fn()
    cluster = plan.get("clusters", {}).get(cluster_name)
    if cluster is None:
        print(colorize_fn(f"  Cluster {cluster_name!r} does not exist.", "red"))
        return

    if description is not None:
        cluster["description"] = description

    if priority is not None:
        cluster["priority"] = priority
        print(colorize_fn(f"  Priority set to {priority}.", "dim"))

    if depends_on is not None:
        all_clusters = set(plan.get("clusters", {}).keys())
        bad = [name for name in depends_on if name not in all_clusters]
        if bad:
            print(colorize_fn(f"  Unknown cluster(s): {', '.join(bad)}", "red"))
            return
        cluster["depends_on_clusters"] = depends_on
        print(colorize_fn(f"  Dependencies set: {', '.join(depends_on)}", "dim"))

    if steps_file is not None:
        path = Path(steps_file)
        if not path.is_file():
            print(colorize_fn(f"  Steps file not found: {steps_file}", "red"))
            return
        parsed = parse_steps_file_fn(path.read_text())
        cluster["action_steps"] = parsed
        print(colorize_fn(f"  Loaded {len(parsed)} step(s) from {steps_file}.", "dim"))
    elif steps is not None:
        cluster["action_steps"] = [normalize_step_fn(step) for step in steps]
        print(colorize_fn(f"  Stored {len(steps)} action step(s).", "dim"))

    current_steps: list = cluster.get("action_steps") or []

    max_step_title = 150

    if add_step is not None:
        new_step: dict = {"title": add_step}
        if detail is not None:
            new_step["detail"] = detail
        if effort is not None:
            new_step["effort"] = effort
        if issue_refs is not None:
            new_step["issue_refs"] = issue_refs
        if len(add_step) > max_step_title:
            print(
                colorize_fn(
                    f"  Warning: step title is {len(add_step)} chars (recommended max {max_step_title}).",
                    "yellow",
                )
            )
            print(colorize_fn("  Move implementation detail to --detail instead.", "dim"))
        current_steps.append(new_step)
        cluster["action_steps"] = current_steps
        print(colorize_fn(f"  Added step {len(current_steps)}: {add_step}", "dim"))

    if update_step is not None:
        idx = update_step - 1
        if idx < 0 or idx >= len(current_steps):
            print(colorize_fn(f"  Step {update_step} out of range (1-{len(current_steps)}).", "red"))
            return
        old = current_steps[idx]
        if isinstance(old, str):
            old = {"title": old}
        if add_step is None:
            if detail is not None:
                old["detail"] = detail
        else:
            old["title"] = add_step
            if detail is not None:
                old["detail"] = detail
            if len(add_step) > max_step_title:
                print(
                    colorize_fn(
                        f"  Warning: step title is {len(add_step)} chars (recommended max {max_step_title}).",
                        "yellow",
                    )
                )
                print(colorize_fn("  Move implementation detail to --detail instead.", "dim"))
        if effort is not None:
            old["effort"] = effort
        if issue_refs is not None:
            old["issue_refs"] = issue_refs
        current_steps[idx] = old
        cluster["action_steps"] = current_steps
        print(colorize_fn(f"  Updated step {update_step}.", "dim"))

    if remove_step is not None:
        idx = remove_step - 1
        if idx < 0 or idx >= len(current_steps):
            print(colorize_fn(f"  Step {remove_step} out of range (1-{len(current_steps)}).", "red"))
            return
        removed = current_steps.pop(idx)
        cluster["action_steps"] = current_steps
        title = step_summary_fn(removed)
        print(colorize_fn(f"  Removed step {remove_step}: {title}", "dim"))

    if done_step is not None:
        idx = done_step - 1
        if idx < 0 or idx >= len(current_steps):
            print(colorize_fn(f"  Step {done_step} out of range (1-{len(current_steps)}).", "red"))
            return
        step = current_steps[idx]
        if isinstance(step, str):
            step = {"title": step}
            current_steps[idx] = step
        step["done"] = True
        cluster["action_steps"] = current_steps
        print(colorize_fn(f"  Marked step {done_step} as done: {step.get('title', '')}", "dim"))

    if undone_step is not None:
        idx = undone_step - 1
        if idx < 0 or idx >= len(current_steps):
            print(colorize_fn(f"  Step {undone_step} out of range (1-{len(current_steps)}).", "red"))
            return
        step = current_steps[idx]
        if isinstance(step, str):
            step = {"title": step}
            current_steps[idx] = step
        step["done"] = False
        cluster["action_steps"] = current_steps
        print(colorize_fn(f"  Marked step {undone_step} as not done: {step.get('title', '')}", "dim"))

    final_steps = cluster.get("action_steps") or []
    if final_steps and any(
        x is not None
        for x in [steps, steps_file, add_step, update_step, remove_step, done_step, undone_step]
    ):
        print()
        print(colorize_fn(f"  Current steps ({len(final_steps)}):", "dim"))
        for i, step in enumerate(final_steps, 1):
            print_step(i, step, colorize_fn=colorize_fn)

    cluster["user_modified"] = True
    cluster["updated_at"] = utc_now_fn()
    append_log_entry_fn(
        plan,
        "cluster_update",
        cluster_name=cluster_name,
        actor="user",
        detail={"description": description},
    )
    save_plan_fn(plan)
    print(colorize_fn(f"  Updated cluster: {cluster_name}", "green"))


__all__ = ["cmd_cluster_update"]
