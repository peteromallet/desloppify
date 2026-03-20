"""Shared constants and helpers for plan internals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AUTO_PREFIX = "auto/"

SUBJECTIVE_PREFIX = "subjective::"
TRIAGE_ID = "triage::pending"  # deprecated, kept for migration

TRIAGE_PREFIX = "triage::"
TRIAGE_STAGE_IDS = (
    "triage::strategize",
    "triage::observe",
    "triage::reflect",
    "triage::organize",
    "triage::enrich",
    "triage::sense-check",
    "triage::commit",
)
# value-check was folded into sense-check as a subagent in v0.9.9.
# Old plan.json files may still contain triage_stages["value-check"] data;
# it is silently ignored because _TRIAGE_STAGE_NAMES no longer includes it.
TRIAGE_STAGE_SPECS = tuple(
    (stage_id.removeprefix("triage::"), stage_id) for stage_id in TRIAGE_STAGE_IDS
)
TRIAGE_STAGE_ORDER = {
    stage_name: index for index, (stage_name, _stage_id) in enumerate(TRIAGE_STAGE_SPECS)
}
TRIAGE_IDS = set(TRIAGE_STAGE_IDS)
_TRIAGE_STAGE_NAMES = {
    stage_id.removeprefix("triage::") for stage_id in TRIAGE_STAGE_IDS
}
WORKFLOW_CREATE_PLAN_ID = "workflow::create-plan"
WORKFLOW_SCORE_CHECKPOINT_ID = "workflow::score-checkpoint"
WORKFLOW_IMPORT_SCORES_ID = "workflow::import-scores"
WORKFLOW_COMMUNICATE_SCORE_ID = "workflow::communicate-score"
WORKFLOW_DEFERRED_DISPOSITION_ID = "workflow::deferred-disposition"
WORKFLOW_RUN_SCAN_ID = "workflow::run-scan"
WORKFLOW_PREFIX = "workflow::"
WORKFLOW_IDS = {
    WORKFLOW_IMPORT_SCORES_ID,
    WORKFLOW_COMMUNICATE_SCORE_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_DEFERRED_DISPOSITION_ID,
    WORKFLOW_RUN_SCAN_ID,
}
WORKFLOW_PRIORITY_ORDER = (
    WORKFLOW_DEFERRED_DISPOSITION_ID,
    WORKFLOW_RUN_SCAN_ID,
    WORKFLOW_IMPORT_SCORES_ID,
    WORKFLOW_COMMUNICATE_SCORE_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    WORKFLOW_CREATE_PLAN_ID,
)
STRATEGY_PREFIX = "strategy::"
SYNTHETIC_PREFIXES = ("triage::", "workflow::", "subjective::", "strategy::")


def is_synthetic_id(issue_id: str) -> bool:
    """Return True when a raw plan ID refers to synthetic queue work."""
    return any(issue_id.startswith(prefix) for prefix in SYNTHETIC_PREFIXES)


def is_workflow_id(issue_id: str) -> bool:
    """Return True when a raw plan ID is a workflow synthetic."""
    return issue_id.startswith(WORKFLOW_PREFIX)


def is_triage_id(issue_id: str) -> bool:
    """Return True when a raw plan ID is a triage synthetic."""
    return issue_id.startswith(TRIAGE_PREFIX)


@dataclass
class QueueSyncResult:
    """Unified result for all queue sync operations."""

    injected: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    resurfaced: list[str] = field(default_factory=list)
    deferred: bool = False

    @property
    def changes(self) -> int:
        return len(self.injected) + len(self.pruned) + len(self.resurfaced)


def _resolve_triage_stages(meta_or_stages: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the triage stages dict from meta or a raw stages dict."""
    if not isinstance(meta_or_stages, dict):
        return {}
    if "triage_stages" in meta_or_stages:
        raw = meta_or_stages.get("triage_stages")
        resolved = raw if isinstance(raw, dict) else {}
        return _apply_legacy_strategize_tolerance(resolved)
    candidate_names = {str(name) for name in meta_or_stages.keys()}
    if candidate_names and candidate_names.issubset(_TRIAGE_STAGE_NAMES):
        return _apply_legacy_strategize_tolerance(meta_or_stages)
    return {}


def _apply_legacy_strategize_tolerance(
    stages: dict[str, Any],
) -> dict[str, Any]:
    """Backfill strategize for legacy triage runs without mutating stored state."""
    if "strategize" in stages:
        return stages
    later_stages = ("observe", "reflect", "organize", "enrich", "sense-check", "commit")
    if not any(name in stages for name in later_stages):
        return stages
    cloned = dict(stages)
    cloned["strategize"] = {
        "stage": "strategize",
        "report": "(legacy: predates strategize stage)",
        "timestamp": "",
        "confirmed_at": "legacy",
        "confirmed_text": "auto-backfilled",
    }
    return cloned


def confirmed_triage_stage_names(meta_or_stages: dict[str, Any] | None) -> set[str]:
    """Return triage stage names with an explicit ``confirmed_at`` marker."""
    return {
        str(name)
        for name, payload in _resolve_triage_stages(meta_or_stages).items()
        if isinstance(payload, dict) and payload.get("confirmed_at")
    }


def recorded_unconfirmed_triage_stage_names(meta_or_stages: dict[str, Any] | None) -> set[str]:
    """Return recorded triage stage names that still need confirmation."""
    return {
        str(name)
        for name, payload in _resolve_triage_stages(meta_or_stages).items()
        if isinstance(payload, dict) and payload and not payload.get("confirmed_at")
    }


def normalize_queue_workflow_and_triage_prefix(queue_order: list[str]) -> None:
    """Keep workflow items ahead of triage, then preserve the rest as-is."""
    seen: set[str] = set()
    normalized: list[str] = []

    for issue_id in WORKFLOW_PRIORITY_ORDER:
        if issue_id in queue_order and issue_id not in seen:
            normalized.append(issue_id)
            seen.add(issue_id)

    for issue_id in queue_order:
        if issue_id.startswith(WORKFLOW_PREFIX) and issue_id not in seen:
            normalized.append(issue_id)
            seen.add(issue_id)

    for issue_id in TRIAGE_STAGE_IDS:
        if issue_id in queue_order and issue_id not in seen:
            normalized.append(issue_id)
            seen.add(issue_id)

    for issue_id in queue_order:
        if issue_id in seen:
            continue
        normalized.append(issue_id)
        seen.add(issue_id)

    queue_order[:] = normalized


__all__ = [
    "AUTO_PREFIX",
    "QueueSyncResult",
    "normalize_queue_workflow_and_triage_prefix",
    "confirmed_triage_stage_names",
    "is_synthetic_id",
    "is_triage_id",
    "is_workflow_id",
    "recorded_unconfirmed_triage_stage_names",
    "STRATEGY_PREFIX",
    "SUBJECTIVE_PREFIX",
    "SYNTHETIC_PREFIXES",
    "TRIAGE_IDS",
    "TRIAGE_PREFIX",
    "TRIAGE_STAGE_ORDER",
    "TRIAGE_STAGE_IDS",
    "TRIAGE_STAGE_SPECS",
    "WORKFLOW_COMMUNICATE_SCORE_ID",
    "WORKFLOW_DEFERRED_DISPOSITION_ID",
    "WORKFLOW_IDS",
    "WORKFLOW_CREATE_PLAN_ID",
    "WORKFLOW_PRIORITY_ORDER",
    "WORKFLOW_IMPORT_SCORES_ID",
    "WORKFLOW_PREFIX",
    "WORKFLOW_RUN_SCAN_ID",
    "WORKFLOW_SCORE_CHECKPOINT_ID",
]
