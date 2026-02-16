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


class Tier(enum.IntEnum):
    AUTO_FIX = 1
    QUICK_FIX = 2
    JUDGMENT = 3
    MAJOR_REFACTOR = 4
