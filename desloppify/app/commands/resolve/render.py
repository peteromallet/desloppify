"""Terminal rendering helpers for resolve command flows."""

from __future__ import annotations

import argparse

from desloppify import state as state_mod
from desloppify.utils import colorize


def _print_resolve_summary(*, status: str, all_resolved: list[str]) -> None:
    print(colorize(f"\nResolved {len(all_resolved)} finding(s) as {status}:", "green"))
    for fid in all_resolved[:20]:
        print(f"  {fid}")
    if len(all_resolved) > 20:
        print(f"  ... and {len(all_resolved) - 20} more")


def _print_wontfix_batch_warning(
    state: dict,
    *,
    status: str,
    resolved_count: int,
) -> None:
    if status != "wontfix" or resolved_count <= 10:
        return
    wontfix_count = sum(
        1 for finding in state["findings"].values() if finding["status"] == "wontfix"
    )
    actionable = sum(
        1
        for finding in state["findings"].values()
        if finding["status"]
        in ("open", "wontfix", "fixed", "auto_resolved", "false_positive")
    )
    wontfix_pct = round(wontfix_count / actionable * 100) if actionable else 0
    print(
        colorize(
            f"\n  ⚠ Wontfix debt is now {wontfix_count} findings ({wontfix_pct}% of actionable).",
            "yellow",
        )
    )
    print(
        colorize(
            '    The strict score reflects this. Run `desloppify show "*" --status wontfix` to review.',
            "dim",
        )
    )


def _delta_suffix(delta: float) -> str:
    if abs(delta) < 0.05:
        return ""
    return f" ({'+' if delta > 0 else ''}{delta:.1f})"


def _print_score_movement(
    *,
    status: str,
    prev_overall: float | None,
    prev_objective: float | None,
    prev_strict: float | None,
    prev_verified: float | None,
    state: dict,
) -> None:
    new_overall = state_mod.get_overall_score(state)
    new_objective = state_mod.get_objective_score(state)
    new_strict = state_mod.get_strict_score(state)
    new_verified = state_mod.get_verified_strict_score(state)
    if (
        new_overall is None
        or new_objective is None
        or new_strict is None
        or new_verified is None
    ):
        print(colorize("\n  Scores unavailable — run `desloppify scan`.", "yellow"))
        return

    overall_delta = new_overall - (prev_overall or 0)
    objective_delta = new_objective - (prev_objective or 0)
    strict_delta = new_strict - (prev_strict or 0)
    verified_delta = new_verified - (prev_verified or 0)
    print(
        f"\n  Scores: overall {new_overall:.1f}/100{_delta_suffix(overall_delta)}"
        + colorize(
            f"  objective {new_objective:.1f}/100{_delta_suffix(objective_delta)}",
            "dim",
        )
        + colorize(f"  strict {new_strict:.1f}/100{_delta_suffix(strict_delta)}", "dim")
        + colorize(
            f"  verified {new_verified:.1f}/100{_delta_suffix(verified_delta)}", "dim"
        )
    )
    if status == "fixed":
        print(
            colorize(
                "  Verified score updates after a scan confirms the finding disappeared.",
                "yellow",
            )
        )


def _print_subjective_reset_hint(
    *,
    args: argparse.Namespace,
    state: dict,
    all_resolved: list[str],
    prev_subjective_scores: dict[str, float],
    assessment_score_fn,
) -> None:
    has_review = any(
        state["findings"].get(fid, {}).get("detector") == "review"
        for fid in all_resolved
    )
    if (
        args.status != "fixed"
        or not has_review
        or not state.get("subjective_assessments")
    ):
        return

    reset_dims = sorted(
        dim
        for dim in {
            str(
                state["findings"].get(fid, {}).get("detail", {}).get("dimension", "")
            ).strip()
            for fid in all_resolved
            if state["findings"].get(fid, {}).get("detector") == "review"
        }
        if dim
        and prev_subjective_scores.get(dim, 0.0) > 0.0
        and assessment_score_fn((state.get("subjective_assessments") or {}).get(dim))
        <= 0.0
    )
    if not reset_dims:
        return

    shown = ", ".join(reset_dims[:3])
    if len(reset_dims) > 3:
        shown = f"{shown}, +{len(reset_dims) - 3} more"
    print(
        colorize(
            f"  Reset subjective score(s) to 0 pending re-review: {shown}", "yellow"
        )
    )
    print(
        colorize(
            "  Next subjective step: "
            + f"`desloppify review --prepare --dimensions {','.join(reset_dims)}`",
            "dim",
        )
    )


def _print_next_command(state: dict) -> str:
    remaining = sum(
        1
        for finding in state["findings"].values()
        if finding["status"] == "open" and finding.get("detector") == "review"
    )
    next_command = "desloppify scan"
    if remaining > 0:
        suffix = "s" if remaining != 1 else ""
        print(
            colorize(
                f"\n  {remaining} review finding{suffix} remaining — run `desloppify issues`",
                "dim",
            )
        )
        next_command = "desloppify issues"
    print(colorize(f"  Next command: `{next_command}`", "dim"))
    print()
    return next_command
