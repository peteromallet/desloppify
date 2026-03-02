"""Plan schema types, defaults, and validation."""

from __future__ import annotations

from typing import Any, Required, TypedDict

from desloppify.engine._state.schema import utc_now

PLAN_VERSION = 4

VALID_SKIP_KINDS = {"temporary", "permanent", "false_positive", "synthesized_out"}

EPIC_PREFIX = "epic/"
VALID_EPIC_DIRECTIONS = {
    "delete", "merge", "flatten", "enforce",
    "simplify", "decompose", "extract", "inline",
}


class SkipEntry(TypedDict, total=False):
    finding_id: Required[str]
    kind: Required[str]  # "temporary" | "permanent" | "false_positive"
    reason: str | None
    note: str | None  # required for permanent (wontfix note)
    attestation: str | None  # required for permanent/false_positive
    created_at: str
    review_after: int | None  # re-surface after N scans (temporary only)
    skipped_at_scan: int  # state.scan_count when skipped


class ItemOverride(TypedDict, total=False):
    finding_id: Required[str]
    description: str | None
    note: str | None
    cluster: str | None
    created_at: str
    updated_at: str


class Cluster(TypedDict, total=False):
    name: Required[str]
    description: str | None
    finding_ids: list[str]
    created_at: str
    updated_at: str
    auto: bool  # True for auto-generated clusters
    cluster_key: str  # Deterministic grouping key (for regeneration)
    action: str | None  # Primary resolution command/guidance text
    user_modified: bool  # True when user manually edits membership


class SupersededEntry(TypedDict, total=False):
    original_id: Required[str]
    original_detector: str
    original_file: str
    original_summary: str
    status: str  # "superseded" | "remapped" | "dismissed"
    superseded_at: str
    remapped_to: str | None
    candidates: list[str]
    note: str | None


class PlanModel(TypedDict, total=False):
    version: Required[int]
    created: Required[str]
    updated: Required[str]
    queue_order: list[str]
    deferred: list[str]  # kept empty for migration compat
    skipped: dict[str, SkipEntry]
    active_cluster: str | None
    overrides: dict[str, ItemOverride]
    clusters: dict[str, Cluster]
    superseded: dict[str, SupersededEntry]
    plan_start_scores: dict  # frozen score snapshot from plan creation cycle
    epic_synthesis_meta: dict  # synthesis engine metadata


def empty_plan() -> PlanModel:
    """Return a new empty plan payload."""
    now = utc_now()
    return {
        "version": PLAN_VERSION,
        "created": now,
        "updated": now,
        "queue_order": [],
        "deferred": [],
        "skipped": {},
        "active_cluster": None,
        "overrides": {},
        "clusters": {},
        "superseded": {},
        "plan_start_scores": {},
        "epic_synthesis_meta": {},
    }


def _ensure_container_types(plan: dict[str, Any]) -> None:
    if not isinstance(plan.get("queue_order"), list):
        plan["queue_order"] = []
    if not isinstance(plan.get("deferred"), list):
        plan["deferred"] = []
    if not isinstance(plan.get("skipped"), dict):
        plan["skipped"] = {}
    if not isinstance(plan.get("overrides"), dict):
        plan["overrides"] = {}
    if not isinstance(plan.get("clusters"), dict):
        plan["clusters"] = {}
    if not isinstance(plan.get("superseded"), dict):
        plan["superseded"] = {}
    if not isinstance(plan.get("plan_start_scores"), dict):
        plan["plan_start_scores"] = {}
    if not isinstance(plan.get("epic_synthesis_meta"), dict):
        plan["epic_synthesis_meta"] = {}


def _migrate_deferred_to_skipped(plan: dict[str, Any]) -> None:
    deferred: list[str] = plan["deferred"]
    skipped: dict[str, SkipEntry] = plan["skipped"]
    if not deferred:
        return

    now = utc_now()
    for fid in list(deferred):
        if fid in skipped:
            continue
        skipped[fid] = {
            "finding_id": fid,
            "kind": "temporary",
            "reason": None,
            "note": None,
            "attestation": None,
            "created_at": now,
            "review_after": None,
            "skipped_at_scan": 0,
        }
    deferred.clear()


def _normalize_cluster_defaults(plan: dict[str, Any]) -> None:
    for cluster in plan["clusters"].values():
        if not isinstance(cluster, dict):
            continue
        if not isinstance(cluster.get("finding_ids"), list):
            cluster["finding_ids"] = []
        cluster.setdefault("auto", False)
        cluster.setdefault("cluster_key", "")
        cluster.setdefault("action", None)
        cluster.setdefault("user_modified", False)


def _migrate_epics_to_clusters(plan: dict[str, Any]) -> None:
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
            continue  # don't overwrite existing cluster
        clusters[name] = {
            "name": name,
            "description": epic.get("thesis", ""),
            "finding_ids": epic.get("finding_ids", []),
            "auto": True,
            "cluster_key": f"epic::{name}",
            "action": f"desloppify plan focus {name}",
            "user_modified": False,
            "created_at": epic.get("created_at", now),
            "updated_at": epic.get("updated_at", now),
            # Epic-specific fields
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
            "synthesis_version": epic.get("synthesis_version", 0),
        }


def ensure_plan_defaults(plan: dict[str, Any]) -> None:
    """Normalize a loaded plan to ensure all keys exist.

    Handles migration from v1 (deferred list) to v2 (skipped dict),
    and v3 (top-level epics) to v4 (epics unified into clusters).
    """
    defaults = empty_plan()
    for key, value in defaults.items():
        plan.setdefault(key, value)

    _ensure_container_types(plan)
    _migrate_deferred_to_skipped(plan)
    _migrate_epics_to_clusters(plan)
    _normalize_cluster_defaults(plan)


def synthesis_clusters(plan: dict[str, Any]) -> dict[str, Cluster]:
    """Return clusters whose name starts with ``EPIC_PREFIX``."""
    return {
        name: cluster
        for name, cluster in plan.get("clusters", {}).items()
        if name.startswith(EPIC_PREFIX)
    }


def validate_plan(plan: dict[str, Any]) -> None:
    """Raise ValueError when plan invariants are violated."""
    if not isinstance(plan.get("version"), int):
        raise ValueError("plan.version must be an int")
    if not isinstance(plan.get("queue_order"), list):
        raise ValueError("plan.queue_order must be a list")

    # No ID should appear in both queue_order and skipped
    skipped_ids = set(plan.get("skipped", {}).keys())
    overlap = set(plan["queue_order"]) & skipped_ids
    if overlap:
        raise ValueError(
            f"IDs cannot appear in both queue_order and skipped: {sorted(overlap)}"
        )

    # Validate skip entry kinds
    for fid, entry in plan.get("skipped", {}).items():
        kind = entry.get("kind")
        if kind not in VALID_SKIP_KINDS:
            raise ValueError(
                f"Invalid skip kind {kind!r} for {fid}; must be one of {sorted(VALID_SKIP_KINDS)}"
            )


__all__ = [
    "EPIC_PREFIX",
    "PLAN_VERSION",
    "Cluster",
    "ItemOverride",
    "PlanModel",
    "SkipEntry",
    "SupersededEntry",
    "VALID_EPIC_DIRECTIONS",
    "VALID_SKIP_KINDS",
    "empty_plan",
    "ensure_plan_defaults",
    "synthesis_clusters",
    "validate_plan",
]
