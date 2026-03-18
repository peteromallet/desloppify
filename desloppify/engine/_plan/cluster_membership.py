"""Canonical cluster membership helpers for persisted plan payloads."""

from __future__ import annotations

from desloppify.engine.plan_state import Cluster


def cluster_issue_ids(cluster: Cluster | dict[str, object]) -> list[str]:
    """Return the effective issue IDs for a cluster."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _append(raw_ids: object) -> None:
        if not isinstance(raw_ids, list):
            return
        for raw_id in raw_ids:
            if not isinstance(raw_id, str):
                continue
            issue_id = raw_id.strip()
            if not issue_id or issue_id in seen:
                continue
            seen.add(issue_id)
            ordered.append(issue_id)

    _append(cluster.get("issue_ids"))

    return ordered


__all__ = ["cluster_issue_ids"]
