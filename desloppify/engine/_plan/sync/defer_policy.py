"""Shared defer-tracking helpers for triage and subjective rerun fairness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from desloppify.engine._state.schema import StateModel, utc_now

DEFER_ESCALATE_AFTER_SCANS = 3
DEFER_ESCALATE_AFTER_DAYS = 7


@dataclass(frozen=True)
class DeferUpdateOptions:
    """Options for durable defer-state updates."""

    deferred_ids_field: str = "deferred_ids"
    now: str | None = None


@dataclass(frozen=True)
class DeferEscalationOptions:
    """Options for defer-state escalation checks."""

    deferred_ids_field: str = "deferred_ids"
    now: str | None = None
    min_scans: int = DEFER_ESCALATE_AFTER_SCANS
    min_days: int = DEFER_ESCALATE_AFTER_DAYS


def _coerce_non_negative_int(value: object, *, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _scan_count(state: StateModel) -> int:
    return _coerce_non_negative_int(state.get("scan_count"), default=0)


def _normalize_timestamp(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value or None


def _parse_timestamp(raw: object) -> datetime | None:
    normalized = _normalize_timestamp(raw)
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _current_timestamp(
    state: StateModel,
    *,
    now: str | None = None,
) -> str:
    for raw in (state.get("last_scan"), now):
        normalized = _normalize_timestamp(raw)
        if normalized:
            return normalized
    return utc_now()


def _normalized_ids(ids: set[str]) -> list[str]:
    return sorted({str(issue_id).strip() for issue_id in ids if str(issue_id).strip()})


def _deferred_ids(
    defer_state: dict[str, object],
    *,
    deferred_ids_field: str,
) -> list[str]:
    raw = defer_state.get(deferred_ids_field)
    if not isinstance(raw, list):
        return []
    return sorted(
        {
            str(issue_id).strip()
            for issue_id in raw
            if str(issue_id).strip()
        }
    )


def update_defer_state(
    defer_state: dict[str, object] | None,
    *,
    state: StateModel,
    deferred_ids: set[str],
    options: DeferUpdateOptions | None = None,
) -> dict[str, object]:
    """Return updated durable defer metadata for the current deferred ID set."""
    resolved_options = options or DeferUpdateOptions()
    previous = defer_state if isinstance(defer_state, dict) else {}
    current_ids = _normalized_ids(deferred_ids)
    previous_ids = _deferred_ids(
        previous,
        deferred_ids_field=resolved_options.deferred_ids_field,
    )
    scan_count = _scan_count(state)
    timestamp = _current_timestamp(state, now=resolved_options.now)

    updated = dict(previous)
    updated[resolved_options.deferred_ids_field] = current_ids
    updated["last_deferred_scan"] = scan_count
    updated["last_deferred_at"] = timestamp

    same_ids = bool(current_ids) and current_ids == previous_ids
    if same_ids:
        defer_count = _coerce_non_negative_int(previous.get("defer_count"), default=1)
        prior_scan = _coerce_non_negative_int(previous.get("last_deferred_scan"), default=-1)
        if prior_scan != scan_count:
            defer_count += 1
        updated["defer_count"] = max(1, defer_count)
        updated["first_deferred_scan"] = _coerce_non_negative_int(
            previous.get("first_deferred_scan"),
            default=scan_count,
        )
        updated["first_deferred_at"] = str(previous.get("first_deferred_at") or timestamp)
    else:
        updated["defer_count"] = 1 if current_ids else 0
        updated["first_deferred_scan"] = scan_count
        updated["first_deferred_at"] = timestamp
    return updated


def should_escalate_defer_state(
    defer_state: dict[str, object] | None,
    *,
    state: StateModel,
    options: DeferEscalationOptions | None = None,
) -> bool:
    """Return True when defer metadata crosses configured escalation bounds."""
    if not isinstance(defer_state, dict):
        return False
    resolved_options = options or DeferEscalationOptions()

    deferred_ids = _deferred_ids(
        defer_state,
        deferred_ids_field=resolved_options.deferred_ids_field,
    )
    if not deferred_ids:
        return False

    min_scans = max(1, int(resolved_options.min_scans))
    min_days = max(1, int(resolved_options.min_days))

    defer_count = _coerce_non_negative_int(defer_state.get("defer_count"), default=0)
    if defer_count >= min_scans:
        return True

    first_scan = _coerce_non_negative_int(
        defer_state.get("first_deferred_scan"),
        default=-1,
    )
    current_scan = _scan_count(state)
    if first_scan >= 0 and current_scan - first_scan + 1 >= min_scans:
        return True

    first_deferred_at = _parse_timestamp(defer_state.get("first_deferred_at"))
    current_at = _parse_timestamp(state.get("last_scan")) or _parse_timestamp(
        resolved_options.now
    )
    if first_deferred_at is None or current_at is None:
        return False
    return (current_at - first_deferred_at).total_seconds() >= min_days * 86400


__all__ = [
    "DEFER_ESCALATE_AFTER_DAYS",
    "DEFER_ESCALATE_AFTER_SCANS",
    "DeferEscalationOptions",
    "DeferUpdateOptions",
    "should_escalate_defer_state",
    "update_defer_state",
]
