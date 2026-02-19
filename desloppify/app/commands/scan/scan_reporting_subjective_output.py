"""Output-oriented helpers for subjective scan reporting."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.app.commands.helpers.score import coerce_target_score
from desloppify.app.commands.scan.scan_reporting_subjective_common import (
    SubjectiveFollowup,
    flatten_cli_keys,
    render_subjective_scores,
)
from desloppify.app.commands.scan.scan_reporting_subjective_integrity import (
    subjective_integrity_followup,
    subjective_integrity_notice_lines,
)
from desloppify.intelligence.integrity import review as subjective_review_integrity_mod


def _subjective_reset_command(state: dict) -> str:
    scan_path = state.get("scan_path")
    if not isinstance(scan_path, str) or not scan_path.strip():
        scan_path = "."
    return f"`desloppify scan --path {scan_path} --reset-subjective`"


def build_subjective_followup(
    state: dict,
    subjective_entries: list[dict],
    *,
    threshold: float = 95.0,
    max_quality_items: int = 3,
    max_integrity_items: int = 5,
) -> SubjectiveFollowup:
    threshold_value = coerce_target_score(threshold, fallback=95.0)
    threshold_label = f"{threshold_value:.1f}".rstrip("0").rstrip(".")
    low_assessed = sorted(
        [
            entry
            for entry in subjective_entries
            if not entry.get("placeholder")
            and float(entry.get("strict", entry.get("score", 100.0))) < threshold_value
        ],
        key=lambda entry: float(entry.get("strict", entry.get("score", 100.0))),
    )
    rendered = render_subjective_scores(low_assessed, max_items=max_quality_items)
    dim_keys = flatten_cli_keys(low_assessed, max_items=max_quality_items)
    command = (
        f"`desloppify review --prepare --dimensions {dim_keys}`"
        if dim_keys
        else "`desloppify review --prepare --holistic --refresh`"
    )
    integrity_notice = subjective_integrity_followup(
        state,
        subjective_entries,
        threshold=threshold_value,
        max_items=max_integrity_items,
    )
    integrity_lines = subjective_integrity_notice_lines(
        integrity_notice,
        fallback_target=threshold_value,
    )
    return SubjectiveFollowup(
        threshold=threshold_value,
        threshold_label=threshold_label,
        low_assessed=low_assessed,
        rendered=rendered,
        command=command,
        integrity_notice=integrity_notice,
        integrity_lines=integrity_lines,
    )


def show_subjective_paths(
    state: dict,
    dim_scores: dict,
    *,
    colorize_fn,
    scorecard_subjective_entries_fn,
    threshold: float = 95.0,
    target_strict_score: float | None = None,
) -> None:
    threshold_value = coerce_target_score(threshold, fallback=95.0)
    subjective_entries = scorecard_subjective_entries_fn(state, dim_scores=dim_scores)
    if not subjective_entries:
        return

    followup = build_subjective_followup(
        state,
        subjective_entries,
        threshold=threshold_value,
        max_quality_items=3,
        max_integrity_items=5,
    )
    unassessed = sorted(
        [entry for entry in subjective_entries if entry["placeholder"]],
        key=lambda item: item["name"].lower(),
    )
    low_assessed = followup.low_assessed

    scoped = state_mod.path_scoped_findings(
        state.get("findings", {}), state.get("scan_path")
    )
    coverage_total, reason_counts, holistic_reason_counts = (
        subjective_review_integrity_mod.subjective_review_open_breakdown(scoped)
    )
    holistic_total = sum(holistic_reason_counts.values())
    if (
        not unassessed
        and not low_assessed
        and coverage_total <= 0
        and not followup.integrity_notice
    ):
        return

    print(colorize_fn("  Subjective path:", "cyan"))
    print(
        colorize_fn(
            f"    Reset baseline from zero: {_subjective_reset_command(state)}",
            "dim",
        )
    )
    if target_strict_score is not None:
        strict_score = state_mod.get_strict_score(state)
        if strict_score is not None:
            gap = round(float(target_strict_score) - float(strict_score), 1)
            if gap > 0:
                print(
                    colorize_fn(
                        f"    North star: strict {strict_score:.1f}/100 → target {target_strict_score:.1f} (+{gap:.1f} needed)",
                        "yellow",
                    )
                )
            else:
                print(
                    colorize_fn(
                        f"    North star: strict {strict_score:.1f}/100 meets target {target_strict_score:.1f}",
                        "green",
                    )
                )

    if unassessed or holistic_total > 0:
        integrity_bits: list[str] = []
        if unassessed:
            integrity_bits.append("unassessed subjective dimensions")
        if holistic_total > 0:
            integrity_bits.append("holistic review stale/missing")
        integrity_label = " + ".join(integrity_bits)
        print(colorize_fn(f"    High-priority integrity gap: {integrity_label}", "yellow"))
        print(
            colorize_fn(
                "    Refresh baseline: `desloppify review --prepare --holistic --refresh`",
                "dim",
            )
        )
        print(
            colorize_fn(
                "    Then import and rescan: `desloppify review --import findings.json --holistic && desloppify scan`",
                "dim",
            )
        )

    if low_assessed:
        print(
            colorize_fn(
                f"    Quality below target (<{followup.threshold_label}%): {followup.rendered}",
                "yellow",
            )
        )
        print(
            colorize_fn(
                f"    Next command to improve subjective scores: {followup.command}",
                "dim",
            )
        )

    for style, message in followup.integrity_lines:
        print(colorize_fn(f"    {message}", style))

    if unassessed:
        rendered = ", ".join(entry["name"] for entry in unassessed[:3])
        if len(unassessed) > 3:
            rendered = f"{rendered}, +{len(unassessed) - 3} more"
        print(colorize_fn(f"    Unassessed (0% placeholder): {rendered}", "yellow"))
        print(
            colorize_fn(
                "    Start with holistic refresh, then tune specific dimensions.", "dim"
            )
        )

    if coverage_total > 0:
        detail = []
        if reason_counts.get("changed", 0) > 0:
            detail.append(f"{reason_counts['changed']} changed")
        if reason_counts.get("unreviewed", 0) > 0:
            detail.append(f"{reason_counts['unreviewed']} unreviewed")
        reason_text = ", ".join(detail) if detail else "stale/unreviewed"
        suffix = "file" if coverage_total == 1 else "files"
        print(
            colorize_fn(
                f"    Coverage debt: {coverage_total} {suffix} need review ({reason_text})",
                "yellow",
            )
        )
        if holistic_total > 0:
            print(
                colorize_fn(
                    f"    Includes {holistic_total} holistic stale/missing signal(s).",
                    "yellow",
                )
            )
        print(
            colorize_fn(
                "    Triage: `desloppify show subjective_review --status open`", "dim"
            )
        )

    print()


__all__ = [
    "build_subjective_followup",
    "show_subjective_paths",
]
