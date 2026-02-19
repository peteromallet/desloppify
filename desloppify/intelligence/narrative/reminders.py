"""Contextual reminders with decay."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime as _dt
from datetime import timezone as _tz

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.intelligence.narrative._constants import (
    _FEEDBACK_URL,
    _REMINDER_DECAY_THRESHOLD,
    STRUCTURAL_MERGE,
)

logger = logging.getLogger(__name__)


def _compute_fp_rates(findings: dict) -> dict[tuple[str, str], float]:
    """Compute false_positive rate per (detector, zone) from historical findings."""
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for finding in findings.values():
        detector = finding.get("detector", "unknown")
        if detector in STRUCTURAL_MERGE:
            detector = "structural"
        zone = finding.get("zone", "production")
        key = (detector, zone)
        if key not in counts:
            counts[key] = {"total": 0, "fp": 0}
        counts[key]["total"] += 1
        if finding.get("status") == "false_positive":
            counts[key]["fp"] += 1

    rates: dict[tuple[str, str], float] = {}
    for key, stat in counts.items():
        if stat["total"] >= 5 and stat["fp"] > 0:
            rates[key] = stat["fp"] / stat["total"]
    return rates


def _auto_fixer_reminder(actions: list[dict]) -> list[dict]:
    auto_fix_actions = [
        action for action in actions if action.get("type") == "auto_fix"
    ]
    if not auto_fix_actions:
        return []
    total = sum(action.get("count", 0) for action in auto_fix_actions)
    if total <= 0:
        return []
    first_cmd = auto_fix_actions[0].get("command", "desloppify fix <fixer> --dry-run")
    return [
        {
            "type": "auto_fixers_available",
            "message": f"{total} findings are auto-fixable. Run `{first_cmd}`.",
            "command": first_cmd,
        }
    ]


def _rescan_needed_reminder(command: str | None) -> list[dict]:
    if command not in {"fix", "resolve", "ignore"}:
        return []
    return [
        {
            "type": "rescan_needed",
            "message": "Rescan to verify — cascading effects may create new findings.",
            "command": "desloppify scan",
        }
    ]


def _badge_reminder(strict_score: float | None, badge: dict) -> list[dict]:
    eligible_for_badge = (
        strict_score is not None
        and strict_score >= 90
        and badge.get("generated")
        and not badge.get("in_readme")
    )
    if not eligible_for_badge:
        return []
    badge_path = str(badge.get("path") or "scorecard.png")
    return [
        {
            "type": "badge_recommendation",
            "message": (
                "Score is above 90! Add the scorecard to your README: "
                f'<img src="{badge_path}" width="100%">'
            ),
            "command": None,
        }
    ]


def _wontfix_debt_reminders(state: dict, debt: dict, command: str | None) -> list[dict]:
    reminders: list[dict] = []
    if debt.get("trend") == "growing":
        reminders.append(
            {
                "type": "wontfix_growing",
                "message": "Wontfix debt is growing. Review stale decisions: `desloppify show --status wontfix`.",
                "command": "desloppify show --status wontfix",
            }
        )

    scan_count = len(state.get("scan_history", []))
    if scan_count < 20 or command != "scan":
        return reminders

    stale_wontfix = []
    for finding in state.get("findings", {}).values():
        if finding.get("status") != "wontfix":
            continue
        resolved_at = finding.get("resolved_at")
        if not resolved_at:
            continue
        try:
            age_days = (_dt.now(_tz.utc) - _dt.fromisoformat(resolved_at)).days
        except (ValueError, TypeError) as exc:
            log_best_effort_failure(
                logger, f"parse wontfix timestamp {resolved_at!r}", exc
            )
            continue
        if age_days > 60:
            stale_wontfix.append(finding)

    if stale_wontfix:
        reminders.append(
            {
                "type": "wontfix_stale",
                "message": (
                    f"{len(stale_wontfix)} wontfix item(s) are >60 days old. "
                    f"Has anything changed? Review with: "
                    f'`desloppify show "*" --status wontfix`'
                ),
                "command": 'desloppify show "*" --status wontfix',
            }
        )
    return reminders


def _ignore_suppression_reminder(state: dict) -> list[dict]:
    """Nudge when ignores/suppression are high enough to mask signal quality."""
    integrity = state.get("ignore_integrity", {}) or {}
    ignored = int(integrity.get("ignored", 0) or 0)
    suppressed_pct = float(integrity.get("suppressed_pct", 0.0) or 0.0)
    if ignored < 10 and suppressed_pct < 30.0:
        return []
    return [
        {
            "type": "ignore_suppression_high",
            "message": (
                f"Ignore suppression is high ({ignored} ignored, {suppressed_pct:.1f}% suppressed). "
                "Revisit broad ignore patterns and resolve stale suppressions."
            ),
            "command": "desloppify show --status wontfix",
        }
    ]


def _stagnation_reminders(dimensions: dict) -> list[dict]:
    reminders: list[dict] = []
    for dim in dimensions.get("stagnant_dimensions", []):
        strict = dim.get("strict", 0)
        if strict >= 99:
            message = (
                f"{dim['name']} has been at {strict}% for {dim['stuck_scans']} scans. "
                f"The remaining items may be worth marking as wontfix if they're intentional."
            )
        else:
            message = (
                f"{dim['name']} has been stuck at {strict}% for {dim['stuck_scans']} scans. "
                f"Try tackling it from a different angle — run `desloppify next` to find the right entry point."
            )
        reminders.append(
            {
                "type": "stagnant_nudge",
                "message": message,
                "command": None,
            }
        )
    return reminders


def _dry_run_reminder(actions: list[dict]) -> list[dict]:
    if not actions or actions[0].get("type") != "auto_fix":
        return []
    return [
        {
            "type": "dry_run_first",
            "message": "Always --dry-run first, review changes, then apply.",
            "command": None,
        }
    ]


def _zone_classification_reminder(state: dict) -> list[dict]:
    zone_dist = state.get("zone_distribution")
    if not zone_dist:
        return []
    non_prod = sum(value for key, value in zone_dist.items() if key != "production")
    if non_prod <= 0:
        return []
    total = sum(zone_dist.values())
    parts = [
        f"{value} {key}"
        for key, value in sorted(zone_dist.items())
        if key != "production" and value > 0
    ]
    return [
        {
            "type": "zone_classification",
            "message": (
                f"{non_prod} of {total} files classified as non-production "
                f"({', '.join(parts)}). "
                f"Override with `desloppify zone set <file> production` "
                f"if any are misclassified."
            ),
            "command": "desloppify zone show",
        }
    ]


def _fp_calibration_reminders(fp_rates: dict[tuple[str, str], float]) -> list[dict]:
    reminders: list[dict] = []
    for (detector, zone), rate in fp_rates.items():
        if rate <= 0.3:
            continue
        pct = round(rate * 100)
        reminders.append(
            {
                "type": f"fp_calibration_{detector}_{zone}",
                "message": (
                    f"{pct}% of {detector} findings in {zone} zone are false positives. "
                    f"Consider reviewing detection rules for {zone} files."
                ),
                "command": None,
            }
        )
    return reminders


def _review_queue_reminders(
    state: dict,
    scoped_findings: dict,
    command: str | None,
    strict_score: float | None,
) -> list[dict]:
    reminders: list[dict] = []
    open_review = [
        finding
        for finding in scoped_findings.values()
        if finding.get("status") == "open" and finding.get("detector") == "review"
    ]
    if open_review:
        uninvestigated = [
            finding
            for finding in open_review
            if not finding.get("detail", {}).get("investigation")
        ]
        if uninvestigated:
            reminders.append(
                {
                    "type": "review_findings_pending",
                    "message": f"{len(uninvestigated)} review finding(s) need investigation. "
                    f"Run `desloppify issues` to see the work queue.",
                    "command": "desloppify issues",
                }
            )

    if command == "resolve" and state.get("subjective_assessments"):
        reminders.append(
            {
                "type": "rereview_needed",
                "message": "Subjective results may be stale after resolve. Re-run "
                "`desloppify review --prepare` to refresh, or reset with "
                "`desloppify scan --reset-subjective` before a clean rerun.",
                "command": "desloppify review --prepare",
            }
        )

    review_cache = state.get("review_cache", {})
    if not review_cache.get("files"):
        current_strict = strict_score or 0
        if current_strict >= 80:
            reminders.append(
                {
                    "type": "review_not_run",
                    "message": (
                        "Mechanical checks look good! Run a subjective design review "
                        "to catch issues linters miss: desloppify review --prepare"
                    ),
                    "command": "desloppify review --prepare",
                }
            )

    return reminders


def _review_staleness_reminder(state: dict, config: dict | None) -> list[dict]:
    review_max_age = (config or {}).get("review_max_age_days", 30)
    review_cache = state.get("review_cache", {})
    if review_max_age <= 0 or not review_cache.get("files"):
        return []
    try:
        oldest_str = min(
            review["reviewed_at"]
            for review in review_cache["files"].values()
            if review.get("reviewed_at")
        )
        oldest = _dt.fromisoformat(oldest_str)
        age_days = (_dt.now(_tz.utc) - oldest).days
    except (ValueError, TypeError) as exc:
        log_best_effort_failure(logger, "parse oldest review timestamp", exc)
        return []
    if age_days <= review_max_age:
        return []
    return [
        {
            "type": "review_stale",
            "message": f"Design review is {age_days} days old — run: desloppify review --prepare",
            "command": "desloppify review --prepare",
        }
    ]


def _feedback_reminder(
    state: dict,
    phase: str,
    command: str | None,
    fp_rates: dict[tuple[str, str], float],
) -> list[dict]:
    scan_count = len(state.get("scan_history", []))
    if scan_count < 2 or command != "scan":
        return []
    high_fp_dets = [
        detector for (detector, _zone), rate in fp_rates.items() if rate > 0.3
    ]
    if high_fp_dets:
        nudge_msg = (
            f"Some detectors have high false-positive rates ({', '.join(high_fp_dets)}). "
            f"If patterns are being misclassified, file an issue at "
            f"{_FEEDBACK_URL} with the file and expected behavior — "
            f"it helps calibrate detection for everyone."
        )
    elif phase == "stagnation":
        nudge_msg = (
            f"Score has plateaued — if you suspect desloppify is missing patterns "
            f"or not capturing something it should, file an issue at "
            f"{_FEEDBACK_URL} describing what you expected. "
            f"Gaps in detection are a common cause of stagnation."
        )
    else:
        nudge_msg = (
            f"If you notice patterns desloppify doesn't detect, false positives, "
            f"or findings that seem off, file an issue at {_FEEDBACK_URL} — "
            f"include the file and what you expected. It helps improve the tool."
        )
    return [
        {
            "type": "feedback_nudge",
            "message": nudge_msg,
            "command": None,
        }
    ]


_REMINDER_METADATA: dict[str, tuple[int, str]] = {
    # Highest urgency operational nudges.
    "rescan_needed": (1, "high"),
    "ignore_suppression_high": (1, "high"),
    "review_findings_pending": (1, "high"),
    "rereview_needed": (1, "high"),
    # Medium urgency quality/process nudges.
    "wontfix_growing": (2, "medium"),
    "wontfix_stale": (2, "medium"),
    "stagnant_nudge": (2, "medium"),
    "review_stale": (2, "medium"),
    "auto_fixers_available": (2, "medium"),
    "zone_classification": (2, "medium"),
    "fp_calibration": (2, "medium"),
    # Informational nudges.
    "badge_recommendation": (3, "low"),
    "dry_run_first": (3, "low"),
    "feedback_nudge": (3, "low"),
    "review_not_run": (3, "low"),
    "report_scores": (3, "low"),
}


def _decorate_reminder_metadata(reminders: list[dict]) -> list[dict]:
    """Attach stable priority/severity metadata and sort by priority."""
    decorated: list[dict] = []
    for reminder in reminders:
        reminder_type = str(reminder.get("type", ""))
        key = reminder_type
        if reminder_type.startswith("fp_calibration_"):
            key = "fp_calibration"
        priority, severity = _REMINDER_METADATA.get(key, (3, "low"))
        clone = dict(reminder)
        clone.setdefault("priority", priority)
        clone.setdefault("severity", severity)
        decorated.append(clone)
    decorated.sort(key=lambda item: (int(item.get("priority", 3)), str(item.get("type", ""))))
    return decorated


def _report_scores_reminder(command: str | None) -> list[dict]:
    if command != "scan":
        return []
    return [
        {
            "type": "report_scores",
            "message": (
                "ALWAYS share ALL scores with the user: overall, objective, and strict, "
                "plus every dimension score (lenient + strict), including subjective dimensions. "
                "The goal is to maximize strict scores."
            ),
            "command": None,
            "no_decay": True,
        }
    ]


def _apply_decay(
    reminders: list[dict], reminder_history: dict
) -> tuple[list[dict], dict]:
    filtered: list[dict] = []
    for reminder in reminders:
        if reminder.get("no_decay"):
            filtered.append(reminder)
            continue
        count = reminder_history.get(reminder["type"], 0)
        if count < _REMINDER_DECAY_THRESHOLD:
            filtered.append(reminder)

    updated_history = dict(reminder_history)
    for reminder in filtered:
        updated_history[reminder["type"]] = updated_history.get(reminder["type"], 0) + 1
    return filtered, updated_history


def _compute_reminders(
    state: dict,
    lang: str | None,
    phase: str,
    debt: dict,
    actions: list[dict],
    dimensions: dict,
    badge: dict,
    command: str | None,
    config: dict | None = None,
) -> tuple[list[dict], dict]:
    """Compute context-specific reminders, suppressing those shown too many times."""
    del lang  # Reserved for future language-specific rules.
    state_mod = importlib.import_module("desloppify.state")

    strict_score = state_mod.get_strict_score(state)
    reminder_history = state.get("reminder_history", {})
    scoped_findings = state_mod.path_scoped_findings(
        state.get("findings", {}), state.get("scan_path")
    )
    fp_rates = _compute_fp_rates(scoped_findings)

    reminders: list[dict] = []
    reminders.extend(_report_scores_reminder(command))
    reminders.extend(_auto_fixer_reminder(actions))
    reminders.extend(_rescan_needed_reminder(command))
    reminders.extend(_badge_reminder(strict_score, badge))
    reminders.extend(_wontfix_debt_reminders(state, debt, command))
    reminders.extend(_ignore_suppression_reminder(state))
    reminders.extend(_stagnation_reminders(dimensions))
    reminders.extend(_dry_run_reminder(actions))
    reminders.extend(_zone_classification_reminder(state))
    reminders.extend(_fp_calibration_reminders(fp_rates))
    reminders.extend(
        _review_queue_reminders(state, scoped_findings, command, strict_score)
    )
    reminders.extend(_review_staleness_reminder(state, config))
    reminders.extend(_feedback_reminder(state, phase, command, fp_rates))

    reminders = _decorate_reminder_metadata(reminders)
    return _apply_decay(reminders, reminder_history)
