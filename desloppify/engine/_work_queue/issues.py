"""State-backed work queue for review issues.

Review issues live in state["issues"]. This module provides:
- Listing/sorting open review issues by impact
- Storing investigation notes on issues
- Expiring stale holistic issues during scan
"""

from __future__ import annotations

import logging
from desloppify.base.compatibility import UTC
from datetime import datetime

from desloppify.base.output.issues import issue_weight
from desloppify.engine._work_queue.helpers import detail_dict

logger = logging.getLogger(__name__)

__all__ = [
    "impact_label",
    "list_open_review_issues",
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


def list_open_review_issues(state: dict) -> list[dict]:
    """Return open review issues sorted by impact (highest first)."""
    issues = state.get("issues", {})
    review = [
        issue
        for issue in issues.values()
        if issue.get("status") == "open" and issue.get("detector") == "review"
    ]

    def _sort_key(issue: dict) -> tuple[float, str]:
        weight, _impact, issue_id = issue_weight(issue)
        return (-weight, issue_id)

    review.sort(key=_sort_key)
    return review


def update_investigation(state: dict, issue_id: str, text: str) -> bool:
    """Store investigation text on a issue. Returns False if not found/not open."""
    issue = state.get("issues", {}).get(issue_id)
    if not issue or issue.get("status") != "open":
        return False
    detail = detail_dict(issue)
    if not detail:
        detail = {}
        issue["detail"] = detail
    detail["investigation"] = text
    detail["investigated_at"] = datetime.now(UTC).isoformat()
    return True


def expire_stale_holistic(state: dict, max_age_days: int = 30) -> list[str]:
    """Auto-resolve holistic review issues older than max_age_days."""
    now = datetime.now(UTC)
    expired: list[str] = []

    for issue_id, issue in state.get("issues", {}).items():
        if issue.get("detector") != "review":
            continue
        if issue.get("status") != "open":
            continue
        if not detail_dict(issue).get("holistic"):
            continue

        last_seen = issue.get("last_seen")
        if not last_seen:
            continue

        try:
            seen_dt = datetime.fromisoformat(last_seen)
        except (ValueError, TypeError) as exc:
            logger.debug(
                "Skipping holistic issue %s with invalid last_seen %r: %s",
                issue_id,
                last_seen,
                exc,
            )
            continue

        age_days = (now - seen_dt).days
        if age_days > max_age_days:
            issue["status"] = "auto_resolved"
            issue["resolved_at"] = now.isoformat()
            issue["note"] = "holistic review expired — re-run review to re-evaluate"
            expired.append(issue_id)

    return expired
