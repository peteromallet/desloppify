"""Integrity and dimension-mapping helpers for subjective scan reporting."""

from __future__ import annotations

from desloppify import scoring as scoring_mod
from desloppify.app.commands.helpers.score import coerce_target_score
from desloppify.app.commands.scan.scan_reporting_subjective_common import (
    coerce_notice_count,
    coerce_str_keys,
    render_subjective_names,
    subjective_rerun_command,
)
from desloppify.intelligence.integrity import subjective as subjective_integrity_mod


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


__all__ = [
    "subjective_entries_for_dimension_keys",
    "subjective_integrity_followup",
    "subjective_integrity_notice_lines",
]
