"""Subjective scan reporting: common helpers, integrity checks, and output."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify import scoring as scoring_mod
from desloppify.app.commands.helpers.score import coerce_target_score
from desloppify.intelligence import integrity as subjective_integrity_mod

# ---------------------------------------------------------------------------
# Common helpers (formerly scan_reporting_subjective_common)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubjectiveFollowup:
    threshold: float
    threshold_label: str
    low_assessed: list[dict]
    rendered: str
    command: str
    integrity_notice: dict[str, object] | None
    integrity_lines: list[tuple[str, str]]


def flatten_cli_keys(items: list[dict], *, max_items: int = 3) -> str:
    """Flatten CLI keys across up to max_items subjective entries, preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items[:max_items]:
        for key in item.get("cli_keys", []):
            if key in seen:
                continue
            ordered.append(key)
            seen.add(key)
    return ",".join(ordered)


def render_subjective_scores(entries: list[dict], *, max_items: int = 3) -> str:
    return ", ".join(
        f"{entry.get('name', 'Subjective')} {float(entry.get('strict', entry.get('score', 100.0))):.1f}%"
        for entry in entries[:max_items]
    )


def render_subjective_names(entries: list[dict], *, max_names: int = 3) -> str:
    count = len(entries)
    names = ", ".join(
        str(entry.get("name", "Subjective")) for entry in entries[:max_names]
    )
    if count > max_names:
        names = f"{names}, +{count - max_names} more"
    return names


def coerce_notice_count(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def coerce_str_keys(value: object) -> list[str]:
    if not isinstance(value, list | tuple | set):
        return []
    return [key for key in value if isinstance(key, str) and key]


def subjective_rerun_command(
    items: list[dict],
    *,
    max_items: int = 5,
    refresh: bool = True,
    has_prior_review: bool | None = None,
) -> str:
    _ = refresh
    # If dimensions already have open review issues, route to the review queue
    # instead of prompting a blocked rerun.
    if any(
        int(entry.get("issues", 0) or 0) > 0
        for entry in items[:max_items]
        if isinstance(entry, dict)
    ):
        return "`desloppify show review --status open`"

    dim_keys = flatten_cli_keys(items, max_items=max_items)

    # If no evidence of prior runner usage, suggest --prepare first
    if has_prior_review is False:
        command_parts = ["desloppify", "review", "--prepare"]
        if dim_keys:
            command_parts.extend(["--dimensions", dim_keys])
        cmd = f"`{' '.join(command_parts)}`"
        return f"{cmd} (set up `--runner codex` for automated reviews)"

    command_parts = [
        "desloppify",
        "review",
        "--run-batches",
        "--runner",
        "codex",
        "--parallel",
        "--scan-after-import",
        "--force-review-rerun",
    ]
    if dim_keys:
        command_parts.extend(["--dimensions", dim_keys])
    return f"`{' '.join(command_parts)}`"


# ---------------------------------------------------------------------------
# Integrity and dimension-mapping helpers (formerly scan_reporting_subjective_integrity)
# ---------------------------------------------------------------------------


def _subjective_display_name_from_key(dimension_key: str) -> str:
    return scoring_mod.DISPLAY_NAMES.get(
        dimension_key, dimension_key.replace("_", " ").title()
    )


def subjective_entries_for_dimension_keys(
    dimension_keys: list[str], entries: list[dict]
) -> list[dict]:
    by_key: dict[str, dict] = {}
    for entry in entries:
        for key in entry.get("cli_keys", []):
            by_key.setdefault(str(key), entry)

    mapped: list[dict] = []
    for key in dimension_keys:
        if key in by_key:
            mapped.append(by_key[key])
            continue
        mapped.append(
            {
                "name": _subjective_display_name_from_key(key),
                "score": 0.0,
                "strict": 0.0,
                "issues": 0,
                "placeholder": False,
                "cli_keys": [key],
            }
        )
    return mapped


def subjective_integrity_followup(
    state: dict,
    subjective_entries: list[dict],
    *,
    threshold: float = 95.0,
    max_items: int = 5,
) -> dict[str, object] | None:
    threshold_value = coerce_target_score(threshold, fallback=95.0)
    raw_integrity_state = state.get("subjective_integrity")
    integrity_state: dict[str, object] = (
        raw_integrity_state if isinstance(raw_integrity_state, dict) else {}
    )
    status = str(integrity_state.get("status", "")).strip().lower()
    raw_target = integrity_state.get("target_score")
    target_display = coerce_target_score(raw_target, fallback=threshold_value)
    matched_keys = coerce_str_keys(integrity_state.get("matched_dimensions", []))
    reset_keys = coerce_str_keys(integrity_state.get("reset_dimensions", []))

    if status == "penalized" and reset_keys:
        reset_entries = subjective_entries_for_dimension_keys(
            reset_keys, subjective_entries
        )
        return {
            "status": "penalized",
            "count": len(reset_keys),
            "target": target_display,
            "entries": reset_entries,
            "rendered": render_subjective_names(reset_entries),
            "command": subjective_rerun_command(reset_entries, max_items=max_items),
        }

    if status == "warn" and matched_keys:
        matched_entries = subjective_entries_for_dimension_keys(
            matched_keys, subjective_entries
        )
        return {
            "status": "warn",
            "count": len(matched_keys),
            "target": target_display,
            "entries": matched_entries,
            "rendered": render_subjective_names(matched_entries),
            "command": subjective_rerun_command(matched_entries, max_items=max_items),
        }

    at_target = sorted(
        [
            entry
            for entry in subjective_entries
            if not entry.get("placeholder")
            and subjective_integrity_mod.matches_target_score(
                float(entry.get("strict", entry.get("score", 100.0))),
                threshold_value,
            )
        ],
        key=lambda entry: str(entry.get("name", "")).lower(),
    )
    if not at_target:
        return None

    return {
        "status": "at_target",
        "count": len(at_target),
        "target": threshold_value,
        "entries": at_target,
        "rendered": render_subjective_names(at_target),
        "command": subjective_rerun_command(at_target, max_items=max_items),
    }


def subjective_integrity_notice_lines(
    integrity_notice: dict[str, object] | None,
    *,
    fallback_target: float = 95.0,
) -> list[tuple[str, str]]:
    if not integrity_notice:
        return []

    status = str(integrity_notice.get("status", "")).strip().lower()
    count = coerce_notice_count(integrity_notice.get("count", 0))
    target_display = coerce_target_score(
        integrity_notice.get("target"),
        fallback=fallback_target,
    )
    rendered = str(integrity_notice.get("rendered", "subjective dimensions"))
    command = str(integrity_notice.get("command", ""))

    if status == "penalized":
        return [
            (
                "red",
                "WARNING: "
                f"{count} subjective dimensions matched target {target_display:.1f} "
                f"and were reset to 0.0 this scan: {rendered}.",
            ),
            (
                "yellow",
                "Anti-gaming safeguard applied. Re-review objectively and import fresh assessments.",
            ),
            ("dim", f"Rerun now: {command}"),
        ]

    if status == "warn":
        dimension_label = "dimension is" if count == 1 else "dimensions are"
        return [
            (
                "yellow",
                "WARNING: "
                f"{count} subjective {dimension_label} parked on target {target_display:.1f}. "
                "Re-run that review with evidence-first scoring before treating this score as final.",
            ),
            ("dim", f"Next step: {command}"),
        ]

    if status == "at_target":
        return [
            (
                "yellow",
                "WARNING: "
                f"{count} of your subjective scores matches the target score, indicating a high risk of gaming. "
                f"Can you rerun them by running {command} taking extra care to be objective.",
            ),
        ]

    return []


# ---------------------------------------------------------------------------
# Output-oriented helpers (formerly scan_reporting_subjective_output)
# ---------------------------------------------------------------------------


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
    command = subjective_rerun_command(
        low_assessed,
        max_items=max_quality_items,
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

    all_findings = state.get("findings", {})
    if not isinstance(all_findings, dict):
        all_findings = {}
    coverage_global, _reason_counts, _holistic_reasons = (
        subjective_integrity_mod.subjective_review_open_breakdown(all_findings)
    )

    stale_count = sum(1 for e in subjective_entries if e.get("stale"))
    if (
        not unassessed
        and not low_assessed
        and stale_count == 0
        and coverage_global <= 0
        and not followup.integrity_notice
    ):
        return

    # Integrity lines are always preserved (anti-gaming safeguard).
    for style, message in followup.integrity_lines:
        print(colorize_fn(f"    {message}", style))

    # Collapsed summary replacing verbose Subjective path section.
    parts: list[str] = []
    if low_assessed:
        parts.append(f"{len(low_assessed)} below target ({followup.threshold_label}%)")
    if unassessed:
        parts.append(f"{len(unassessed)} unassessed")
    if stale_count:
        parts.append(f"{stale_count} stale")
    if coverage_global > 0:
        parts.append(f"{coverage_global} files need review")

    if parts:
        print(colorize_fn(f"  Subjective: {', '.join(parts)}.", "cyan"))
        print(colorize_fn("  Run `desloppify show subjective` for details.", "dim"))

    print()


__all__ = [
    "SubjectiveFollowup",
    "build_subjective_followup",
    "coerce_notice_count",
    "coerce_str_keys",
    "flatten_cli_keys",
    "render_subjective_names",
    "render_subjective_scores",
    "show_subjective_paths",
    "subjective_entries_for_dimension_keys",
    "subjective_integrity_followup",
    "subjective_integrity_notice_lines",
    "subjective_rerun_command",
]
