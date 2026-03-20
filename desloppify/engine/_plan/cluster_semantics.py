"""Canonical semantic helpers for plan clusters.

Cluster behavior should be derived from explicit semantic metadata rather than
from command-string sniffing spread across queue assembly and rendering code.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from desloppify.base.registry import DETECTORS

ACTION_TYPE_AUTO_FIX = "auto_fix"
ACTION_TYPE_REFACTOR = "refactor"
ACTION_TYPE_MANUAL_FIX = "manual_fix"
ACTION_TYPE_REORGANIZE = "reorganize"
EXECUTION_STATUS_ACTIVE = "active"
EXECUTION_STATUS_REVIEW = "review"
EXECUTION_STATUS_DEFERRED = "deferred"
EXECUTION_STATUS_DONE = "done"
VALID_ACTION_TYPES = frozenset(
    {
        ACTION_TYPE_AUTO_FIX,
        ACTION_TYPE_REFACTOR,
        ACTION_TYPE_MANUAL_FIX,
        ACTION_TYPE_REORGANIZE,
    }
)

EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE = "ephemeral_autopromote"
EXECUTION_POLICY_PLANNED_ONLY = "planned_only"
VALID_EXECUTION_POLICIES = frozenset(
    {
        EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE,
        EXECUTION_POLICY_PLANNED_ONLY,
    }
)
VALID_EXECUTION_STATUSES = frozenset(
    {
        EXECUTION_STATUS_ACTIVE,
        EXECUTION_STATUS_REVIEW,
        EXECUTION_STATUS_DEFERRED,
        EXECUTION_STATUS_DONE,
    }
)


def _action_text(cluster: MutableMapping[str, Any] | dict[str, Any]) -> str:
    return str(cluster.get("action") or "").strip()


def infer_cluster_action_type(
    cluster: MutableMapping[str, Any] | dict[str, Any],
    *,
    detector: str = "",
) -> str:
    """Return the canonical action type for a cluster."""
    explicit = str(cluster.get("action_type") or "").strip()
    if explicit in VALID_ACTION_TYPES:
        return explicit

    action = _action_text(cluster)
    if action.startswith("desloppify autofix ") and "--dry-run" in action:
        return ACTION_TYPE_AUTO_FIX
    if action == "desloppify move":
        return ACTION_TYPE_REORGANIZE

    meta = DETECTORS.get(detector)
    if meta is not None:
        # Legacy safeguard: a detector may be auto-fixable in principle, but
        # if the stored action is not an autofix command, keep cluster handling
        # conservative and render it as refactor work.
        if meta.action_type == ACTION_TYPE_AUTO_FIX and action and (
            not action.startswith("desloppify autofix ")
            or "--dry-run" not in action
        ):
            return ACTION_TYPE_REFACTOR
        if meta.action_type in VALID_ACTION_TYPES:
            return meta.action_type

    return ACTION_TYPE_MANUAL_FIX


def infer_cluster_execution_policy(
    cluster: MutableMapping[str, Any] | dict[str, Any],
    *,
    detector: str = "",
) -> str:
    """Return how a cluster is allowed to surface in the execution queue."""
    explicit = str(cluster.get("execution_policy") or "").strip()
    if explicit in VALID_EXECUTION_POLICIES:
        return explicit
    # Registry auto_queue tag — primary path for new clusters.
    # When the detector is known, the registry is authoritative.
    if cluster.get("auto") and detector:
        meta = DETECTORS.get(detector)
        if meta is not None:
            if meta.auto_queue:
                return EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE
            return EXECUTION_POLICY_PLANNED_ONLY
    # String-sniffing fallback — handles old clusters without detector context.
    if (
        cluster.get("auto")
        and infer_cluster_action_type(cluster, detector=detector) == ACTION_TYPE_AUTO_FIX
    ):
        return EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE
    return EXECUTION_POLICY_PLANNED_ONLY


def infer_cluster_execution_status(
    cluster: MutableMapping[str, Any] | dict[str, Any],
) -> str:
    """Return whether the cluster is active queue work or review backlog."""
    explicit = str(cluster.get("execution_status") or "").strip()
    if explicit in VALID_EXECUTION_STATUSES:
        return explicit
    return EXECUTION_STATUS_REVIEW


def normalize_cluster_semantics(
    cluster: MutableMapping[str, Any],
    *,
    detector: str = "",
) -> bool:
    """Populate canonical semantic fields and report whether anything changed."""
    explicit_action_type = str(cluster.get("action_type") or "").strip()
    explicit_execution_policy = str(cluster.get("execution_policy") or "").strip()
    explicit_execution_status = str(cluster.get("execution_status") or "").strip()
    if (
        explicit_action_type not in VALID_ACTION_TYPES
        and explicit_execution_policy not in VALID_EXECUTION_POLICIES
        and explicit_execution_status not in VALID_EXECUTION_STATUSES
        and cluster.get("auto")
        and not detector
    ):
        action = _action_text(cluster)
        if action != "desloppify move" and not (
            action.startswith("desloppify autofix ") and "--dry-run" in action
        ):
            return False

    action_type = infer_cluster_action_type(cluster, detector=detector)
    execution_policy = infer_cluster_execution_policy(cluster, detector=detector)
    execution_status = infer_cluster_execution_status(cluster)
    changed = False
    if cluster.get("action_type") != action_type:
        cluster["action_type"] = action_type
        changed = True
    if cluster.get("execution_policy") != execution_policy:
        cluster["execution_policy"] = execution_policy
        changed = True
    if cluster.get("execution_status") != execution_status:
        cluster["execution_status"] = execution_status
        changed = True
    return changed


def cluster_allows_ephemeral_execution(
    cluster: MutableMapping[str, Any] | dict[str, Any],
    *,
    detector: str = "",
) -> bool:
    return bool(cluster.get("auto")) and (
        infer_cluster_execution_policy(cluster, detector=detector)
        == EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE
    )


def cluster_is_active(
    cluster: MutableMapping[str, Any] | dict[str, Any],
) -> bool:
    return infer_cluster_execution_status(cluster) == EXECUTION_STATUS_ACTIVE


def cluster_autofix_hint(
    cluster: MutableMapping[str, Any] | dict[str, Any],
    *,
    detector: str = "",
) -> str | None:
    """Return the autofix command to suggest for a cluster when semantically valid."""
    if infer_cluster_action_type(cluster, detector=detector) != ACTION_TYPE_AUTO_FIX:
        return None
    action = _action_text(cluster)
    return action or None


__all__ = [
    "ACTION_TYPE_AUTO_FIX",
    "ACTION_TYPE_MANUAL_FIX",
    "ACTION_TYPE_REFACTOR",
    "ACTION_TYPE_REORGANIZE",
    "EXECUTION_STATUS_ACTIVE",
    "EXECUTION_STATUS_DEFERRED",
    "EXECUTION_STATUS_DONE",
    "EXECUTION_STATUS_REVIEW",
    "EXECUTION_POLICY_EPHEMERAL_AUTOPROMOTE",
    "EXECUTION_POLICY_PLANNED_ONLY",
    "cluster_allows_ephemeral_execution",
    "cluster_autofix_hint",
    "cluster_is_active",
    "infer_cluster_action_type",
    "infer_cluster_execution_status",
    "infer_cluster_execution_policy",
    "normalize_cluster_semantics",
]
