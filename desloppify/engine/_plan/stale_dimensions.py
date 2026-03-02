"""Sync subjective dimensions into the plan queue.

Two independent sync functions:

- **sync_unscored_dimensions** — prepend never-scored (placeholder) dimensions
  to the *front* of the queue unconditionally (onboarding priority).
- **sync_stale_dimensions** — append stale (previously-scored) dimensions to
  the *back* of the queue when no objective items remain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from desloppify.engine._plan.schema import PlanModel, ensure_plan_defaults
from desloppify.engine._state.schema import StateModel

SUBJECTIVE_PREFIX = "subjective::"
SYNTHESIS_ID = "synthesis::pending"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StaleDimensionSyncResult:
    """What changed during a stale-dimension sync."""

    injected: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)

    @property
    def changes(self) -> int:
        return len(self.injected) + len(self.pruned)


@dataclass
class UnscoredDimensionSyncResult:
    """What changed during an unscored-dimension sync."""

    injected: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)

    @property
    def changes(self) -> int:
        return len(self.injected) + len(self.pruned)


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def _current_stale_ids(state: StateModel) -> set[str]:
    """Return the set of ``subjective::<slug>`` IDs that are currently stale."""
    from desloppify.engine._work_queue.helpers import slugify
    from desloppify.engine.planning.scorecard_projection import (
        scorecard_subjective_entries,
    )

    dim_scores = state.get("dimension_scores", {}) or {}
    if not dim_scores:
        return set()

    stale: set[str] = set()
    for entry in scorecard_subjective_entries(state, dim_scores=dim_scores):
        if not entry.get("stale"):
            continue
        dim_key = entry.get("dimension_key", "")
        if dim_key:
            stale.add(f"{SUBJECTIVE_PREFIX}{slugify(dim_key)}")
    return stale


def _current_unscored_ids(state: StateModel) -> set[str]:
    """Return the set of ``subjective::<slug>`` IDs that are currently unscored (placeholder).

    Checks ``subjective_assessments`` directly because
    ``scorecard_subjective_entries`` filters out placeholder dimensions
    (they are hidden from the scorecard display).
    """
    from desloppify.engine._work_queue.helpers import slugify

    assessments = state.get("subjective_assessments")
    if not isinstance(assessments, dict) or not assessments:
        return set()

    unscored: set[str] = set()
    for dim_key, payload in assessments.items():
        if not isinstance(payload, dict):
            continue
        if not payload.get("placeholder"):
            continue
        if dim_key:
            unscored.add(f"{SUBJECTIVE_PREFIX}{slugify(dim_key)}")
    return unscored


# ---------------------------------------------------------------------------
# Unscored dimension sync (front of queue, unconditional)
# ---------------------------------------------------------------------------

def sync_unscored_dimensions(
    plan: PlanModel,
    state: StateModel,
) -> UnscoredDimensionSyncResult:
    """Keep the plan queue in sync with unscored (placeholder) subjective dimensions.

    1. **Prune** — remove ``subjective::*`` IDs from ``queue_order`` that are
       no longer unscored AND not stale (avoids pruning stale IDs — that is
       ``sync_stale_dimensions``' responsibility).
    2. **Inject** — unconditionally prepend currently-unscored IDs to the
       *front* of ``queue_order`` so initial reviews are the first priority.
    """
    ensure_plan_defaults(plan)
    result = UnscoredDimensionSyncResult()
    unscored_ids = _current_unscored_ids(state)
    stale_ids = _current_stale_ids(state)
    order: list[str] = plan["queue_order"]

    # --- Cleanup: prune subjective IDs that are no longer unscored --------
    # Only prune IDs that are neither unscored nor stale (stale sync owns those).
    to_remove: list[str] = [
        fid for fid in order
        if fid.startswith(SUBJECTIVE_PREFIX)
        and fid not in unscored_ids
        and fid not in stale_ids
    ]
    for fid in to_remove:
        order.remove(fid)
        result.pruned.append(fid)

    # --- Inject: prepend unscored IDs to front ----------------------------
    existing = set(order)
    for uid in reversed(sorted(unscored_ids)):
        if uid not in existing:
            order.insert(0, uid)
            result.injected.append(uid)

    return result


# ---------------------------------------------------------------------------
# Stale dimension sync (back of queue, conditional)
# ---------------------------------------------------------------------------

def sync_stale_dimensions(
    plan: PlanModel,
    state: StateModel,
) -> StaleDimensionSyncResult:
    """Keep the plan queue in sync with stale subjective dimensions.

    1. Remove any ``subjective::*`` IDs from ``queue_order`` that are no
       longer stale and not unscored (avoids pruning IDs owned by
       ``sync_unscored_dimensions``).
    2. If no objective items remain after cleanup, inject all currently-stale
       dimension IDs so the plan surfaces them as actionable work.
    """
    ensure_plan_defaults(plan)
    result = StaleDimensionSyncResult()
    stale_ids = _current_stale_ids(state)
    unscored_ids = _current_unscored_ids(state)
    order: list[str] = plan["queue_order"]

    # --- Cleanup: prune resolved subjective IDs --------------------------
    # Only prune IDs that are neither stale nor unscored.
    to_remove: list[str] = [
        fid for fid in order
        if fid.startswith(SUBJECTIVE_PREFIX)
        and fid not in stale_ids
        and fid not in unscored_ids
    ]
    for fid in to_remove:
        order.remove(fid)
        result.pruned.append(fid)

    # --- Inject: populate when no objective items remain -----------------
    has_real_items = any(fid for fid in order if not fid.startswith(SUBJECTIVE_PREFIX))
    if not has_real_items and stale_ids:
        existing = set(order)
        for sid in sorted(stale_ids):
            if sid not in existing:
                order.append(sid)
                result.injected.append(sid)

    return result


# ---------------------------------------------------------------------------
# Synthesis snapshot hash + sync
# ---------------------------------------------------------------------------

def review_finding_snapshot_hash(state: StateModel) -> str:
    """Hash open review finding IDs to detect changes.

    Returns empty string when there are no open review findings.
    """
    findings = state.get("findings", {})
    review_ids = sorted(
        fid for fid, f in findings.items()
        if f.get("status") == "open"
        and f.get("detector") in ("review", "concerns")
    )
    if not review_ids:
        return ""
    return hashlib.sha256("|".join(review_ids).encode()).hexdigest()[:16]


@dataclass
class SynthesisSyncResult:
    """What changed during a synthesis sync."""

    injected: bool = False
    pruned: bool = False

    @property
    def changes(self) -> int:
        return int(self.injected) + int(self.pruned)


def sync_synthesis_needed(
    plan: PlanModel,
    state: StateModel,
) -> SynthesisSyncResult:
    """Inject ``synthesis::pending`` at front of queue when review findings change.

    Never auto-prunes — only explicit completion (``_apply_completion``) removes it.
    """
    ensure_plan_defaults(plan)
    result = SynthesisSyncResult()
    order: list[str] = plan["queue_order"]
    meta = plan.get("epic_synthesis_meta", {})
    already_present = SYNTHESIS_ID in order

    current_hash = review_finding_snapshot_hash(state)
    last_hash = meta.get("finding_snapshot_hash", "")

    # If hash changed and not already present, inject at front
    if current_hash and current_hash != last_hash and not already_present:
        order.insert(0, SYNTHESIS_ID)
        result.injected = True

    # Never auto-prune: synthesis::pending is only removed by explicit completion

    return result


__all__ = [
    "SUBJECTIVE_PREFIX",
    "SYNTHESIS_ID",
    "StaleDimensionSyncResult",
    "SynthesisSyncResult",
    "UnscoredDimensionSyncResult",
    "_current_unscored_ids",
    "review_finding_snapshot_hash",
    "sync_stale_dimensions",
    "sync_synthesis_needed",
    "sync_unscored_dimensions",
]
