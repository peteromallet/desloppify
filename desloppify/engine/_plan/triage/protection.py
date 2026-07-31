"""User-owned review issue exclusions for triage automation.

Protected review IDs remain open in state and may remain in user-owned plan
clusters.  They are deliberately outside automated triage scope; protection is
not a skip, resolution, or disposition.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping

from desloppify.engine._plan.skip_policy import SYSTEM_SKIP_KINDS

PROTECTED_REVIEW_ISSUE_IDS_KEY = "protected_review_issue_ids"


def protected_review_issue_ids_from_meta(meta: Mapping[str, object] | None) -> set[str]:
    """Return normalized user-protected review IDs from triage metadata."""
    if not isinstance(meta, Mapping):
        return set()
    raw_ids = meta.get(PROTECTED_REVIEW_ISSUE_IDS_KEY)
    if not isinstance(raw_ids, list):
        return set()
    return {
        issue_id.strip()
        for issue_id in raw_ids
        if isinstance(issue_id, str) and issue_id.strip()
    }


def protected_review_issue_ids(plan: Mapping[str, object] | None) -> set[str]:
    """Return explicit review IDs that automated triage must leave untouched."""
    if not isinstance(plan, Mapping):
        return set()
    meta = plan.get("epic_triage_meta")
    return protected_review_issue_ids_from_meta(meta if isinstance(meta, Mapping) else None)


def clear_protected_triage_artifacts(
    plan: MutableMapping[str, object],
    state: MutableMapping[str, object] | None = None,
) -> None:
    """Remove automated plan artifacts for protected review IDs.

    Protection is an exclusion from triage, not a disposition.  When a user
    protects an ID that was previously touched by automation, clear those
    automation-owned plan entries instead of retaining or rewriting them.

    This is deliberately a sanitation boundary rather than a skip operation:
    protected IDs must not remain in execution containers that can make them
    visible to ``next``.  Manual cluster membership is retained, but automated
    cluster membership and all queue/override references are removed.
    """
    protected_ids = protected_review_issue_ids(plan)
    if not protected_ids:
        return

    automated_ids: set[str] = set()
    meta = plan.get("epic_triage_meta")
    if isinstance(meta, MutableMapping):
        dispositions = meta.get("issue_dispositions")
        if isinstance(dispositions, MutableMapping):
            for issue_id in protected_ids:
                entry = dispositions.get(issue_id)
                if isinstance(entry, Mapping) and entry.get("decision_source") == "observe_auto":
                    automated_ids.add(issue_id)
                dispositions.pop(issue_id, None)
        for key in ("active_triage_issue_ids", "undispositioned_issue_ids", "dismissed_ids"):
            issue_ids = meta.get(key)
            if isinstance(issue_ids, list):
                meta[key] = [
                    issue_id
                    for issue_id in issue_ids
                    if issue_id not in protected_ids
                ]

    root_dispositions = plan.get("issue_dispositions")
    if isinstance(root_dispositions, MutableMapping):
        for issue_id in protected_ids:
            entry = root_dispositions.get(issue_id)
            if isinstance(entry, Mapping) and entry.get("decision_source") == "observe_auto":
                automated_ids.add(issue_id)
            root_dispositions.pop(issue_id, None)

    skipped = plan.get("skipped")
    if isinstance(skipped, MutableMapping):
        for issue_id in protected_ids:
            entry = skipped.get(issue_id)
            if isinstance(entry, Mapping) and entry.get("kind") in SYSTEM_SKIP_KINDS:
                automated_ids.add(issue_id)
            skipped.pop(issue_id, None)

    queue_order = plan.get("queue_order")
    if isinstance(queue_order, list):
        queue_order[:] = [
            issue_id for issue_id in queue_order if issue_id not in protected_ids
        ]

    promoted_ids = plan.get("promoted_ids")
    if isinstance(promoted_ids, list):
        promoted_ids[:] = [
            issue_id for issue_id in promoted_ids if issue_id not in protected_ids
        ]

    overrides = plan.get("overrides")
    if isinstance(overrides, MutableMapping):
        for issue_id in protected_ids:
            overrides.pop(issue_id, None)

    clusters = plan.get("clusters")
    if isinstance(clusters, Mapping):
        for cluster in clusters.values():
            if not isinstance(cluster, MutableMapping) or not cluster.get("auto"):
                continue
            issue_ids = cluster.get("issue_ids")
            if not isinstance(issue_ids, list):
                continue
            cluster["issue_ids"] = [
                issue_id for issue_id in issue_ids if issue_id not in protected_ids
            ]

        active_cluster = plan.get("active_cluster")
        active = clusters.get(active_cluster) if isinstance(active_cluster, str) else None
        if isinstance(active, Mapping) and active.get("auto") and not active.get("issue_ids"):
            plan["active_cluster"] = None

    if state is None:
        return
    for issue_map in (state.get("work_items"), state.get("issues")):
        if not isinstance(issue_map, MutableMapping):
            continue
        for issue_id in protected_ids:
            issue = issue_map.get(issue_id)
            if not isinstance(issue, MutableMapping):
                continue
            status = issue.get("status")
            if status == "triaged_out" or (
                issue_id in automated_ids and status == "false_positive"
            ):
                issue["status"] = "open"


__all__ = [
    "PROTECTED_REVIEW_ISSUE_IDS_KEY",
    "clear_protected_triage_artifacts",
    "protected_review_issue_ids",
    "protected_review_issue_ids_from_meta",
]
