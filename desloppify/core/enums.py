"""Canonical enums for finding attributes.

StrEnum values compare equal to their string values (Confidence.HIGH == "high"),
so existing code using raw strings continues to work during gradual migration.
"""

from __future__ import annotations

import enum


class Confidence(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Status(enum.StrEnum):
    OPEN = "open"
    FIXED = "fixed"
    WONTFIX = "wontfix"
    FALSE_POSITIVE = "false_positive"
    AUTO_RESOLVED = "auto_resolved"
    RESOLVED = "resolved"  # Legacy on-disk value; migrated to FIXED on load.


_CANONICAL_FINDING_STATUSES = frozenset(
    {
        Status.OPEN.value,
        Status.FIXED.value,
        Status.WONTFIX.value,
        Status.FALSE_POSITIVE.value,
        Status.AUTO_RESOLVED.value,
    }
)
_RESOLVED_STATUSES = frozenset(
    {
        Status.FIXED.value,
        Status.WONTFIX.value,
        Status.FALSE_POSITIVE.value,
        Status.AUTO_RESOLVED.value,
    }
)
_LEGACY_STATUS_ALIASES = {
    Status.RESOLVED.value: Status.FIXED.value,
}


class Tier(enum.IntEnum):
    AUTO_FIX = 1
    QUICK_FIX = 2
    JUDGMENT = 3
    MAJOR_REFACTOR = 4


def canonical_finding_status(value: object, *, default: str = Status.OPEN.value) -> str:
    """Normalize legacy/unknown finding status values to a canonical token."""
    token = str(value).strip().lower()
    token = _LEGACY_STATUS_ALIASES.get(token, token)
    return token if token in _CANONICAL_FINDING_STATUSES else default


def finding_status_tokens(*, include_all: bool = False) -> frozenset[str]:
    """Return canonical finding-status tokens, optionally including `all`."""
    if include_all:
        return frozenset({*_CANONICAL_FINDING_STATUSES, "all"})
    return _CANONICAL_FINDING_STATUSES


def resolved_statuses() -> frozenset[str]:
    """Return the set of statuses that mean a finding is no longer open."""
    return _RESOLVED_STATUSES


__all__ = [
    "Confidence",
    "Status",
    "Tier",
    "canonical_finding_status",
    "finding_status_tokens",
    "resolved_statuses",
]
