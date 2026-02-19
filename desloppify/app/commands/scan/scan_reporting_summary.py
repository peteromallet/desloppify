"""Score and diff summary output for scan command."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.app.commands.scan.scan_helpers import _format_delta
from desloppify.app.commands.status_parts.strict_target import (
    format_strict_target_progress,
)
from desloppify.utils import colorize


def _consecutive_subjective_integrity_status(state: dict, status: str) -> int:
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


def _show_diff_summary(diff: dict):
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


def _show_score_delta(
    state: dict,
    prev_overall: float | None,
    prev_objective: float | None,
    prev_strict: float | None,
    prev_verified: float | None = None,
    non_comparable_reason: str | None = None,
):
    """Print the canonical score trio with deltas."""
    stats = state["stats"]
    new_overall = state_mod.get_overall_score(state)
    new_objective = state_mod.get_objective_score(state)
    new_strict = state_mod.get_strict_score(state)
    new_verified = state_mod.get_verified_strict_score(state)

    wontfix = stats.get("wontfix", 0)
    wontfix_str = f" · {wontfix} wontfix" if wontfix else ""

    if (
        new_overall is None
        or new_objective is None
        or new_strict is None
        or new_verified is None
    ):
        print(
            colorize(
                "  Scores unavailable — run a full scan with language detectors enabled.",
                "yellow",
            )
        )
        return

    overall_delta_str, overall_color = _format_delta(new_overall, prev_overall)
    objective_delta_str, objective_color = _format_delta(new_objective, prev_objective)
    strict_delta_str, strict_color = _format_delta(new_strict, prev_strict)
    verified_delta_str, verified_color = _format_delta(new_verified, prev_verified)
    print(
        "  Scores: "
        + colorize(f"overall {new_overall:.1f}/100{overall_delta_str}", overall_color)
        + colorize(
            f"  objective {new_objective:.1f}/100{objective_delta_str}",
            objective_color,
        )
        + colorize(f"  strict {new_strict:.1f}/100{strict_delta_str}", strict_color)
        + colorize(
            f"  verified {new_verified:.1f}/100{verified_delta_str}",
            verified_color,
        )
        + colorize(
            f"  |  {stats['open']} open{wontfix_str} / {stats['total']} total",
            "dim",
        )
    )
    if isinstance(non_comparable_reason, str) and non_comparable_reason.strip():
        print(colorize(f"  Δ non-comparable: {non_comparable_reason.strip()}", "yellow"))
    # Surface wontfix debt gap prominently when significant
    gap = (new_overall or 0) - (new_strict or 0)
    if gap >= 5 and wontfix >= 10:
        print(
            colorize(
                f"  ⚠ {gap:.1f}-point gap between overall and strict — "
                f"{wontfix} wontfix items represent hidden debt",
                "yellow",
            )
        )

    integrity = state.get("subjective_integrity", {})
    if isinstance(integrity, dict):
        status = integrity.get("status")
        matched_count = int(integrity.get("matched_count", 0) or 0)
        target = integrity.get("target_score")
        if status == "penalized":
            print(
                colorize(
                    "  ⚠ Subjective integrity: "
                    f"{matched_count} target-matched dimensions were reset to 0.0 "
                    f"({'target ' + str(target) if target is not None else 'target threshold'}).",
                    "red",
                )
            )
            streak = _consecutive_subjective_integrity_status(state, "penalized")
            if streak >= 2:
                print(
                    colorize(
                        "    Repeated penalty across scans. Use a blind, isolated reviewer "
                        "on `.desloppify/review_packet_blind.json` and re-import before trusting subjective scores.",
                        "yellow",
                    )
                )
        elif status == "warn":
            print(
                colorize(
                    "  ⚠ Subjective integrity: "
                    f"{matched_count} dimension matched the target "
                    f"({'target ' + str(target) if target is not None else 'target threshold'}). Re-review recommended.",
                    "yellow",
                )
            )
            streak = _consecutive_subjective_integrity_status(state, "warn")
            if streak >= 2:
                print(
                    colorize(
                        "    This warning has repeated. Use `desloppify review --prepare --refresh` "
                        "and run a blind reviewer pass before import.",
                        "yellow",
                )
            )


def _show_strict_target_progress(strict_target: dict | None) -> tuple[float | None, float | None]:
    """Print strict target progress lines and return (target, gap)."""
    lines, target, gap = format_strict_target_progress(strict_target)
    for message, style in lines:
        print(colorize(message, style))
    return target, gap


__all__ = ["_show_diff_summary", "_show_score_delta", "_show_strict_target_progress"]
