"""File selection and staleness tracking for review."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from ..utils import rel, read_file_text
from .context import _abs, _dep_graph_lookup, _importer_count


# Files with these name patterns have low subjective review value —
# they're mostly declarations (types, constants, enums) not logic.
LOW_VALUE_NAMES = re.compile(
    r"(?:^|/)(?:types|constants|enums|index)\.[a-z]+$"
    r"|\.d\.ts$"
)

# Minimum LOC to be worth a review slot
MIN_REVIEW_LOC = 20


def hash_file(filepath: str) -> str:
    """Compute a content hash for a file."""
    try:
        content = Path(filepath).read_bytes()
        return hashlib.sha256(content).hexdigest()[:16]
    except OSError:
        return ""


def select_files_for_review(
    lang, path: Path, state: dict,
    max_files: int = 50, max_age_days: int = 30, force_refresh: bool = False,
    files: list[str] | None = None,
) -> list[str]:
    """Select production files for review, priority-sorted.

    If *files* is provided, skip file_finder (avoids redundant filesystem walks).
    """
    if files is None:
        files = lang.file_finder(path) if lang.file_finder else []

    cache = state.get("review_cache", {}).get("files", {})
    now = datetime.now(timezone.utc)
    candidates = []

    for filepath in files:
        rpath = rel(filepath)

        # Skip non-production files
        if lang._zone_map is not None:
            zone = lang._zone_map.get(filepath)
            if zone.value in ("test", "generated", "vendor"):
                continue

        # Skip if cached, content unchanged, and not stale
        if not force_refresh:
            entry = cache.get(rpath)
            if entry:
                current_hash = hash_file(_abs(filepath))
                if current_hash and current_hash == entry.get("content_hash"):
                    reviewed_at = entry.get("reviewed_at", "")
                    if reviewed_at:
                        try:
                            reviewed = datetime.fromisoformat(reviewed_at)
                            age_days = (now - reviewed).days
                            if age_days <= max_age_days:
                                continue  # Still fresh
                        except (ValueError, TypeError):
                            pass  # Can't parse date, treat as stale

        priority = _compute_review_priority(filepath, lang, state)
        if priority >= 0:  # Negative = filtered out (too small)
            candidates.append((filepath, priority))

    candidates.sort(key=lambda x: -x[1])
    return [f for f, _ in candidates[:max_files]]


def _compute_review_priority(filepath: str, lang, state: dict) -> int:
    """Higher = more important to review.

    Prioritizes implementation files with high blast radius and existing findings.
    Deprioritizes types/constants files (low subjective review value).
    """
    score = 0
    rpath = rel(filepath)

    content = read_file_text(_abs(filepath))
    loc = len(content.splitlines()) if content is not None else 0

    # Skip tiny files — not enough to review
    if loc < MIN_REVIEW_LOC:
        return -1

    # Low-value files: types, constants, enums, index files, .d.ts
    is_low_value = bool(LOW_VALUE_NAMES.search(rpath))

    # High blast radius (many importers)
    if lang._dep_graph:
        entry = _dep_graph_lookup(lang._dep_graph, filepath)
        ic = _importer_count(entry)
        if is_low_value:
            score += ic * 2
        else:
            score += ic * 10

    # Already has programmatic findings (compound value — review will be richer)
    findings = state.get("findings", {})
    n_findings = sum(1 for f in findings.values()
                     if f.get("file") == rpath and f["status"] == "open")
    score += n_findings * 5

    # High-complexity files with wontfixed structural findings
    # (mechanical detector says "complex" but can't say why — subjective review can)
    n_wontfix_structural = sum(
        1 for f in findings.values()
        if f.get("file") == rpath and f["status"] == "wontfix"
        and f.get("detector") in ("structural", "smells")
    )
    if n_wontfix_structural:
        score += n_wontfix_structural * 15  # Strong boost — these need human insight

    # Complexity score from mechanical detectors (if available)
    complexity_map = getattr(lang, "_complexity_map", None)
    if isinstance(complexity_map, dict) and complexity_map.get(rpath, 0) > 100:
        score += 20  # Very complex files need subjective review most

    # Larger files have more to review
    score += loc // 50

    # Low-value penalty — push toward bottom but don't exclude entirely
    if is_low_value:
        score = score // 3

    return score


def _get_file_findings(state: dict, filepath: str) -> list[dict]:
    """Get existing open findings for a file (summaries for context)."""
    rpath = rel(filepath)
    findings = state.get("findings", {})
    return [
        {"detector": f["detector"], "summary": f["summary"], "id": f["id"]}
        for f in findings.values()
        if f.get("file") == rpath and f["status"] == "open"
    ]


def _count_fresh(state: dict, max_age_days: int) -> int:
    """Count files in review cache that are still fresh."""
    cache = state.get("review_cache", {}).get("files", {})
    now = datetime.now(timezone.utc)
    count = 0
    for entry in cache.values():
        reviewed_at = entry.get("reviewed_at", "")
        if reviewed_at:
            try:
                reviewed = datetime.fromisoformat(reviewed_at)
                if (now - reviewed).days <= max_age_days:
                    count += 1
            except (ValueError, TypeError):
                pass
    return count


def _count_stale(state: dict, max_age_days: int) -> int:
    """Count files in review cache that are stale."""
    cache = state.get("review_cache", {}).get("files", {})
    total = len(cache)
    return total - _count_fresh(state, max_age_days)
