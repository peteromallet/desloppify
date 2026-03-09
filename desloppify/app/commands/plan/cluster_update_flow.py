"""Core flow for cluster update command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .cluster_steps import print_step

LoadPlanFn = Callable[[], dict]
SavePlanFn = Callable[[dict], None]
AppendLogFn = Callable[..., None]
ParseStepsFn = Callable[[str], list]
NormalizeStepFn = Callable[[str | dict], dict]
StepSummaryFn = Callable[[str | dict], str]
UtcNowFn = Callable[[], str]
ColorizeFn = Callable[[str, str], str]

_MAX_STEP_TITLE = 150


@dataclass(frozen=True)
class ClusterUpdateRequest:
    cluster_name: str
    description: str | None
    steps: list[str] | None
    steps_file: str | None
    add_step: str | None
    detail: str | None
    update_step: int | None
    remove_step: int | None
    done_step: int | None
    undone_step: int | None
    priority: int | None
    effort: str | None
    depends_on: list[str] | None
    issue_refs: list[str] | None

    def has_updates(self) -> bool:
        return any(
            value is not None
            for value in (
                self.description,
                self.steps,
                self.steps_file,
                self.add_step,
                self.update_step,
                self.remove_step,
                self.done_step,
                self.undone_step,
                self.priority,
                self.effort,
                self.depends_on,
                self.issue_refs,
            )
        )

    def mutates_steps(self) -> bool:
        return any(
            value is not None
            for value in (
                self.steps,
                self.steps_file,
                self.add_step,
                self.update_step,
                self.remove_step,
                self.done_step,
                self.undone_step,
            )
        )


@dataclass(frozen=True)
class ClusterUpdateServices:
    load_plan_fn: LoadPlanFn
    save_plan_fn: SavePlanFn
    append_log_entry_fn: AppendLogFn
    parse_steps_file_fn: ParseStepsFn
    normalize_step_fn: NormalizeStepFn
    step_summary_fn: StepSummaryFn
    utc_now_fn: UtcNowFn
    colorize_fn: ColorizeFn


def build_request(args) -> ClusterUpdateRequest:
    """Convert argparse namespace to typed request payload."""
    return ClusterUpdateRequest(
        cluster_name=str(getattr(args, "cluster_name", "")),
        description=getattr(args, "description", None),
        steps=getattr(args, "steps", None),
        steps_file=getattr(args, "steps_file", None),
        add_step=getattr(args, "add_step", None),
        detail=getattr(args, "detail", None),
        update_step=getattr(args, "update_step", None),
        remove_step=getattr(args, "remove_step", None),
        done_step=getattr(args, "done_step", None),
        undone_step=getattr(args, "undone_step", None),
        priority=getattr(args, "priority", None),
        effort=getattr(args, "effort", None),
        depends_on=getattr(args, "depends_on", None),
        issue_refs=getattr(args, "issue_refs", None),
    )


def print_no_update_warning(*, colorize_fn: ColorizeFn) -> None:
    print(
        colorize_fn(
            "  Nothing to update. Use --description, --steps, --steps-file, --add-step, --priority, etc.",
            "yellow",
        )
    )


def run_cluster_update_locked(
    request: ClusterUpdateRequest,
    *,
    services: ClusterUpdateServices,
) -> None:
    """Apply cluster updates while already holding the plan lock."""
    plan = services.load_plan_fn()
    cluster = plan.get("clusters", {}).get(request.cluster_name)
    if cluster is None:
        print(services.colorize_fn(f"  Cluster {request.cluster_name!r} does not exist.", "red"))
        return

    if not _apply_cluster_metadata(cluster=cluster, plan=plan, request=request, services=services):
        return
    if not _apply_step_source(cluster=cluster, request=request, services=services):
        return

    current_steps = cluster.get("action_steps") or []
    current_steps = _as_step_list(current_steps)

    if not _apply_step_mutations(current_steps=current_steps, request=request, services=services):
        return
    cluster["action_steps"] = current_steps

    _print_current_steps(cluster=cluster, request=request, colorize_fn=services.colorize_fn)
    _save_cluster_update(plan=plan, cluster_name=request.cluster_name, request=request, services=services)


def _apply_cluster_metadata(
    *,
    cluster: dict,
    plan: dict,
    request: ClusterUpdateRequest,
    services: ClusterUpdateServices,
) -> bool:
    if request.description is not None:
        cluster["description"] = request.description

    if request.priority is not None:
        cluster["priority"] = request.priority
        print(services.colorize_fn(f"  Priority set to {request.priority}.", "dim"))

    if request.depends_on is None:
        return True

    all_clusters = set(plan.get("clusters", {}).keys())
    bad = [name for name in request.depends_on if name not in all_clusters]
    if bad:
        print(services.colorize_fn(f"  Unknown cluster(s): {', '.join(bad)}", "red"))
        return False
    cluster["depends_on_clusters"] = request.depends_on
    print(services.colorize_fn(f"  Dependencies set: {', '.join(request.depends_on)}", "dim"))
    return True


def _apply_step_source(
    *,
    cluster: dict,
    request: ClusterUpdateRequest,
    services: ClusterUpdateServices,
) -> bool:
    if request.steps_file is not None:
        path = Path(request.steps_file)
        if not path.is_file():
            print(services.colorize_fn(f"  Steps file not found: {request.steps_file}", "red"))
            return False
        parsed = services.parse_steps_file_fn(path.read_text())
        cluster["action_steps"] = parsed
        print(services.colorize_fn(f"  Loaded {len(parsed)} step(s) from {request.steps_file}.", "dim"))
        return True

    if request.steps is not None:
        normalized_steps = [services.normalize_step_fn(step) for step in request.steps]
        cluster["action_steps"] = normalized_steps
        print(services.colorize_fn(f"  Stored {len(request.steps)} action step(s).", "dim"))
    return True


def _apply_step_mutations(
    *,
    current_steps: list[dict],
    request: ClusterUpdateRequest,
    services: ClusterUpdateServices,
) -> bool:
    if request.add_step is not None:
        _apply_add_step(current_steps=current_steps, request=request, colorize_fn=services.colorize_fn)

    if request.update_step is not None and not _apply_update_step(
        current_steps=current_steps,
        request=request,
        colorize_fn=services.colorize_fn,
    ):
        return False

    if request.remove_step is not None and not _apply_remove_step(
        current_steps=current_steps,
        step_summary_fn=services.step_summary_fn,
        step_number=request.remove_step,
        colorize_fn=services.colorize_fn,
    ):
        return False

    if request.done_step is not None and not _apply_done_toggle(
        current_steps=current_steps,
        step_number=request.done_step,
        done=True,
        colorize_fn=services.colorize_fn,
    ):
        return False

    if request.undone_step is not None and not _apply_done_toggle(
        current_steps=current_steps,
        step_number=request.undone_step,
        done=False,
        colorize_fn=services.colorize_fn,
    ):
        return False
    return True


def _apply_add_step(
    *,
    current_steps: list[dict],
    request: ClusterUpdateRequest,
    colorize_fn: ColorizeFn,
) -> None:
    title = str(request.add_step or "")
    new_step: dict[str, object] = {"title": title}
    if request.detail is not None:
        new_step["detail"] = request.detail
    if request.effort is not None:
        new_step["effort"] = request.effort
    if request.issue_refs is not None:
        new_step["issue_refs"] = request.issue_refs

    _warn_on_long_title(title=title, colorize_fn=colorize_fn)
    current_steps.append(new_step)
    print(colorize_fn(f"  Added step {len(current_steps)}: {title}", "dim"))


def _apply_update_step(
    *,
    current_steps: list[dict],
    request: ClusterUpdateRequest,
    colorize_fn: ColorizeFn,
) -> bool:
    step_number = int(request.update_step or 0)
    idx = step_number - 1
    if idx < 0 or idx >= len(current_steps):
        print(colorize_fn(f"  Step {step_number} out of range (1-{len(current_steps)}).", "red"))
        return False

    updated = dict(current_steps[idx])
    if request.add_step is not None:
        title = request.add_step
        updated["title"] = title
        _warn_on_long_title(title=title, colorize_fn=colorize_fn)
    if request.detail is not None:
        updated["detail"] = request.detail
    if request.effort is not None:
        updated["effort"] = request.effort
    if request.issue_refs is not None:
        updated["issue_refs"] = request.issue_refs
    current_steps[idx] = updated
    print(colorize_fn(f"  Updated step {step_number}.", "dim"))
    return True


def _apply_remove_step(
    *,
    current_steps: list[dict],
    step_summary_fn: StepSummaryFn,
    step_number: int,
    colorize_fn: ColorizeFn,
) -> bool:
    idx = step_number - 1
    if idx < 0 or idx >= len(current_steps):
        print(colorize_fn(f"  Step {step_number} out of range (1-{len(current_steps)}).", "red"))
        return False
    removed = current_steps.pop(idx)
    title = step_summary_fn(removed)
    print(colorize_fn(f"  Removed step {step_number}: {title}", "dim"))
    return True


def _apply_done_toggle(
    *,
    current_steps: list[dict],
    step_number: int,
    done: bool,
    colorize_fn: ColorizeFn,
) -> bool:
    idx = step_number - 1
    if idx < 0 or idx >= len(current_steps):
        print(colorize_fn(f"  Step {step_number} out of range (1-{len(current_steps)}).", "red"))
        return False
    step = dict(current_steps[idx])
    step["done"] = done
    current_steps[idx] = step
    state = "done" if done else "not done"
    print(colorize_fn(f"  Marked step {step_number} as {state}: {step.get('title', '')}", "dim"))
    return True


def _print_current_steps(
    *,
    cluster: dict,
    request: ClusterUpdateRequest,
    colorize_fn: ColorizeFn,
) -> None:
    final_steps = cluster.get("action_steps") or []
    if not final_steps or not request.mutates_steps():
        return
    print()
    print(colorize_fn(f"  Current steps ({len(final_steps)}):", "dim"))
    for i, step in enumerate(final_steps, 1):
        print_step(i, step, colorize_fn=colorize_fn)


def _save_cluster_update(
    *,
    plan: dict,
    cluster_name: str,
    request: ClusterUpdateRequest,
    services: ClusterUpdateServices,
) -> None:
    cluster = plan.get("clusters", {}).get(cluster_name, {})
    cluster["user_modified"] = True
    cluster["updated_at"] = services.utc_now_fn()
    services.append_log_entry_fn(
        plan,
        "cluster_update",
        cluster_name=cluster_name,
        actor="user",
        detail={"description": request.description},
    )
    services.save_plan_fn(plan)
    print(services.colorize_fn(f"  Updated cluster: {cluster_name}", "green"))


def _warn_on_long_title(*, title: str, colorize_fn: ColorizeFn) -> None:
    if len(title) <= _MAX_STEP_TITLE:
        return
    print(
        colorize_fn(
            f"  Warning: step title is {len(title)} chars (recommended max {_MAX_STEP_TITLE}).",
            "yellow",
        )
    )
    print(colorize_fn("  Move implementation detail to --detail instead.", "dim"))


def _as_step_list(raw_steps: list) -> list[dict]:
    normalized: list[dict] = []
    for step in raw_steps:
        if isinstance(step, str):
            normalized.append({"title": step})
        elif isinstance(step, dict):
            normalized.append(dict(step))
    return normalized


__all__ = [
    "AppendLogFn",
    "ClusterUpdateRequest",
    "ClusterUpdateServices",
    "ColorizeFn",
    "LoadPlanFn",
    "NormalizeStepFn",
    "ParseStepsFn",
    "SavePlanFn",
    "StepSummaryFn",
    "UtcNowFn",
    "build_request",
    "print_no_update_warning",
    "run_cluster_update_locked",
]
