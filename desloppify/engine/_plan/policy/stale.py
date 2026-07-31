"""Canonical stale/unscored subjective policy helpers."""

from __future__ import annotations

import hashlib

from desloppify.base.config import DEFAULT_TARGET_STRICT_SCORE
from desloppify.engine._plan.triage.protection import protected_review_issue_ids
from desloppify.engine._state.schema import StateModel
from desloppify.engine._work_queue.helpers import slugify
from desloppify.engine.planning.scorecard_projection import all_subjective_entries


def open_review_ids(state: StateModel) -> set[str]:
    """Return IDs of open review/concerns issues from state.

    With the unified pipeline, ``is_triage_finding`` now includes mechanical
    defects. For staleness/snapshot purposes we still track only review-type
    issues — mechanical changes use threshold-based staleness via
    ``is_triage_stale``.
    """
    from desloppify.engine._state.issue_semantics import is_review_work_item
    return {
        fid
        for fid, f in (state.get("work_items") or state.get("issues", {})).items()
        if f.get("status") == "open" and is_review_work_item(f)
    }


def triage_open_review_ids(plan: dict, state: StateModel) -> set[str]:
    """Return open review IDs that are in automated triage scope.

    Explicitly protected IDs remain open in state.  They are excluded here so
    triage automation cannot re-inject or disposition a user-owned hold.
    """
    return open_review_ids(state) - protected_review_issue_ids(plan)


def open_mechanical_count(state: StateModel) -> int:
    """Return the count of open mechanical defects from state."""
    from desloppify.engine._state.issue_semantics import is_objective_finding
    return sum(
        1
        for f in (state.get("work_items") or state.get("issues", {})).values()
        if f.get("status") == "open" and is_objective_finding(f)
    )


def _subjective_entry_id(
    dimension_key: object,
    *,
    subjective_prefix: str,
) -> str:
    return f"{subjective_prefix}{slugify(str(dimension_key))}"


def _subjective_entries(state: StateModel) -> list[dict]:
    dim_scores = state.get("dimension_scores", {}) or {}
    if not dim_scores:
        return []
    return list(all_subjective_entries(state, dim_scores=dim_scores))


def _collect_subjective_entry_ids(
    entries: list[dict],
    *,
    subjective_prefix: str,
    predicate,
) -> set[str]:
    collected: set[str] = set()
    for entry in entries:
        dim_key = entry.get("dimension_key", "")
        if not dim_key or not predicate(entry):
            continue
        collected.add(_subjective_entry_id(dim_key, subjective_prefix=subjective_prefix))
    return collected


def current_stale_ids(
    state: StateModel,
    *,
    subjective_prefix: str = "subjective::",
) -> set[str]:
    """Return ``subjective::<slug>`` IDs that are currently stale."""
    return _collect_subjective_entry_ids(
        _subjective_entries(state),
        subjective_prefix=subjective_prefix,
        predicate=lambda entry: bool(entry.get("stale")),
    )


def _unscored_ids_from_assessments(
    assessments: dict,
    *,
    subjective_prefix: str,
) -> set[str]:
    unscored: set[str] = set()
    for dim_key, payload in assessments.items():
        if not isinstance(payload, dict) or not payload.get("placeholder") or not dim_key:
            continue
        unscored.add(_subjective_entry_id(dim_key, subjective_prefix=subjective_prefix))
    return unscored


def _unscored_ids_from_dimension_scores(
    entries: list[dict],
    *,
    subjective_prefix: str,
) -> set[str]:
    return _collect_subjective_entry_ids(
        entries,
        subjective_prefix=subjective_prefix,
        predicate=lambda entry: bool(entry.get("placeholder")),
    )


def current_unscored_ids(
    state: StateModel,
    *,
    subjective_prefix: str = "subjective::",
) -> set[str]:
    """Return ``subjective::<slug>`` IDs that are currently unscored."""
    assessments = state.get("subjective_assessments")
    if isinstance(assessments, dict) and assessments:
        return _unscored_ids_from_assessments(
            assessments,
            subjective_prefix=subjective_prefix,
        )
    return _unscored_ids_from_dimension_scores(
        _subjective_entries(state),
        subjective_prefix=subjective_prefix,
    )


def current_under_target_ids(
    state: StateModel,
    *,
    target_strict: float = DEFAULT_TARGET_STRICT_SCORE,
    subjective_prefix: str = "subjective::",
) -> set[str]:
    """Return under-target subjective IDs that are neither stale nor unscored."""
    entries = _subjective_entries(state)
    if not entries:
        return set()

    stale_ids = current_stale_ids(state, subjective_prefix=subjective_prefix)
    unscored_ids = current_unscored_ids(state, subjective_prefix=subjective_prefix)

    return {
        item_id
        for item_id in _collect_subjective_entry_ids(
            entries,
            subjective_prefix=subjective_prefix,
            predicate=lambda entry: (
                not entry.get("placeholder")
                and not entry.get("stale")
                and float(entry.get("strict", entry.get("score", 100.0))) < target_strict
            ),
        )
        if item_id not in stale_ids and item_id not in unscored_ids
    }


def review_issue_snapshot_hash(state: StateModel) -> str:
    """Hash open review/concerns issue IDs to detect triage-relevant changes."""
    review_ids = sorted(open_review_ids(state))
    if not review_ids:
        return ""
    return hashlib.sha256("|".join(review_ids).encode()).hexdigest()[:16]


def triage_review_issue_snapshot_hash(plan: dict, state: StateModel) -> str:
    """Hash only the review IDs that automated triage is allowed to process."""
    review_ids = sorted(triage_open_review_ids(plan, state))
    if not review_ids:
        return ""
    return hashlib.sha256("|".join(review_ids).encode()).hexdigest()[:16]


def compute_new_issue_ids(plan: dict, state: StateModel) -> set[str]:
    """Return open review/concerns IDs that appeared since the last triage."""
    meta = plan.get("epic_triage_meta", {})
    triaged = set(meta.get("triaged_ids", []))
    active = set(meta.get("active_triage_issue_ids", []))
    known = triaged | active
    return triage_open_review_ids(plan, state) - known if known else set()


def is_triage_stale(
    plan: dict,
    state: StateModel,
    *,
    mechanical_growth_threshold: float = 0.10,
) -> bool:
    """Return True when triage should be re-run.

    Stale when:
    - ANY new review issues appeared since last triage, OR
    - Mechanical defect count grew by more than *mechanical_growth_threshold*
      (default 10%) since last triage.

    The threshold prevents trivial scan changes from forcing full re-triage
    while still catching significant new mechanical findings.

    In-progress triage (confirmed stages + stage IDs in queue) is NOT
    considered stale — the lifecycle filter in the work queue already
    forces triage stages to the front.
    """
    meta = plan.get("epic_triage_meta", {})
    triaged_ids = set(meta.get("triaged_ids", []))
    active_ids = set(meta.get("active_triage_issue_ids", []))
    known = triaged_ids | active_ids

    # Any new review issue → stale
    if triage_open_review_ids(plan, state) - known:
        return True

    # Check mechanical growth threshold
    last_mechanical = meta.get("last_mechanical_count", 0)
    current_mechanical = open_mechanical_count(state)
    if last_mechanical > 0:
        growth = (current_mechanical - last_mechanical) / last_mechanical
        if growth > mechanical_growth_threshold:
            return True
    elif current_mechanical > 0 and not known:
        # First triage with mechanical issues
        return True

    return False


__all__ = [
    "compute_new_issue_ids",
    "current_stale_ids",
    "current_under_target_ids",
    "current_unscored_ids",
    "is_triage_stale",
    "open_mechanical_count",
    "open_review_ids",
    "review_issue_snapshot_hash",
    "triage_open_review_ids",
    "triage_review_issue_snapshot_hash",
]
