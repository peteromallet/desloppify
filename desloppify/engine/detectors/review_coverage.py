"""Review coverage detector — flags production files lacking design review.

Runs during every scan. Checks the review_cache (persisted in state) to determine
which production files have been reviewed, are stale, or have changed since review.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from desloppify.file_discovery import read_file_text, rel, resolve_path
from desloppify.hook_registry import get_lang_hook

_LOW_VALUE_NAMES = re.compile(
    r"(?:^|/)(?:types|constants|enums|index)\.[a-z]+$|(?:^|/).+\.d\.[a-z]+$"
)
# Keep this expression distinct from other modules to avoid duplicate-constant
# drift while preserving the shared review threshold value.
MIN_REVIEW_LOC = 10 * 2


def _hash_file(filepath: str) -> str:
    try:
        content = Path(filepath).read_bytes()
        return hashlib.sha256(content).hexdigest()[:16]
    except OSError:
        return ""


def _is_low_value_file(
    filepath: str,
    lang_name: str,
    low_value_pattern: re.Pattern | None = None,
) -> bool:
    if isinstance(low_value_pattern, re.Pattern):
        return bool(low_value_pattern.search(filepath))

    mod = get_lang_hook(lang_name, "test_coverage")
    pattern = getattr(mod, "LOW_VALUE_NAMES", None) if mod is not None else None
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(filepath))
    return bool(_LOW_VALUE_NAMES.search(filepath))

def detect_review_coverage(
    files: list[str],
    zone_map,
    review_cache: dict,
    lang_name: str,
    max_age_days: int = 30,
    low_value_pattern: re.Pattern | None = None,
    holistic_cache: dict | None = None,
    holistic_total_files: int | None = None,
) -> tuple[list[dict], int]:
    """Detect production files missing or with stale design reviews.

    Args:
        files: list of file paths from file_finder
        zone_map: FileZoneMap (or None)
        review_cache: dict of {rel_path: {content_hash, reviewed_at, finding_count}}
        lang_name: language plugin name (for low-value pattern matching)
        max_age_days: reviews older than this are flagged as stale

    Returns:
        (entries, potential) where potential = count of reviewable production files.
    """
    now = datetime.now(UTC)
    entries: list[dict] = []
    candidates: list[tuple[str, str, int]] = []
    for filepath in files:
        rpath = rel(filepath)

        # Skip non-production files
        if zone_map is not None:
            zone = zone_map.get(filepath)
            if zone.value in ("test", "generated", "vendor", "config", "script"):
                continue

        # Skip low-value files (language-specific + generic patterns)
        if _is_low_value_file(rpath, lang_name, low_value_pattern=low_value_pattern):
            continue

        # Skip files below minimum LOC
        abs_path = resolve_path(filepath)
        content = read_file_text(abs_path)
        if content is None:
            continue
        loc = len(content.splitlines())
        if loc < MIN_REVIEW_LOC:
            continue

        candidates.append((abs_path, rpath, loc))

    potential = len(candidates)
    holistic_fresh = False
    if isinstance(holistic_cache, dict) and holistic_cache:
        full_sweep_included = holistic_cache.get("full_sweep_included")
        if full_sweep_included is not False:
            resolved_total_files = (
                holistic_total_files
                if isinstance(holistic_total_files, int) and holistic_total_files > 0
                else potential
            )
            holistic_fresh = (
                len(
                    detect_holistic_review_staleness(
                        {"holistic": holistic_cache},
                        total_files=resolved_total_files,
                        max_age_days=max_age_days,
                    )
                )
                == 0
            )

    for abs_path, rpath, loc in candidates:

        # Check review cache
        cached = review_cache.get(rpath)
        if cached is None:
            if holistic_fresh:
                continue
            entries.append(
                {
                    "file": abs_path,
                    "name": "unreviewed",
                    "tier": 4,
                    "confidence": "low",
                    "summary": "No design review on record — run `desloppify review --prepare`",
                    "detail": {"reason": "unreviewed", "loc": loc},
                }
            )
            continue

        # Check if content changed since review
        current_hash = _hash_file(abs_path)
        if current_hash and current_hash != cached.get("content_hash", ""):
            entries.append(
                {
                    "file": abs_path,
                    "name": "changed",
                    "tier": 4,
                    "confidence": "medium",
                    "summary": "File changed since last review — re-review recommended",
                    "detail": {"reason": "changed", "loc": loc},
                }
            )
            continue

        # max_age_days == 0 means "never" — reviews don't expire
        if max_age_days == 0:
            continue

        # Check if review is stale (age expired)
        reviewed_at = cached.get("reviewed_at", "")
        if reviewed_at:
            try:
                reviewed = datetime.fromisoformat(reviewed_at)
                age_days = (now - reviewed).days
                if age_days > max_age_days:
                    entries.append(
                        {
                            "file": abs_path,
                            "name": "stale",
                            "tier": 4,
                            "confidence": "low",
                            "summary": f"Review is stale ({age_days} days old) — re-review recommended",
                            "detail": {
                                "reason": "stale",
                                "age_days": age_days,
                                "loc": loc,
                            },
                        }
                    )
                    continue
            except (ValueError, TypeError):
                # Can't parse date — treat as stale
                entries.append(
                    {
                        "file": abs_path,
                        "name": "stale",
                        "tier": 4,
                        "confidence": "low",
                        "summary": "Review date unparseable — re-review recommended",
                        "detail": {"reason": "stale", "loc": loc},
                    }
                )
                continue
        else:
            # No reviewed_at — treat as unreviewed
            entries.append(
                {
                    "file": abs_path,
                    "name": "unreviewed",
                    "tier": 4,
                    "confidence": "low",
                    "summary": "No design review on record — run `desloppify review --prepare`",
                    "detail": {"reason": "unreviewed", "loc": loc},
                }
            )

    return entries, potential


def detect_holistic_review_staleness(
    review_cache: dict,
    total_files: int,
    max_age_days: int = 30,
) -> list[dict]:
    """Detect whether a holistic codebase-wide review is needed.

    Returns 0 or 1 entries:
    - No holistic review on record → holistic_unreviewed
    - Stale (>max_age_days) → holistic_stale
    - File count drifted >20% since review → holistic_stale
    """
    # No production files in scope means holistic review is not applicable.
    if total_files <= 0:
        return []

    holistic = review_cache.get("holistic")
    if not holistic:
        return [
            {
                "file": "",
                "name": "holistic_unreviewed",
                "tier": 4,
                "confidence": "low",
                "summary": "No holistic codebase review on record — run `desloppify review --prepare`",
                "detail": {"reason": "unreviewed"},
            }
        ]

    # max_age_days == 0 means "never" — holistic reviews don't expire
    if max_age_days == 0:
        return []

    now = datetime.now(UTC)

    # Check age
    reviewed_at = holistic.get("reviewed_at", "")
    if reviewed_at:
        try:
            reviewed = datetime.fromisoformat(reviewed_at)
            age_days = (now - reviewed).days
            if age_days > max_age_days:
                return [
                    {
                        "file": "",
                        "name": "holistic_stale",
                        "tier": 4,
                        "confidence": "low",
                        "summary": f"Holistic review is stale ({age_days} days old) — re-review recommended",
                        "detail": {"reason": "stale", "age_days": age_days},
                    }
                ]
        except (ValueError, TypeError):
            return [
                {
                    "file": "",
                    "name": "holistic_stale",
                    "tier": 4,
                    "confidence": "low",
                    "summary": "Holistic review date unparseable — re-review recommended",
                    "detail": {"reason": "stale"},
                }
            ]

    # Check file count drift
    file_count_at_review = holistic.get("file_count_at_review", 0)
    if file_count_at_review > 0 and total_files > 0:
        drift = abs(total_files - file_count_at_review) / file_count_at_review
        if drift > 0.20:
            return [
                {
                    "file": "",
                    "name": "holistic_stale",
                    "tier": 4,
                    "confidence": "low",
                    "summary": (
                        f"Codebase changed significantly since holistic review "
                        f"({file_count_at_review}→{total_files} files) — re-review recommended"
                    ),
                    "detail": {
                        "reason": "drift",
                        "old_files": file_count_at_review,
                        "new_files": total_files,
                    },
                }
            ]

    return []
