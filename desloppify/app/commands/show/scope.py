"""Scope and queue helpers for show command selection."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.engine.work_queue_internal.core import (
    QueueBuildOptions,
    build_work_queue,
)
from desloppify.utils import colorize


def resolve_show_scope(args) -> tuple[bool, str | None, str, str | None]:
    """Resolve scope/pattern/status for a show invocation."""
    chronic = getattr(args, "chronic", False)
    pattern = args.pattern
    status_filter = "open" if chronic else getattr(args, "status", "open")
    if chronic:
        scope = pattern
        pattern = pattern or "<chronic>"
        return True, pattern, status_filter, scope
    if not pattern:
        print(
            colorize(
                "Pattern required (or use --chronic). Try: desloppify show --help",
                "yellow",
            )
        )
        return False, None, status_filter, ""
    return True, pattern, status_filter, pattern


def load_matches(
    state: dict,
    *,
    scope: str | None,
    status_filter: str,
    chronic: bool,
) -> list[dict]:
    """Load matching findings from the ranked queue."""
    queue = build_work_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            scan_path=state.get("scan_path"),
            scope=scope,
            status=status_filter,
            include_subjective=False,
            chronic=chronic,
            no_tier_fallback=True,
        ),
    )
    return [item for item in queue.get("items", []) if item.get("kind") == "finding"]


def resolve_noise(config: dict, matches: list[dict]):
    """Apply detector/global noise budget to show matches."""
    noise_budget, global_noise_budget, budget_warning = (
        state_mod.resolve_finding_noise_settings(config)
    )
    surfaced_matches, hidden_by_detector = state_mod.apply_finding_noise_budget(
        matches,
        budget=noise_budget,
        global_budget=global_noise_budget,
    )
    return (
        surfaced_matches,
        hidden_by_detector,
        noise_budget,
        global_noise_budget,
        budget_warning,
    )


__all__ = ["load_matches", "resolve_noise", "resolve_show_scope"]
