"""State-backed work queue for review findings.

Review findings live in state["findings"]. This module provides:
- Listing/sorting open review findings by impact
- Storing investigation notes on findings
- Expiring stale holistic findings during scan
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from desloppify.core.issues_render import finding_weight

logger = logging.getLogger(__name__)

__all__ = [
    "impact_label",
    "list_open_review_findings",
    "update_investigation",
    "expire_stale_holistic",
]


def impact_label(weight: float) -> str:
    """Convert weight to a human-readable impact label."""
    try:
        numeric = float(weight)
    except (TypeError, ValueError):
        return "+"
    if numeric >= 8:
        return "+++"
    if numeric >= 5:
        return "++"
    return "+"


def list_open_review_findings(state: dict) -> list[dict]:
    """Return open review findings sorted by impact (highest first)."""
    findings = state.get("findings", {})
    review = [
        finding
        for finding in findings.values()
        if finding.get("status") == "open" and finding.get("detector") == "review"
    ]

    def _sort_key(finding: dict) -> tuple[float, str]:
        weight, _impact, finding_id = finding_weight(finding)
        return (-weight, finding_id)

    review.sort(key=_sort_key)
    return review


def update_investigation(state: dict, finding_id: str, text: str) -> bool:
    """Store investigation text on a finding. Returns False if not found/not open."""
    finding = state.get("findings", {}).get(finding_id)
    if not finding or finding.get("status") != "open":
        return False
    detail = finding.setdefault("detail", {})
    detail["investigation"] = text
    detail["investigated_at"] = datetime.now(timezone.utc).isoformat()
    return True


def expire_stale_holistic(state: dict, max_age_days: int = 30) -> list[str]:
    """Auto-resolve holistic review findings older than max_age_days."""
    now = datetime.now(timezone.utc)
    expired: list[str] = []

    for finding_id, finding in state.get("findings", {}).items():
        if finding.get("detector") != "review":
            continue
        if finding.get("status") != "open":
            continue
        if not finding.get("detail", {}).get("holistic"):
            continue

        last_seen = finding.get("last_seen")
        if not last_seen:
            continue

        try:
            seen_dt = datetime.fromisoformat(last_seen)
        except (ValueError, TypeError) as exc:
            logger.debug(
                "Skipping holistic finding %s with invalid last_seen %r: %s",
                finding_id,
                last_seen,
                exc,
            )
            continue

        age_days = (now - seen_dt).days
        if age_days > max_age_days:
            finding["status"] = "auto_resolved"
            finding["resolved_at"] = now.isoformat()
            finding["note"] = "holistic review expired — re-run review to re-evaluate"
            expired.append(finding_id)

    return expired
