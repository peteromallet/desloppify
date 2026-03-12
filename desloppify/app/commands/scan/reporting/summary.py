"""Score and diff summary output for scan command."""

from __future__ import annotations

import logging
from typing import Any

from desloppify import state as state_mod
from desloppify.app.commands.helpers.score_update import print_strict_target_nudge
from desloppify.app.commands.scan.helpers import format_delta
from desloppify.app.commands.scan.reporting.agent_context import is_agent_environment
from desloppify.app.commands.status.strict_target import (
    format_strict_target_progress,
)
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.base.output.terminal import colorize
from desloppify.engine._concerns.generators import generate_concerns
from desloppify.engine._state.schema import StateModel

logger = logging.getLogger(__name__)


def _consecutive_subjective_integrity_status(
    state: StateModel, status: str
) -> int:
    """Return consecutive trailing scans with the given subjective-integrity status."""
    history = state.get("scan_history", [])
    if not isinstance(history, list):
        return 0

    streak = 0
    for entry in reversed(history):
        if not isinstance(entry, dict):
            break
        integrity = entry.get("subjective_integrity")
        if not isinstance(integrity, dict):
            break
        if integrity.get("status") != status:
            break
        streak += 1
    return streak


def _show_score_reveal(
    state: StateModel,
    new: state_mod.ScoreSnapshot,
    *,
    target_strict: float | None = None,
) -> None:
    """Show before/after score comparison when a queue cycle just completed.

    This fires when the plan had ``plan_start_scores`` and the queue was empty
    at scan time (i.e. the reconcile block cleared plan_start_scores).  We detect
    this by checking the plan *before* the clear happened — since merge_scan_results
    clears it, we peek at the ``_last_score_reveal`` stash it leaves behind.
    """
    # scan_workflow stashes the old plan_start_scores on state as a transient
    # key when it clears them (queue empty).  Pop it here for the reveal.
    plan_start = state.pop("_plan_start_scores_for_reveal", None)
    if not isinstance(plan_start, dict) or not plan_start.get("strict"):
        return

    old_strict = float(plan_start["strict"])
    new_strict = float(new.strict or 0)
    delta = round(new_strict - old_strict, 1)
    delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if abs(delta) >= 0.05 else ""

    bar = "=" * 50
    print(colorize(f"  {bar}", "cyan"))
    print(colorize("  SCORE UPDATE — Queue cycle complete!", "bold"))
    print(colorize(f"  Plan-start: strict {old_strict:.1f}/100", "dim"))
    print(colorize(f"  Updated:    strict {new_strict:.1f}/100{delta_str}", "cyan"))
    if target_strict is not None:
        target_gap = round(target_strict - new_strict, 1)
        if target_gap > 0:
            print(colorize(f"  Target:     {target_strict:.1f} (+{target_gap:.1f} to go)", "dim"))
        else:
            print(colorize(f"  Target:     {target_strict:.1f} — reached!", "green"))
    print(colorize(f"  {bar}", "cyan"))


def show_diff_summary(diff: dict[str, Any]) -> None:
    """Print the +new / -resolved / reopened one-liner."""
    diff_parts = []
    if diff["new"]:
        diff_parts.append(colorize(f"+{diff['new']} new", "yellow"))
    if diff["auto_resolved"]:
        diff_parts.append(colorize(f"-{diff['auto_resolved']} resolved", "green"))
    if diff["reopened"]:
        diff_parts.append(colorize(f"↻{diff['reopened']} reopened", "red"))
    if diff_parts:
        print(f"  {' · '.join(diff_parts)}")
    else:
        print(colorize("  No changes since last scan", "dim"))
    if diff.get("suspect_detectors"):
        print(
            colorize(
                "  ⚠ Skipped auto-resolve for: "
                f"{', '.join(diff['suspect_detectors'])} (returned 0 — likely transient)",
                "yellow",
            )
        )


def _has_complete_scores(new: state_mod.ScoreSnapshot) -> bool:
    return not (
        new.overall is None
        or new.objective is None
        or new.strict is None
        or new.verified is None
    )


def _unscored_subjective_callout(state: StateModel) -> None:
    """Print a callout when subjective dimensions are unassessed, clarifying score composition."""
    dim_scores = state.get("dimension_scores", {})
    if not dim_scores:
        return

    total_subj, unscored_subj = _subjective_unscored_counts(dim_scores)
    if unscored_subj == 0 or total_subj == 0:
        return

    print(colorize(_unscored_subjective_message(dim_scores, total_subj, unscored_subj), "yellow"))


def _subjective_unscored_counts(dim_scores: dict[str, Any]) -> tuple[int, int]:
    total_subj = 0
    unscored_subj = 0
    for data in dim_scores.values():
        if not isinstance(data, dict):
            continue
        detectors = data.get("detectors", {})
        if "subjective_assessment" not in detectors:
            continue
        total_subj += 1
        meta = detectors.get("subjective_assessment", {})
        if isinstance(meta, dict) and meta.get("placeholder"):
            unscored_subj += 1
    return total_subj, unscored_subj


def _subjective_fraction_percent(dim_scores: dict[str, Any]) -> int:
    try:
        import desloppify.engine._scoring.results.core as scoring_mod

        breakdown = scoring_mod.compute_health_breakdown(dim_scores)
        return round(float(breakdown.get("subjective_fraction", 0.0) or 0.0) * 100)
    except (ImportError, TypeError, ValueError):
        return 0


def _unscored_subjective_message(
    dim_scores: dict[str, Any],
    total_subj: int,
    unscored_subj: int,
) -> str:
    if unscored_subj != total_subj:
        return (
            f"  ⚠ {unscored_subj} of {total_subj} subjective dimensions unassessed (scored as 0). "
            f"Strict score is lower than expected until these are reviewed."
        )

    subject_word = "dimensions" if unscored_subj != 1 else "dimension"
    verb = "are" if unscored_subj != 1 else "is"
    msg = (
        f"  ⚠ {unscored_subj} subjective {subject_word} {verb} unassessed (scored as 0). "
    )
    subj_pct = _subjective_fraction_percent(dim_scores)
    if subj_pct:
        msg += (
            f"The strict score currently reflects only mechanical detectors "
            f"({100 - subj_pct}% of score weight). "
        )
    return msg + "Run `desloppify review --prepare` to assess."


def _print_score_guide() -> None:
    print(colorize("  Score guide:", "dim"))
    print(colorize("    overall  = 25% mechanical + 75% subjective (lenient — ignores wontfix)", "dim"))
    print(colorize("    objective = mechanical detectors only (no subjective review)", "dim"))
    print(colorize("    strict   = like overall, but wontfix counts against you  <-- your north star", "dim"))
    print(colorize("    verified = strict, but only credits scan-verified fixes", "dim"))


def _print_subjective_integrity_warning(
    state: StateModel,
    integrity: dict[str, Any],
) -> None:
    status = integrity.get("status")
    matched_count = int(integrity.get("matched_count", 0) or 0)
    if status == "penalized":
        print(
            colorize(
                "  ⚠ Subjective integrity: "
                f"{matched_count} target-matched dimensions were reset to 0.0 "
                "(target-matched).",
                "red",
            )
        )
        print(
            colorize(
                "    Review with `.desloppify/review_packet_blind.json` to avoid score anchoring."
                " See docs/CLAUDE.md or docs/HERMES.md for the workflow.",
                "dim",
            )
        )
        streak = _consecutive_subjective_integrity_status(state, "penalized")
        if streak < 2:
            return
        print(
            colorize(
                "    Repeated penalty across scans. Use a blind, isolated reviewer "
                "and re-import before trusting subjective scores.",
                "yellow",
            )
        )
        return

    if status != "warn":
        return
    print(
        colorize(
            "  ⚠ Subjective integrity: "
            f"{matched_count} dimension matched the target "
            "(near target). Re-review recommended.",
            "yellow",
        )
    )
    streak = _consecutive_subjective_integrity_status(state, "warn")
    if streak < 2:
        return
    print(
        colorize(
            "    This warning has repeated. Prefer "
            "`desloppify review --prepare` and run a trusted review "
            "(see skill doc for options).",
            "yellow",
        )
    )


def _print_score_quartet(
    new: state_mod.ScoreSnapshot,
    prev_overall: float | None,
    prev_objective: float | None,
    prev_strict: float | None,
    prev_verified: float | None,
    non_comparable_reason: str | None,
) -> None:
    """Print the four-score comparison line with deltas."""
    overall_delta_str, overall_color = format_delta(new.overall, prev_overall)
    objective_delta_str, objective_color = format_delta(new.objective, prev_objective)
    strict_delta_str, strict_color = format_delta(new.strict, prev_strict)
    verified_delta_str, verified_color = format_delta(new.verified, prev_verified)
    print(
        "  Scores: "
        + colorize(f"overall {new.overall:.1f}/100{overall_delta_str}", overall_color)
        + colorize(
            f"  objective {new.objective:.1f}/100{objective_delta_str}",
            objective_color,
        )
        + colorize(f"  strict {new.strict:.1f}/100{strict_delta_str}", strict_color)
        + colorize(
            f"  verified {new.verified:.1f}/100{verified_delta_str}",
            verified_color,
        )
    )
    if isinstance(non_comparable_reason, str) and non_comparable_reason.strip():
        print(colorize(f"  Δ non-comparable: {non_comparable_reason.strip()}", "yellow"))


def _print_wontfix_gap(
    wontfix: int,
    gap: float,
) -> None:
    """Print a yellow warning when the overall-vs-strict gap is significant."""
    if gap >= 5 and wontfix >= 10:
        print(
            colorize(
                f"  ⚠ {gap:.1f}-point gap between overall and strict — "
                f"{wontfix} wontfix items represent hidden debt",
                "yellow",
            )
        )


def _print_score_legend(
    state: StateModel,
    gap: float,
) -> None:
    """Show the score guide on first scan, large gap, or agent environments."""
    scan_count = state.get("scan_count", 0)
    if scan_count <= 1 or gap > 10 or is_agent_environment():
        _print_score_guide()


def _print_integrity_warnings(state: StateModel) -> None:
    """Print subjective-integrity warnings when present."""
    integrity = state.get("subjective_integrity", {})
    if isinstance(integrity, dict):
        _print_subjective_integrity_warning(state, integrity)


def show_score_delta(
    state: StateModel,
    prev_overall: float | None,
    prev_objective: float | None,
    prev_strict: float | None,
    prev_verified: float | None = None,
    non_comparable_reason: str | None = None,
    *,
    target_strict: float | None = None,
) -> None:
    """Print the canonical score quartet with deltas."""
    stats = state["stats"]
    new = state_mod.score_snapshot(state)

    if not _has_complete_scores(new):
        print(
            colorize(
                "  Scores unavailable — run a full scan with language detectors enabled.",
                "yellow",
            )
        )
        return

    _show_score_reveal(state, new, target_strict=target_strict)

    _print_score_quartet(
        new, prev_overall, prev_objective, prev_strict, prev_verified,
        non_comparable_reason,
    )

    _unscored_subjective_callout(state)

    gap = (new.overall or 0) - (new.strict or 0)
    _print_wontfix_gap(stats.get("wontfix", 0), gap)
    _print_score_legend(state, gap)

    if target_strict is not None and new.strict is not None:
        print_strict_target_nudge(new.strict, target_strict, show_next=False)

    _print_integrity_warnings(state)


def show_concern_count(state: StateModel, lang_name: str | None = None) -> None:
    """Print concern count if any exist."""
    try:
        concerns = generate_concerns(state)
        if concerns:
            print(
                colorize(
                    f"  {len(concerns)} potential design concern{'s' if len(concerns) != 1 else ''}"
                    " (run `show concerns` to view)",
                    "cyan",
                )
            )
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        log_best_effort_failure(logger, "generate best-effort concern summary", exc)


def show_strict_target_progress(
    strict_target: dict[str, Any] | None,
) -> tuple[float | None, float | None]:
    """Print strict target progress lines and return (target, gap)."""
    lines, target, gap = format_strict_target_progress(strict_target)
    for message, style in lines:
        print(colorize(message, style))
    return target, gap


__all__ = ["show_concern_count", "show_diff_summary", "show_score_delta", "show_strict_target_progress"]
