"""Terminal rendering helpers for resolve command flows."""

from __future__ import annotations

import argparse

from desloppify import state as state_mod
from desloppify.app.commands.helpers.score_update import _print_strict_target_nudge
from desloppify.core.output_api import colorize


def _print_resolve_summary(*, status: str, all_resolved: list[str]) -> None:
    verb = "Reopened" if status == "open" else "Resolved"
    print(colorize(f"\n{verb} {len(all_resolved)} finding(s) as {status}:", "green"))
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


def _score_snapshot_or_warn(state: dict):
    snapshot = state_mod.score_snapshot(state)
    if (
        snapshot.overall is None
        or snapshot.objective is None
        or snapshot.strict is None
        or snapshot.verified is None
    ):
        print(colorize("\n  Scores unavailable — run `desloppify scan`.", "yellow"))
        return None
    return snapshot


def _print_strict_gap_note(status: str, *, overall: float, strict: float) -> None:
    if status != "wontfix":
        return
    strict_gap = round(overall - strict, 1)
    if strict_gap <= 0:
        return
    print(
        colorize(
            f"  Note: wontfix items still count against strict score. "
            f"Current gap: overall {overall:.1f} vs strict {strict:.1f} ({strict_gap:.1f} pts of hidden debt).",
            "yellow",
        )
    )


def _print_post_resolve_guidance(
    *,
    status: str,
    has_review_findings: bool,
    overall_delta: float,
) -> None:
    if has_review_findings and abs(overall_delta) < 0.05:
        print(
            colorize(
                "  Scores unchanged (review findings don't affect scores directly).",
                "yellow",
            )
        )
        print(
            colorize(
                "  Run `desloppify review --prepare` to get updated assessment scores.",
                "dim",
            )
        )
        return
    if status == "fixed":
        print(
            colorize(
                "  Verified score updates after a scan confirms the finding disappeared.",
                "yellow",
            )
        )


def _print_score_movement(
    *,
    status: str,
    prev_overall: float | None,
    prev_objective: float | None,
    prev_strict: float | None,
    prev_verified: float | None,
    state: dict,
    has_review_findings: bool = False,
    target_strict: float | None = None,
) -> None:
    new = _score_snapshot_or_warn(state)
    if new is None:
        return

    overall_delta = new.overall - (prev_overall or 0)
    objective_delta = new.objective - (prev_objective or 0)
    strict_delta = new.strict - (prev_strict or 0)
    verified_delta = new.verified - (prev_verified or 0)
    print(
        f"\n  Scores: overall {new.overall:.1f}/100{_delta_suffix(overall_delta)}"
        + colorize(
            f"  objective {new.objective:.1f}/100{_delta_suffix(objective_delta)}",
            "dim",
        )
        + colorize(f"  strict {new.strict:.1f}/100{_delta_suffix(strict_delta)}", "dim")
        + colorize(
            f"  verified {new.verified:.1f}/100{_delta_suffix(verified_delta)}", "dim"
        )
    )
    if target_strict is not None:
        _print_strict_target_nudge(new.strict, target_strict, show_next=False)
    _print_strict_gap_note(status, overall=new.overall, strict=new.strict)
    _print_post_resolve_guidance(
        status=status,
        has_review_findings=has_review_findings,
        overall_delta=overall_delta,
    )


def _print_subjective_reset_hint(
    *,
    args: argparse.Namespace,
    state: dict,
    all_resolved: list[str],
    prev_subjective_scores: dict[str, float],
) -> None:
    has_review = any(
        state["findings"].get(fid, {}).get("detector") == "review"
        for fid in all_resolved
    )
    if not has_review or not state.get("subjective_assessments"):
        return

    stale_dims = sorted(
        dim
        for dim in {
            str(
                state["findings"].get(fid, {}).get("detail", {}).get("dimension", "")
            ).strip()
            for fid in all_resolved
            if state["findings"].get(fid, {}).get("detector") == "review"
        }
        if dim and dim in (state.get("subjective_assessments") or {})
    )
    if not stale_dims:
        return

    shown = ", ".join(stale_dims[:3])
    if len(stale_dims) > 3:
        shown = f"{shown}, +{len(stale_dims) - 3} more"
    print(
        colorize(
            f"  Subjective scores unchanged — re-run review for updated scores: {shown}",
            "yellow",
        )
    )
    print(
        colorize(
            "  Next subjective step: "
            + (
                "`desloppify review --prepare --dimensions "
                f"{','.join(stale_dims)} --force-review-rerun`"
            ),
            "dim",
        )
    )


def _print_next_command(state: dict) -> str:
    remaining = sum(
        1
        for finding in state["findings"].values()
        if finding["status"] == "open"
        and not finding.get("suppressed")
    )
    next_command = "desloppify scan"
    if remaining > 0:
        suffix = "s" if remaining != 1 else ""
        print(
            colorize(
                f"\n  {remaining} finding{suffix} remaining — run `desloppify next`",
                "dim",
            )
        )
        next_command = "desloppify next"
    print(colorize(f"  Next command: `{next_command}`", "dim"))
    print()
    return next_command
