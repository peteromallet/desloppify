"""Historical plan schema upgrades applied during load."""

from __future__ import annotations

from typing import Any

from desloppify.engine._plan.schema.helpers import (
    _cleanup_synthesis_meta,
    _drop_legacy_plan_keys,
    _has_synthesis_artifacts,
    _migrate_action_steps_to_v8,
)
from desloppify.engine._plan.schema.normalize import (
    ensure_container_types,
    normalize_cluster_defaults,
)
from desloppify.engine._state.schema import utc_now

V7_SCHEMA_VERSION = 7
V8_SCHEMA_VERSION = 8


def _rename_key(d: dict, old: str, new: str) -> bool:
    if old not in d:
        return False
    d.setdefault(new, d.pop(old))
    return True


def migrate_deferred_to_skipped(plan: dict[str, Any]) -> None:
    """Migrate legacy deferred IDs into structured skip entries."""
    deferred: list[str] = plan["deferred"]
    skipped: dict[str, dict[str, Any]] = plan["skipped"]
    if not deferred:
        return

    now = utc_now()
    for issue_id in list(deferred):
        if issue_id in skipped:
            continue
        skipped[issue_id] = {
            "issue_id": issue_id,
            "kind": "temporary",
            "reason": None,
            "note": None,
            "attestation": None,
            "created_at": now,
            "review_after": None,
            "skipped_at_scan": 0,
        }
    deferred.clear()


def migrate_epics_to_clusters(plan: dict[str, Any]) -> None:
    """Migrate v3 top-level ``epics`` dict into ``clusters`` (v4 unification)."""
    epics = plan.pop("epics", None)
    if not isinstance(epics, dict) or not epics:
        return
    clusters = plan["clusters"]
    now = utc_now()
    for name, epic in epics.items():
        if not isinstance(epic, dict):
            continue
        if name in clusters:
            continue
        clusters[name] = {
            "name": name,
            "description": epic.get("thesis", ""),
            "issue_ids": epic.get("issue_ids", []),
            "auto": True,
            "cluster_key": f"epic::{name}",
            "action": f"desloppify plan focus {name}",
            "user_modified": False,
            "created_at": epic.get("created_at", now),
            "updated_at": epic.get("updated_at", now),
            "thesis": epic.get("thesis", ""),
            "direction": epic.get("direction", "simplify"),
            "root_cause": epic.get("root_cause", ""),
            "supersedes": epic.get("supersedes", []),
            "dismissed": epic.get("dismissed", []),
            "agent_safe": epic.get("agent_safe", False),
            "dependency_order": epic.get("dependency_order", 999),
            "action_steps": epic.get("action_steps", []),
            "source_clusters": epic.get("source_clusters", []),
            "status": epic.get("status", "pending"),
            "triage_version": epic.get("triage_version", epic.get("synthesis_version", 0)),
        }


def migrate_v5_to_v6(plan: dict[str, Any]) -> None:
    """Migrate v5 -> v6 unified queue IDs and plan gate."""
    # cycle-break: schema/version_upgrades.py -> constants
    from desloppify.engine._plan.constants import (
        TRIAGE_STAGE_IDS,
        WORKFLOW_CREATE_PLAN_ID,
    )

    order: list[str] = plan.get("queue_order", [])

    for legacy_pending in ("synthesis::pending", "triage::pending"):
        if legacy_pending in order:
            idx = order.index(legacy_pending)
            order.remove(legacy_pending)
            meta = plan.get("epic_triage_meta", plan.get("epic_synthesis_meta", {}))
            confirmed = set(meta.get("triage_stages", meta.get("synthesis_stages", {})).keys())
            stage_names = ("strategize", "observe", "reflect", "organize", "enrich", "sense-check", "commit")
            to_inject = [
                stage_id
                for stage_id, name in zip(TRIAGE_STAGE_IDS, stage_names, strict=False)
                if name not in confirmed and stage_id not in order
            ]
            for offset, stage_id in enumerate(to_inject):
                order.insert(idx + offset, stage_id)
            break

    if plan.pop("pending_plan_gate", False):
        if WORKFLOW_CREATE_PLAN_ID not in order:
            insert_at = 0
            for idx, issue_id in enumerate(order):
                if issue_id.startswith("triage::") or issue_id.startswith("synthesis::"):
                    insert_at = idx + 1
            order.insert(insert_at, WORKFLOW_CREATE_PLAN_ID)
    else:
        plan.pop("pending_plan_gate", None)


def migrate_synthesis_to_triage(plan: dict[str, Any]) -> None:
    """Migrate ``synthesis::*`` identifiers and metadata to ``triage::*``."""
    order: list[str] = plan.get("queue_order", [])
    for index, issue_id in enumerate(order):
        if issue_id.startswith("synthesis::"):
            order[index] = "triage::" + issue_id[len("synthesis::"):]

    skipped: dict = plan.get("skipped", {})
    for old_key in [key for key in skipped if key.startswith("synthesis::")]:
        new_key = "triage::" + old_key[len("synthesis::"):]
        entry = skipped.pop(old_key)
        if isinstance(entry, dict):
            entry["issue_id"] = new_key
        skipped[new_key] = entry

    meta = plan.pop("epic_synthesis_meta", None)
    if meta is not None:
        if isinstance(meta, dict):
            _rename_key(meta, "synthesis_stages", "triage_stages")
            _rename_key(meta, "synthesized_ids", "triaged_ids")
        plan["epic_triage_meta"] = meta

    for entry in skipped.values():
        if isinstance(entry, dict) and entry.get("kind") == "synthesized_out":
            entry["kind"] = "triaged_out"

    for cluster in plan.get("clusters", {}).values():
        if isinstance(cluster, dict):
            _rename_key(cluster, "synthesis_version", "triage_version")


def upgrade_plan_to_v7(plan: dict[str, Any]) -> bool:
    """Apply legacy migrations once and normalize onto v7-only keys."""
    changed = False
    original_version = plan.get("version", 1)
    if not isinstance(original_version, int):
        original_version = 1

    ensure_container_types(plan)
    meta = plan.get("epic_triage_meta")
    queue_order = plan.get("queue_order", [])
    skipped = plan.get("skipped", {})
    clusters = plan.get("clusters", {})
    has_synthesis_artifacts = _has_synthesis_artifacts(
        queue_order=queue_order,
        skipped=skipped,
        clusters=clusters,
        meta=meta,
    )

    needs_legacy_upgrade = (
        original_version < V7_SCHEMA_VERSION
        or bool(plan.get("deferred"))
        or "epics" in plan
        or "epic_synthesis_meta" in plan
        or "pending_plan_gate" in plan
        or "uncommitted_findings" in plan
        or has_synthesis_artifacts
    )

    if needs_legacy_upgrade:
        migrate_deferred_to_skipped(plan)
        migrate_epics_to_clusters(plan)
        migrate_v5_to_v6(plan)
        migrate_synthesis_to_triage(plan)
        changed = True

    normalize_cluster_defaults(plan)

    changed = _drop_legacy_plan_keys(
        plan,
        (
            "epics",
            "epic_synthesis_meta",
            "pending_plan_gate",
            "uncommitted_findings",
        ),
    ) or changed

    meta = plan.get("epic_triage_meta")
    if _cleanup_synthesis_meta(meta):
        changed = True

    if plan.get("version") != V7_SCHEMA_VERSION:
        plan["version"] = V7_SCHEMA_VERSION
        changed = True
    return changed


def upgrade_plan_to_v8(plan: dict[str, Any]) -> bool:
    """Apply v7 migrations then upgrade action steps to structured dicts."""
    changed = upgrade_plan_to_v7(plan)

    for cluster in plan.get("clusters", {}).values():
        if isinstance(cluster, dict) and _migrate_action_steps_to_v8(cluster):
            changed = True

    if plan.get("version") != V8_SCHEMA_VERSION:
        plan["version"] = V8_SCHEMA_VERSION
        changed = True
    return changed


__all__ = [
    "V7_SCHEMA_VERSION",
    "V8_SCHEMA_VERSION",
    "migrate_deferred_to_skipped",
    "migrate_epics_to_clusters",
    "migrate_synthesis_to_triage",
    "migrate_v5_to_v6",
    "upgrade_plan_to_v7",
    "upgrade_plan_to_v8",
]
