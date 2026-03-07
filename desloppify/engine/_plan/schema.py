"""Plan schema types, defaults, and validation."""

from __future__ import annotations

from desloppify.base.compatibility import NotRequired, Required
from typing import Any, TypedDict

from desloppify.engine._plan.schema_migrations import (
    upgrade_plan_to_v8 as _upgrade_plan_to_v8,
)
from desloppify.engine._plan.skip_policy import VALID_SKIP_KINDS
from desloppify.engine._state.schema import utc_now

PLAN_VERSION = 8

EPIC_PREFIX = "epic/"
VALID_EPIC_DIRECTIONS = {
    "delete", "merge", "flatten", "enforce",
    "simplify", "decompose", "extract", "inline",
}


class SkipEntry(TypedDict, total=False):
    issue_id: Required[str]
    kind: Required[str]  # "temporary" | "permanent" | "false_positive"
    reason: str | None
    note: str | None  # required for permanent (wontfix note)
    attestation: str | None  # required for permanent/false_positive
    created_at: str
    review_after: int | None  # re-surface after N scans (temporary only)
    skipped_at_scan: int  # state.scan_count when skipped


class ItemOverride(TypedDict, total=False):
    issue_id: Required[str]
    description: str | None
    note: str | None
    cluster: str | None
    created_at: str
    updated_at: str


class ActionStep(TypedDict, total=False):
    title: Required[str]        # Short summary, 1 line
    detail: str                 # Long description, paragraphs OK
    issue_refs: list[str]       # Issue ID suffixes this step addresses
    done: bool                  # Completion tracking (default False)


class Cluster(TypedDict, total=False):
    name: Required[str]
    description: str | None
    issue_ids: list[str]
    created_at: str
    updated_at: str
    auto: bool  # True for auto-generated clusters
    cluster_key: str  # Deterministic grouping key (for regeneration)
    action: str | None  # Primary resolution command/guidance text
    user_modified: bool  # True when user manually edits membership
    optional: bool
    thesis: str
    direction: str
    root_cause: str
    supersedes: list[str]
    dismissed: list[str]
    agent_safe: bool
    dependency_order: int
    action_steps: list[str | ActionStep]
    priority: int
    source_clusters: list[str]
    status: str
    triage_version: int


class CommitRecord(TypedDict, total=False):
    sha: Required[str]           # git commit SHA
    branch: str | None           # branch name
    issue_ids: list[str]       # issues included
    recorded_at: str             # ISO timestamp
    note: str | None             # user-provided rationale
    cluster_name: str | None     # cluster context


class ExecutionLogEntry(TypedDict, total=False):
    timestamp: Required[str]
    action: Required[str]  # "done", "skip", "unskip", "resolve", "reconcile", "cluster_done", "focus", "reset"
    issue_ids: list[str]
    cluster_name: str | None
    actor: str  # "user" | "system" | "agent"
    note: str | None
    detail: dict[str, Any]  # action-specific extra data


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


class PlanStartScores(TypedDict, total=False):
    """Frozen score snapshot captured when a plan cycle starts."""

    strict: float
    overall: float
    objective: float
    verified: float
    reset: bool


class TriageStagePayload(TypedDict, total=False):
    """Persisted payload for one triage stage checkpoint."""

    stage: str
    report: str
    cited_ids: list[str]
    timestamp: str
    issue_count: int
    recurring_dims: list[str]
    confirmed_at: str
    confirmed_text: str


class LastTriageSnapshot(TypedDict, total=False):
    """Archived triage stage state captured when triage is completed."""

    completed_at: str
    stages: dict[str, TriageStagePayload]
    strategy: str


class EpicTriageMeta(TypedDict, total=False):
    """Metadata persisted for the multi-stage triage flow."""

    triaged_ids: list[str]
    dismissed_ids: list[str]
    issue_snapshot_hash: str
    strategy_summary: str
    trigger: str
    version: int
    last_run: str
    last_completed_at: str
    triage_stages: dict[str, TriageStagePayload]
    stage_snapshot_hash: str
    stage_refresh_required: bool
    last_triage: LastTriageSnapshot


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
    promoted_ids: list[str]  # IDs user explicitly positioned via move_items()
    plan_start_scores: PlanStartScores
    execution_log: list[ExecutionLogEntry]
    epic_triage_meta: EpicTriageMeta
    commit_log: list[CommitRecord]
    uncommitted_issues: list[str]
    commit_tracking_branch: str | None
    completed_clusters: NotRequired[list[dict[str, Any]]]  # legacy snapshot key


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
        "promoted_ids": [],
        "plan_start_scores": {},
        "execution_log": [],
        "epic_triage_meta": {},
        "commit_log": [],
        "uncommitted_issues": [],
        "commit_tracking_branch": None,
    }


def ensure_plan_defaults(plan: dict[str, Any]) -> None:
    """Normalize a loaded plan to ensure all keys exist.

    Runtime contract is v8-only. Legacy payloads are upgraded in-place once.
    """
    defaults = empty_plan()
    for key, value in defaults.items():
        plan.setdefault(key, value)
    _upgrade_plan_to_v8(plan)


def triage_clusters(plan: dict[str, Any]) -> dict[str, Cluster]:
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
    "ActionStep",
    "EPIC_PREFIX",
    "EpicTriageMeta",
    "ExecutionLogEntry",
    "PLAN_VERSION",
    "Cluster",
    "CommitRecord",
    "ItemOverride",
    "LastTriageSnapshot",
    "PlanModel",
    "PlanStartScores",
    "SkipEntry",
    "SupersededEntry",
    "TriageStagePayload",
    "VALID_EPIC_DIRECTIONS",
    "VALID_SKIP_KINDS",
    "empty_plan",
    "ensure_plan_defaults",
    "triage_clusters",
    "validate_plan",
]
