"""Stable normalization helpers for loaded plan payloads."""

from __future__ import annotations

import re
from typing import Any

from desloppify.engine._plan.cluster_semantics import normalize_cluster_semantics

_HEX_SUFFIX_RE = re.compile(r"^[0-9a-f]{8}$")


def _rename_key(d: dict, old: str, new: str) -> bool:
    if old not in d:
        return False
    d.setdefault(new, d.pop(old))
    return True


def _ensure_container(
    plan: dict[str, Any],
    key: str,
    expected_type: type[list] | type[dict],
    default_factory,
) -> None:
    if not isinstance(plan.get(key), expected_type):
        plan[key] = default_factory()


def ensure_container_types(plan: dict[str, Any]) -> None:
    """Normalize top-level container keys onto their runtime shapes."""
    for key, expected_type, default_factory in (
        ("queue_order", list, list),
        ("deferred", list, list),
        ("skipped", dict, dict),
        ("overrides", dict, dict),
        ("clusters", dict, dict),
        ("superseded", dict, dict),
        ("promoted_ids", list, list),
        ("plan_start_scores", dict, dict),
        ("refresh_state", dict, dict),
        ("execution_log", list, list),
        ("epic_triage_meta", dict, dict),
    ):
        _ensure_container(plan, key, expected_type, default_factory)
    _rename_key(plan["epic_triage_meta"], "finding_snapshot_hash", "issue_snapshot_hash")
    _ensure_container(plan, "commit_log", list, list)
    _rename_key(plan, "uncommitted_findings", "uncommitted_issues")
    _ensure_container(plan, "uncommitted_issues", list, list)
    if "commit_tracking_branch" not in plan:
        plan["commit_tracking_branch"] = None


def _normalize_cluster_issue_id(raw_id: object) -> str | None:
    if not isinstance(raw_id, str):
        return None
    issue_id = raw_id.strip()
    if not issue_id:
        return None
    if _HEX_SUFFIX_RE.fullmatch(issue_id):
        return None
    if issue_id.startswith("review::") or issue_id.startswith("concerns::"):
        parts = issue_id.split("::")
        if len(parts) >= 2 and _HEX_SUFFIX_RE.fullmatch(parts[-1]):
            return "::".join(parts[:-1])
    return issue_id


def _override_cluster_members(plan: dict[str, Any]) -> dict[str, list[str]]:
    members: dict[str, list[str]] = {}
    seen_by_cluster: dict[str, set[str]] = {}
    overrides = plan.get("overrides", {})
    if not isinstance(overrides, dict):
        return members

    for issue_id, override in overrides.items():
        normalized_issue_id = _normalize_cluster_issue_id(issue_id)
        if normalized_issue_id is None or not isinstance(override, dict):
            continue
        cluster_name = override.get("cluster")
        if not isinstance(cluster_name, str) or not cluster_name.strip():
            continue
        cluster_name = cluster_name.strip()
        bucket = members.setdefault(cluster_name, [])
        seen = seen_by_cluster.setdefault(cluster_name, set())
        if normalized_issue_id in seen:
            continue
        seen.add(normalized_issue_id)
        bucket.append(normalized_issue_id)
    return members


def _execution_log_cluster_members(
    plan: dict[str, Any],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    members: dict[str, list[str]] = {}
    hash_lookup: dict[str, str] = {}

    for entry in plan.get("execution_log", []):
        cluster_entry = _execution_log_cluster_entry(entry)
        if cluster_entry is None:
            continue
        cluster_name, action, normalized_issue_ids = cluster_entry
        if action == "cluster_delete":
            members.pop(cluster_name, None)
            continue
        if not normalized_issue_ids:
            continue
        _apply_execution_log_cluster_action(
            members,
            hash_lookup,
            cluster_name=cluster_name,
            action=action,
            issue_ids=normalized_issue_ids,
        )

    return members, hash_lookup


def _execution_log_cluster_entry(
    entry: object,
) -> tuple[str, object, list[str]] | None:
    if not isinstance(entry, dict):
        return None
    cluster_name = entry.get("cluster_name")
    if not isinstance(cluster_name, str) or not cluster_name.strip():
        return None
    return (
        cluster_name.strip(),
        entry.get("action"),
        _normalized_execution_log_issue_ids(entry),
    )


def _normalized_execution_log_issue_ids(entry: dict[str, Any]) -> list[str]:
    return [
        issue_id
        for raw_id in entry.get("issue_ids", [])
        if (issue_id := _normalize_cluster_issue_id(raw_id)) is not None
    ]


def _apply_execution_log_cluster_action(
    members: dict[str, list[str]],
    hash_lookup: dict[str, str],
    *,
    cluster_name: str,
    action: object,
    issue_ids: list[str],
) -> None:
    if action == "cluster_remove":
        bucket = members.get(cluster_name, [])
        if bucket:
            remove_set = set(issue_ids)
            members[cluster_name] = [
                issue_id for issue_id in bucket if issue_id not in remove_set
            ]
        return
    if action in {"cluster_add", "cluster_create", "cluster_update"}:
        _append_execution_log_members(
            members,
            hash_lookup,
            cluster_name=cluster_name,
            issue_ids=issue_ids,
        )


def _append_execution_log_members(
    members: dict[str, list[str]],
    hash_lookup: dict[str, str],
    *,
    cluster_name: str,
    issue_ids: list[str],
) -> None:
    bucket = members.setdefault(cluster_name, [])
    seen = set(bucket)
    for issue_id in issue_ids:
        if issue_id in seen:
            continue
        seen.add(issue_id)
        bucket.append(issue_id)
        _record_execution_log_hash(hash_lookup, issue_id)


def _record_execution_log_hash(hash_lookup: dict[str, str], issue_id: str) -> None:
    parts = issue_id.split("::")
    if parts and _HEX_SUFFIX_RE.fullmatch(parts[-1]):
        hash_lookup[parts[-1]] = issue_id


def normalize_cluster_defaults(plan: dict[str, Any]) -> None:
    """Recover cluster memberships and normalize runtime defaults."""
    recovered_members, hash_lookup = _execution_log_cluster_members(plan)
    override_members = _override_cluster_members(plan)

    for cluster in plan["clusters"].values():
        if not isinstance(cluster, dict):
            continue
        if not isinstance(cluster.get("issue_ids"), list):
            cluster["issue_ids"] = []
        cluster["issue_ids"] = _normalized_cluster_issue_ids(
            cluster,
            recovered_members=recovered_members,
            override_members=override_members,
            hash_lookup=hash_lookup,
        )
        cluster.setdefault("auto", False)
        cluster.setdefault("cluster_key", "")
        cluster.setdefault("action", None)
        cluster.setdefault("user_modified", False)
        normalize_cluster_semantics(cluster)


def _append_normalized_issue_id(
    raw_id: object,
    *,
    normalized_issue_ids: list[str],
    seen: set[str],
    hash_lookup: dict[str, str],
) -> None:
    issue_id = _normalize_cluster_issue_id(raw_id)
    if issue_id is None and isinstance(raw_id, str) and _HEX_SUFFIX_RE.fullmatch(raw_id):
        issue_id = hash_lookup.get(raw_id)
    if issue_id is None or issue_id in seen:
        return
    seen.add(issue_id)
    normalized_issue_ids.append(issue_id)


def _iter_cluster_raw_issue_ids(
    cluster: dict[str, Any],
    *,
    recovered_members: dict[str, list[str]],
    override_members: dict[str, list[str]],
) -> list[object]:
    raw_issue_ids: list[object] = list(cluster.get("issue_ids", []))

    cluster_name = cluster.get("name")
    if isinstance(cluster_name, str):
        raw_issue_ids.extend(recovered_members.get(cluster_name, []))
        raw_issue_ids.extend(override_members.get(cluster_name, []))
    return raw_issue_ids


def _normalized_cluster_issue_ids(
    cluster: dict[str, Any],
    *,
    recovered_members: dict[str, list[str]],
    override_members: dict[str, list[str]],
    hash_lookup: dict[str, str],
) -> list[str]:
    normalized_issue_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in _iter_cluster_raw_issue_ids(
        cluster,
        recovered_members=recovered_members,
        override_members=override_members,
    ):
        _append_normalized_issue_id(
            raw_id,
            normalized_issue_ids=normalized_issue_ids,
            seen=seen,
            hash_lookup=hash_lookup,
        )
    return normalized_issue_ids


__all__ = [
    "ensure_container_types",
    "normalize_cluster_defaults",
]
