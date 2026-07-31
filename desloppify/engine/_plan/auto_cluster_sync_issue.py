"""Issue auto-cluster synchronization helpers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from desloppify.base.registry import DETECTORS
from desloppify.engine._plan.cluster_semantics import (
    EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
    EXECUTION_STATUS_ACTIVE,
    EXECUTION_STATUS_REVIEW,
    infer_cluster_execution_policy,
    normalize_cluster_semantics,
)
from desloppify.engine._plan.cluster_strategy import (
    cluster_name_from_key as _cluster_name_from_key,
)
from desloppify.engine._plan.cluster_strategy import (
    generate_action as _generate_action,
)
from desloppify.engine._plan.cluster_strategy import (
    generate_description as _generate_description,
)
from desloppify.engine._plan.cluster_strategy import (
    grouping_key as _grouping_key,
)
from desloppify.engine._plan.triage.protection import protected_review_issue_ids

_MIN_CLUSTER_SIZE = 2


def _auto_cluster_execution_status(
    cluster: dict,
    *,
    detector: str = "",
) -> str:
    if (
        infer_cluster_execution_policy(cluster, detector=detector)
        == EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE
    ):
        return EXECUTION_STATUS_ACTIVE
    return EXECUTION_STATUS_REVIEW


@dataclass(frozen=True)
class AutoClusterSyncResult:
    """Explicit result describing what `_sync_auto_cluster` changed."""

    cluster_name: str
    changed: bool
    created: bool
    member_count: int


def _manual_member_ids(clusters: dict) -> set[str]:
    """Collect all issue IDs belonging to manual (non-auto) clusters."""
    ids: set[str] = set()
    for cluster in clusters.values():
        if not cluster.get("auto"):
            ids.update(cluster.get("issue_ids", []))
    return ids


def _group_clusterable_issues(
    issues: dict,
    *,
    manual_member_ids: set[str],
    protected_issue_ids: set[str] | None = None,
) -> tuple[dict[str, list[str]], dict[str, dict]]:
    """Group open, non-suppressed, non-manual issues by detector/subtype key."""
    protected_ids = protected_issue_ids or set()
    groups: dict[str, list[str]] = defaultdict(list)
    issue_data: dict[str, dict] = {}
    for fid, issue in issues.items():
        if issue.get("status") != "open":
            continue
        if issue.get("suppressed"):
            continue
        if fid in manual_member_ids:
            continue
        if fid in protected_ids:
            continue

        detector = issue.get("detector", "")
        meta = DETECTORS.get(detector)
        key = _grouping_key(issue, meta)
        if key is None:
            continue

        groups[key].append(fid)
        issue_data[fid] = issue

    groups = {k: v for k, v in groups.items() if len(v) >= _MIN_CLUSTER_SIZE}
    return groups, issue_data


def _sync_user_modified_cluster_members(
    plan: dict,
    *,
    clusters: dict,
    existing_name: str,
    member_ids: list[str],
    now: str,
) -> int:
    """Sync member IDs for a user-modified cluster, returns count of changes."""
    cluster = clusters[existing_name]
    changes = 0
    existing_ids = set(cluster.get("issue_ids", []))
    new_ids = [fid for fid in member_ids if fid not in existing_ids]
    if new_ids:
        cluster["issue_ids"].extend(new_ids)
        cluster["updated_at"] = now
        changes = 1
    overrides = plan.get("overrides", {})
    for fid in member_ids:
        if fid not in overrides:
            overrides[fid] = {"issue_id": fid, "created_at": now}
        overrides[fid]["cluster"] = existing_name
        overrides[fid]["updated_at"] = now
    return changes


def _sync_auto_cluster(
    plan: dict,
    clusters: dict,
    existing_by_key: dict[str, str],
    *,
    cluster_key: str,
    cluster_name: str,
    member_ids: list[str],
    description: str,
    action: str,
    now: str,
    detector: str = "",
    optional: bool = False,
) -> AutoClusterSyncResult:
    """Create/update one auto-cluster and report the mutation outcome.

    Mutates:
      - ``clusters`` (cluster create/update),
      - ``existing_by_key`` (cluster-key to name binding),
      - ``plan['overrides']`` (cluster ownership for each member issue).
    """
    changes = 0
    created = False
    existing_name = existing_by_key.get(cluster_key)
    if existing_name and existing_name in clusters:
        cluster = clusters[existing_name]
        old_ids = set(cluster.get("issue_ids", []))
        new_ids_set = set(member_ids)
        if (
            old_ids != new_ids_set
            or cluster.get("description") != description
            or cluster.get("action") != action
        ):
            cluster["issue_ids"] = list(member_ids)
            cluster["description"] = description
            cluster["action"] = action
            cluster["updated_at"] = now
            changes = 1
        execution_status = _auto_cluster_execution_status(cluster, detector=detector)
        if cluster.get("execution_status") != execution_status:
            cluster["execution_status"] = execution_status
            cluster["updated_at"] = now
            changes = 1
        if normalize_cluster_semantics(cluster, detector=detector):
            cluster["updated_at"] = now
            changes = 1
    else:
        new_cluster = {
            "name": cluster_name,
            "description": description,
            "issue_ids": list(member_ids),
            "created_at": now,
            "updated_at": now,
            "auto": True,
            "cluster_key": cluster_key,
            "action": action,
            "execution_status": _auto_cluster_execution_status(
                {"auto": True, "action": action},
                detector=detector,
            ),
            "user_modified": False,
        }
        if optional:
            new_cluster["optional"] = True
        normalize_cluster_semantics(new_cluster, detector=detector)
        clusters[cluster_name] = new_cluster
        existing_by_key[cluster_key] = cluster_name
        changes = 1
        created = True

    overrides = plan.get("overrides", {})
    current_name = existing_by_key.get(cluster_key, cluster_name)
    for fid in member_ids:
        if fid not in overrides:
            overrides[fid] = {"issue_id": fid, "created_at": now}
        overrides[fid]["cluster"] = current_name
        overrides[fid]["updated_at"] = now

    return AutoClusterSyncResult(
        cluster_name=current_name,
        changed=bool(changes),
        created=created,
        member_count=len(member_ids),
    )


def sync_issue_clusters(
    plan: dict,
    issues: dict,
    clusters: dict,
    existing_by_key: dict[str, str],
    active_auto_keys: set[str],
    now: str,
) -> int:
    """Group open issues by detector/subtype and sync auto-clusters."""
    changes = 0

    groups, issue_data = _group_clusterable_issues(
        issues,
        manual_member_ids=_manual_member_ids(clusters),
        protected_issue_ids=protected_review_issue_ids(plan),
    )

    for key, member_ids in groups.items():
        active_auto_keys.add(key)
        cluster_name = _cluster_name_from_key(key)

        rep = issue_data.get(member_ids[0], {})
        detector = rep.get("detector", "")
        meta = DETECTORS.get(detector)
        members = [issue_data[fid] for fid in member_ids if fid in issue_data]

        key_parts = key.split("::")
        subtype = key_parts[2] if len(key_parts) >= 3 else None

        description = _generate_description(members, meta)
        action = _generate_action(meta, subtype)

        existing_name = existing_by_key.get(key)
        if existing_name and existing_name in clusters:
            cluster = clusters[existing_name]
            if cluster.get("user_modified"):
                changes += _sync_user_modified_cluster_members(
                    plan,
                    clusters=clusters,
                    existing_name=existing_name,
                    member_ids=member_ids,
                    now=now,
                )
                continue

        if cluster_name in clusters and clusters[cluster_name].get("cluster_key") != key:
            cluster_name = f"{cluster_name}-{len(member_ids)}"

        sync_result = _sync_auto_cluster(
            plan,
            clusters,
            existing_by_key,
            cluster_key=key,
            cluster_name=cluster_name,
            member_ids=member_ids,
            description=description,
            action=action,
            now=now,
            detector=detector,
        )
        changes += int(sync_result.changed)

    return changes


__all__ = ["AutoClusterSyncResult", "sync_issue_clusters"]
