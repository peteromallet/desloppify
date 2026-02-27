"""Score and diff summary output for scan command."""

from __future__ import annotations

import logging

from desloppify import state as state_mod
from desloppify.app.commands.scan.scan_helpers import format_delta
from desloppify.app.commands.status_parts.strict_target import (
    format_strict_target_progress,
)
from desloppify.app.commands.scan.scan_reporting_llm import _is_agent_environment
from desloppify.core.output_api import colorize

logger = logging.getLogger(__name__)


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


def show_diff_summary(diff: dict):
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


def show_score_delta(
    state: dict,
    prev_overall: float | None,
    prev_objective: float | None,
    prev_strict: float | None,
    prev_verified: float | None = None,
    non_comparable_reason: str | None = None,
    *,
    target_strict: float | None = None,
):
    """Print the canonical score quartet with deltas."""
    stats = state["stats"]
    new = state_mod.score_snapshot(state)

    if (
        new.overall is None
        or new.objective is None
        or new.strict is None
        or new.verified is None
    ):
        print(
            colorize(
                "  Scores unavailable — run a full scan with language detectors enabled.",
                "yellow",
            )
        )
        return

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
    # Surface wontfix debt gap prominently when significant
    wontfix = stats.get("wontfix", 0)
    gap = (new.overall or 0) - (new.strict or 0)
    if gap >= 5 and wontfix >= 10:
        print(
            colorize(
                f"  ⚠ {gap:.1f}-point gap between overall and strict — "
                f"{wontfix} wontfix items represent hidden debt",
                "yellow",
            )
        )

    # Score legend — shown on first scan or when strict gap is significant
    scan_count = state.get("scan_count", 0)
    if scan_count <= 1 or gap > 10 or _is_agent_environment():
        print(colorize("  Score guide:", "dim"))
        print(colorize("    overall  = 40% mechanical + 60% subjective (lenient — ignores wontfix)", "dim"))
        print(colorize("    objective = mechanical detectors only (no subjective review)", "dim"))
        print(colorize("    strict   = like overall, but wontfix counts against you  <-- your north star", "dim"))
        print(colorize("    verified = strict, but only credits scan-verified fixes", "dim"))

    # Show strict target progress
    if target_strict is not None and new.strict is not None:
        from desloppify.app.commands.helpers.score_update import _print_strict_target_nudge

        _print_strict_target_nudge(new.strict, target_strict, show_next=False)

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
                        "    This warning has repeated. Prefer "
                        "`desloppify review --run-batches --runner codex --parallel --scan-after-import` "
                        "or run a blind reviewer pass before import.",
                        "yellow",
                )
            )


def show_concern_count(state: dict, lang_name: str | None = None) -> None:
    """Print concern count if any exist."""
    try:
        from desloppify.engine.concerns import generate_concerns

        concerns = generate_concerns(state, lang_name=lang_name)
        if concerns:
            print(
                colorize(
                    f"  {len(concerns)} potential design concern{'s' if len(concerns) != 1 else ''}"
                    " (run `show concerns` to view)",
                    "cyan",
                )
            )
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("Concern generation failed (best-effort): %s", exc)


def show_strict_target_progress(strict_target: dict | None) -> tuple[float | None, float | None]:
    """Print strict target progress lines and return (target, gap)."""
    lines, target, gap = format_strict_target_progress(strict_target)
    for message, style in lines:
        print(colorize(message, style))
    return target, gap


__all__ = ["show_concern_count", "show_diff_summary", "show_score_delta", "show_strict_target_progress"]
