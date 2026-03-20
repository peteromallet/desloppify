"""Plan schema types, defaults, and validation."""

from __future__ import annotations

from typing import Any, NotRequired, Required, TypedDict

from desloppify.engine._plan.constants import SYNTHETIC_PREFIXES
from desloppify.engine._plan.schema.migrations import (
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
    effort: str                 # "trivial" | "small" | "medium" | "large"
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
    action_type: str
    execution_policy: str
    execution_status: str
    user_modified: bool  # True when user manually edits membership
    optional: bool
    thesis: str
    direction: str
    root_cause: str
    supersedes: list[str]
    dismissed: list[str]
    agent_safe: bool
    dependency_order: int
    depends_on_clusters: list[str]
    action_steps: list[ActionStep]
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


class IssueDisposition(TypedDict, total=False):
    """Per-issue intent/history accumulated across triage stages.

    Observe writes verdict fields; reflect writes decision fields.
    NOT derived state — ``plan["clusters"]`` and ``plan["skipped"]`` remain
    authoritative for "what is actually true now."
    """

    # Observe writes (what did we find?):
    verdict: str  # "genuine" | "false positive" | "exaggerated" | "over engineering" | "not worth it"
    verdict_reasoning: str
    files_read: list[str]
    recommendation: str

    # Reflect writes (what should we do about it?):
    decision: str  # "cluster" | "skip"
    target: str  # cluster name or skip reason
    decision_source: str  # "observe_auto" (false-positive auto-skip) | "reflect" (strategy)


class ReflectDisposition(TypedDict, total=False):
    """One issue's disposition as declared by the reflect stage."""

    issue_id: Required[str]
    decision: Required[str]  # "cluster" | "permanent_skip"
    target: Required[str]  # cluster name or skip reason tag


class ReflectClusterBlueprint(TypedDict, total=False):
    """A cluster definition declared by the reflect stage."""

    name: Required[str]
    description: str
    priority_order: int
    depends_on: list[str]


class TriageStagePayload(TypedDict, total=False):
    """Persisted payload for one triage stage checkpoint."""

    stage: str
    report: str
    cited_ids: list[str]
    timestamp: str
    issue_count: int
    dimension_names: list[str]
    dimension_counts: dict[str, int]
    recurring_dims: list[str]
    confirmed_at: str
    confirmed_text: str
    assessments: list[dict[str, Any]]
    # Structured reflect contract (populated only for reflect stage)
    disposition_ledger: list[ReflectDisposition]
    cluster_blueprint: list[ReflectClusterBlueprint]


class StrategistBriefing(TypedDict, total=False):
    """Structured strategist output persisted before the triage stages."""

    computed_at: str
    lookback_scans: int
    focus_dimensions: list[dict[str, Any]]
    avoid_areas: list[dict[str, Any]]
    rework_warnings: list[dict[str, Any]]
    file_churn_hotspots: list[dict[str, Any]]
    stagnant_dimensions: list[str]
    debt_trend: str
    score_trend: str
    momentum_dimensions: list[str]
    executive_summary: str
    observe_guidance: str
    reflect_guidance: str
    organize_guidance: str
    sense_check_guidance: str
    anti_patterns: list[dict[str, Any]]


class LastTriageSnapshot(TypedDict, total=False):
    """Archived triage stage state captured when triage is completed."""

    completed_at: str
    stages: dict[str, TriageStagePayload]
    strategy: str


class EpicTriageMeta(TypedDict, total=False):
    """Metadata persisted for the multi-stage triage flow."""

    triaged_ids: list[str]
    active_triage_issue_ids: list[str]
    dismissed_ids: list[str]
    undispositioned_issue_ids: list[str]
    undispositioned_issue_count: int
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
    triage_defer_state: dict[str, Any]
    issue_dispositions: dict[str, IssueDisposition]
    triage_force_visible: bool
    strategist_briefing: StrategistBriefing


class RefreshState(TypedDict, total=False):
    """Metadata for the post-flight refresh pipeline."""

    lifecycle_phase: str
    postflight_scan_completed_at_scan_count: int
    pending_import_scores: dict[str, Any]


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
    promoted_ids: list[str]  # IDs explicitly promoted from backlog into the queue
    plan_start_scores: PlanStartScores
    previous_plan_start_scores: PlanStartScores
    refresh_state: RefreshState
    execution_log: list[ExecutionLogEntry]
    epic_triage_meta: EpicTriageMeta
    subjective_defer_meta: dict[str, Any]
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
        "refresh_state": {},
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
    subjective_defer_meta = plan.get("subjective_defer_meta")
    if isinstance(subjective_defer_meta, dict):
        subjective_defer_meta.pop("force_visible_ids", None)
    epic_triage_meta = plan.get("epic_triage_meta")
    if isinstance(epic_triage_meta, dict):
        epic_triage_meta.pop("triage_force_visible", None)


def triage_clusters(plan: dict[str, Any]) -> dict[str, Cluster]:
    """Return clusters whose name starts with ``EPIC_PREFIX``."""
    return {
        name: cluster
        for name, cluster in plan.get("clusters", {}).items()
        if name.startswith(EPIC_PREFIX)
    }


def live_planned_queue_ids(plan: dict[str, Any] | None) -> set[str]:
    """Return substantive live queue IDs sourced only from ``queue_order``.

    Overrides and clusters are ownership metadata — they must never expand
    the live queue.  Only explicit ``queue_order`` entries count.
    """
    if not isinstance(plan, dict):
        return set()
    skipped_ids = set(plan.get("skipped", {}).keys())
    return {
        str(issue_id)
        for issue_id in plan.get("queue_order", [])
        if isinstance(issue_id, str)
        and issue_id
        and issue_id not in skipped_ids
        and not any(issue_id.startswith(prefix) for prefix in SYNTHETIC_PREFIXES)
    }


def executable_objective_ids(
    all_objective_ids: set[str],
    plan: dict[str, Any] | None,
) -> set[str]:
    """Return objective IDs eligible for execution.

    Before the plan tracks any queue work at all, all objective IDs are
    implicitly executable. Once *any* queue items exist — including synthetic
    review/workflow/triage items — execution becomes queue-driven and only
    objective IDs explicitly present in ``plan["queue_order"]`` remain
    eligible for ``next``.
    """
    if not isinstance(plan, dict):
        return set(all_objective_ids)
    skipped_ids = set(plan.get("skipped", {}).keys())
    queued_ids = {
        issue_id
        for issue_id in plan.get("queue_order", [])
        if isinstance(issue_id, str)
        and issue_id
        and issue_id not in skipped_ids
    }
    live_queue_ids = live_planned_queue_ids(plan)
    queued_objective_ids = all_objective_ids & live_queue_ids
    if queued_objective_ids:
        return queued_objective_ids
    if not queued_ids:
        return set(all_objective_ids) - skipped_ids
    return set()


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
        if not isinstance(entry, dict):
            raise ValueError(f"plan.skipped[{fid!r}] must be an object")
        if "kind" not in entry:
            raise ValueError(f"plan.skipped[{fid!r}] missing required key 'kind'")
        kind = entry["kind"]
        if kind not in VALID_SKIP_KINDS:
            raise ValueError(
                f"Invalid skip kind {kind!r} for {fid}; must be one of {sorted(VALID_SKIP_KINDS)}"
            )


__all__ = [
    "ActionStep",
    "EPIC_PREFIX",
    "EpicTriageMeta",
    "IssueDisposition",
    "ExecutionLogEntry",
    "PLAN_VERSION",
    "Cluster",
    "CommitRecord",
    "ItemOverride",
    "LastTriageSnapshot",
    "PlanModel",
    "PlanStartScores",
    "RefreshState",
    "SkipEntry",
    "StrategistBriefing",
    "SupersededEntry",
    "TriageStagePayload",
    "VALID_EPIC_DIRECTIONS",
    "VALID_SKIP_KINDS",
    "empty_plan",
    "ensure_plan_defaults",
    "executable_objective_ids",
    "live_planned_queue_ids",
    "triage_clusters",
    "validate_plan",
]
