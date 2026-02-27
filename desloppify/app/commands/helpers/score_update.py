"""Centralized score update display for all state-changing commands."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.app.commands.scan.scan_helpers import format_delta
from desloppify.core.output_api import colorize


def print_score_update(
    state: dict,
    prev: state_mod.ScoreSnapshot,
    *,
    config: dict | None = None,
    label: str = "Scores",
) -> None:
    """Print score quartet with deltas and strict target progress.

    Args:
        state: Current state dict (scores already recomputed by save_state).
        prev: ScoreSnapshot taken before the operation.
        config: Project config dict (loaded from disk if not provided).
        label: Prefix label (default "Scores").
    """
    new = state_mod.score_snapshot(state)
    if (
        new.overall is None
        or new.objective is None
        or new.strict is None
        or new.verified is None
    ):
        print(colorize(f"\n  {label} unavailable — run `desloppify scan`.", "yellow"))
        return

    overall_s, overall_c = format_delta(new.overall, prev.overall)
    objective_s, objective_c = format_delta(new.objective, prev.objective)
    strict_s, strict_c = format_delta(new.strict, prev.strict)
    verified_s, verified_c = format_delta(new.verified, prev.verified)

    print(
        f"\n  {label}: "
        + colorize(f"overall {new.overall:.1f}/100{overall_s}", overall_c)
        + colorize(f"  objective {new.objective:.1f}/100{objective_s}", objective_c)
        + colorize(f"  strict {new.strict:.1f}/100{strict_s}", strict_c)
        + colorize(f"  verified {new.verified:.1f}/100{verified_s}", verified_c)
    )

    # Always show strict target + next-command nudge
    if config is None:
        from desloppify.core import config as config_mod

        config = config_mod.load_config()
    from desloppify.app.commands.helpers.score import target_strict_score_from_config

    target = target_strict_score_from_config(config, fallback=95.0)
    _print_strict_target_nudge(new.strict, target)


def _print_strict_target_nudge(
    strict: float, target: float, *, show_next: bool = True,
) -> None:
    """Print a one-liner with strict→target and optional next-command nudge."""
    gap = round(target - strict, 1)
    if gap > 0:
        suffix = " — run `desloppify next` to find the next improvement" if show_next else ""
        print(colorize(f"  Strict {strict:.1f} (target: {target:.1f}){suffix}", "dim"))
    else:
        print(colorize(f"  Strict {strict:.1f} — target {target:.1f} reached!", "green"))


__all__ = ["print_score_update", "_print_strict_target_nudge"]
