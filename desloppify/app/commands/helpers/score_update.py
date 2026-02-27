"""Centralized score update display for all state-changing commands."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.app.commands.scan.scan_helpers import _format_delta
from desloppify.app.commands.status_parts.strict_target import format_strict_target_progress
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
        config: Project config dict (needed for target_strict_score).
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

    overall_s, overall_c = _format_delta(new.overall, prev.overall)
    objective_s, objective_c = _format_delta(new.objective, prev.objective)
    strict_s, strict_c = _format_delta(new.strict, prev.strict)
    verified_s, verified_c = _format_delta(new.verified, prev.verified)

    print(
        f"\n  {label}: "
        + colorize(f"overall {new.overall:.1f}/100{overall_s}", overall_c)
        + colorize(f"  objective {new.objective:.1f}/100{objective_s}", objective_c)
        + colorize(f"  strict {new.strict:.1f}/100{strict_s}", strict_c)
        + colorize(f"  verified {new.verified:.1f}/100{verified_s}", verified_c)
    )

    # Show strict target progress when config is available
    if config is not None:
        from desloppify.intelligence import narrative as narrative_mod
        from desloppify.intelligence.narrative.core import NarrativeContext

        narrative = narrative_mod.compute_narrative(
            state, context=NarrativeContext(command="score_update"),
        )
        strict_target = narrative.get("strict_target")
        if strict_target:
            lines, _target, _gap = format_strict_target_progress(strict_target)
            for message, style in lines:
                print(colorize(message, style))


__all__ = ["print_score_update"]
