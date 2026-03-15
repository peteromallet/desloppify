"""Workflow gate sync — inject workflow action items when preconditions are met."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.engine._plan.refresh_lifecycle import (
    subjective_review_completed_for_scan,
)
from desloppify.engine._plan.policy import stale as stale_policy_mod
from desloppify.engine._plan.constants import (
    SUBJECTIVE_PREFIX,
    TRIAGE_IDS,
    normalize_queue_workflow_and_triage_prefix,
    WORKFLOW_COMMUNICATE_SCORE_ID,
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_IMPORT_SCORES_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    QueueSyncResult,
)
from desloppify.engine._plan.schema import PlanModel, ensure_plan_defaults
from desloppify.engine._plan.policy.subjective import SubjectiveVisibility
from desloppify.engine._state.schema import StateModel

from .context import has_objective_backlog

_PENDING_IMPORT_SCORES_KEY = "pending_import_scores"
_TRUSTED_ASSESSMENT_MODES = {"trusted_internal", "attested_external"}


def _get_refresh_state(plan: PlanModel) -> dict[str, Any] | None:
    refresh_state = plan.get("refresh_state")
    return refresh_state if isinstance(refresh_state, dict) else None


def _ensure_refresh_state(plan: PlanModel) -> dict[str, Any]:
    refresh_state = plan.get("refresh_state")
    if not isinstance(refresh_state, dict):
        refresh_state = {}
        plan["refresh_state"] = refresh_state
    return refresh_state


@dataclass(frozen=True)
class PendingImportScoresMeta:
    """Normalized contract for the queued score-import workflow."""

    timestamp: str = ""
    import_file: str = ""
    normalized_import_file: str = ""
    packet_sha256: str = ""

    @classmethod
    def from_mapping(cls, raw: object) -> PendingImportScoresMeta | None:
        if not isinstance(raw, dict):
            return None
        meta = cls(
            timestamp=str(raw.get("timestamp", "")).strip(),
            import_file=str(raw.get("import_file", "")).strip(),
            normalized_import_file=str(raw.get("normalized_import_file", "")).strip(),
            packet_sha256=str(raw.get("packet_sha256", "")).strip(),
        )
        return (
            meta
            if any((meta.timestamp, meta.import_file, meta.packet_sha256))
            else None
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "timestamp": self.timestamp,
            "import_file": self.import_file,
            "normalized_import_file": self.normalized_import_file,
            "packet_sha256": self.packet_sha256,
        }


def _normalize_match_path(raw_path: object) -> str | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return str(Path(raw_path).expanduser().resolve(strict=False))


def _latest_assessment_audit(
    state: StateModel,
    *,
    modes: set[str],
) -> dict[str, Any] | None:
    audit = state.get("assessment_import_audit", [])
    if not isinstance(audit, list):
        return None
    for entry in reversed(audit):
        if not isinstance(entry, dict):
            continue
        mode = entry.get("mode")
        if isinstance(mode, str) and mode in modes:
            return entry
    return None


def _build_pending_import_scores_meta(
    *,
    import_file: str | None,
    import_payload: dict[str, Any] | None,
    issues_only_audit: dict[str, Any] | None,
) -> PendingImportScoresMeta:
    packet_sha256 = ""
    if isinstance(import_payload, dict):
        raw_provenance = import_payload.get("provenance")
        if isinstance(raw_provenance, dict):
            packet_sha256 = str(raw_provenance.get("packet_sha256", "")).strip()
    recorded_file = (
        str(import_file).strip()
        if isinstance(import_file, str) and import_file.strip()
        else (
            str(issues_only_audit.get("import_file", "")).strip()
            if isinstance(issues_only_audit, dict)
            else ""
        )
    )
    timestamp = ""
    if isinstance(issues_only_audit, dict):
        timestamp = str(issues_only_audit.get("timestamp", "")).strip()
    if not packet_sha256 and isinstance(issues_only_audit, dict):
        packet_sha256 = str(issues_only_audit.get("packet_sha256", "")).strip()
    return PendingImportScoresMeta(
        timestamp=timestamp,
        import_file=recorded_file,
        normalized_import_file=_normalize_match_path(recorded_file) or "",
        packet_sha256=packet_sha256,
    )


def pending_import_scores_meta(
    plan: PlanModel,
    state: StateModel,
) -> PendingImportScoresMeta | None:
    """Return queued score-import metadata without mutating the plan."""
    refresh_state = _get_refresh_state(plan)
    if refresh_state is not None:
        meta = PendingImportScoresMeta.from_mapping(
            refresh_state.get(_PENDING_IMPORT_SCORES_KEY)
        )
        if meta is not None:
            return meta
    issues_only_audit = _latest_assessment_audit(state, modes={"issues_only"})
    if issues_only_audit is None:
        return None
    return _build_pending_import_scores_meta(
        import_file=str(issues_only_audit.get("import_file", "")),
        import_payload=None,
        issues_only_audit=issues_only_audit,
    )


def import_scores_meta_matches(
    meta: PendingImportScoresMeta | dict[str, Any] | None,
    *,
    import_file: str,
    import_payload: dict[str, Any],
) -> tuple[bool, str]:
    """Return (matches, reason) for whether the import matches the pending batch.

    Checks packet_sha256 first (strongest signal), falls back to normalized
    file path.  Returns a single human-readable reason on mismatch.
    """
    normalized_meta = (
        meta
        if isinstance(meta, PendingImportScoresMeta)
        else PendingImportScoresMeta.from_mapping(meta)
    )
    if normalized_meta is None:
        return True, ""

    provenance = import_payload.get("provenance")
    provenance_dict = provenance if isinstance(provenance, dict) else {}

    expected_hash = normalized_meta.packet_sha256
    current_hash = str(provenance_dict.get("packet_sha256", "")).strip()
    if expected_hash and current_hash:
        if current_hash == expected_hash:
            return True, ""
        return False, f"expected packet_sha256 {expected_hash}, got {current_hash}"

    expected_file = normalized_meta.normalized_import_file
    current_file = _normalize_match_path(import_file) or ""
    if expected_file and current_file and current_file != expected_file:
        return (
            False,
            f"expected import file {normalized_meta.import_file}, got {import_file}",
        )

    return True, ""


def _clear_pending_import_scores(plan: PlanModel) -> None:
    order = plan["queue_order"]
    if WORKFLOW_IMPORT_SCORES_ID in order:
        order[:] = [item for item in order if item != WORKFLOW_IMPORT_SCORES_ID]
    refresh_state = _get_refresh_state(plan)
    if refresh_state is not None:
        refresh_state.pop(_PENDING_IMPORT_SCORES_KEY, None)


def _pending_compare_timestamp(
    pending_meta: PendingImportScoresMeta | None,
    latest_issues_only: dict[str, Any],
) -> str:
    if pending_meta is not None and pending_meta.timestamp:
        return pending_meta.timestamp
    return str(latest_issues_only.get("timestamp", "")).strip()


def _pending_import_scores_stale(
    *,
    order: list[str],
    pending_meta: PendingImportScoresMeta | None,
    latest_issues_only: dict[str, Any] | None,
    latest_trusted: dict[str, Any] | None,
) -> bool:
    if WORKFLOW_IMPORT_SCORES_ID not in order:
        return False
    if latest_issues_only is None:
        return True
    if latest_trusted is None:
        return False

    latest_trusted_ts = str(latest_trusted.get("timestamp", "")).strip()
    compare_ts = _pending_compare_timestamp(pending_meta, latest_issues_only)
    return bool(compare_ts and latest_trusted_ts and latest_trusted_ts >= compare_ts)


def _record_pending_import_scores(
    refresh_state: dict[str, Any],
    *,
    import_file: str | None,
    import_payload: dict[str, Any] | None,
    latest_issues_only: dict[str, Any] | None,
) -> None:
    refresh_state[_PENDING_IMPORT_SCORES_KEY] = _build_pending_import_scores_meta(
        import_file=import_file,
        import_payload=import_payload,
        issues_only_audit=latest_issues_only,
    ).to_dict()


def _no_unscored(
    state: StateModel,
    policy: SubjectiveVisibility | None,
) -> bool:
    """Return True when no unscored (placeholder) subjective dimensions remain."""
    if policy is not None:
        return not policy.unscored_ids
    return not stale_policy_mod.current_unscored_ids(
        state,
        subjective_prefix=SUBJECTIVE_PREFIX,
    )


def _subjective_review_current_for_cycle(
    plan: PlanModel,
    state: StateModel,
    *,
    policy: SubjectiveVisibility | None,
) -> bool:
    """Return True when the current cycle no longer owes subjective review."""
    if not _no_unscored(state, policy):
        return False

    refresh_state = _get_refresh_state(plan)
    if refresh_state is None:
        return True

    postflight_scan_count = refresh_state.get("postflight_scan_completed_at_scan_count")
    try:
        current_scan_count = int(state.get("scan_count", 0) or 0)
    except (TypeError, ValueError):
        current_scan_count = 0

    if postflight_scan_count != current_scan_count:
        return True

    if subjective_review_completed_for_scan(plan, scan_count=current_scan_count):
        return True

    if policy is not None:
        return not (policy.stale_ids or policy.under_target_ids)

    return True


def _inject(plan: PlanModel, item_id: str) -> QueueSyncResult:
    """Inject *item_id* into the workflow prefix and clear stale skip entries."""
    order = plan["queue_order"]
    if item_id not in order:
        order.append(item_id)
    normalize_queue_workflow_and_triage_prefix(order)
    skipped = plan.get("skipped", {})
    if isinstance(skipped, dict):
        skipped.pop(item_id, None)
    return QueueSyncResult(injected=[item_id])


def clear_score_communicated_sentinel(plan: PlanModel) -> None:
    """Clear the ``previous_plan_start_scores`` sentinel.

    Call this in import/scan pre-steps when a trusted import completes or
    a cycle boundary resets.  The sentinel gates ``sync_communicate_score_needed``
    — clearing it allows communicate-score to re-inject next cycle.
    """
    plan.pop("previous_plan_start_scores", None)


def clear_create_plan_sentinel(plan: PlanModel) -> None:
    """Clear the ``create_plan_resolved_this_cycle`` sentinel.

    Call this at the same cycle-boundary points as
    ``clear_score_communicated_sentinel`` so that ``sync_create_plan_needed``
    can re-inject ``workflow::create-plan`` in the next cycle.
    """
    plan.pop("create_plan_resolved_this_cycle", None)


_EMPTY = QueueSyncResult


def sync_score_checkpoint_needed(
    plan: PlanModel,
    state: StateModel,
    *,
    policy: SubjectiveVisibility | None = None,
) -> QueueSyncResult:
    """Inject ``workflow::score-checkpoint`` when all initial reviews complete.

    Injects when:
    - No unscored (placeholder) subjective dimensions remain
    - ``workflow::score-checkpoint`` is not already in the queue

    Front-loads it into the workflow prefix so it stays ahead of triage.
    """
    ensure_plan_defaults(plan)
    order: list[str] = plan["queue_order"]

    if WORKFLOW_SCORE_CHECKPOINT_ID in order:
        return _EMPTY()
    if not _no_unscored(state, policy):
        return _EMPTY()
    return _inject(plan, WORKFLOW_SCORE_CHECKPOINT_ID)


def sync_create_plan_needed(
    plan: PlanModel,
    state: StateModel,
    *,
    policy: SubjectiveVisibility | None = None,
) -> QueueSyncResult:
    """Inject ``workflow::create-plan`` when reviews complete + objective backlog exists.

    Only injects when:
    - No unscored (placeholder) subjective dimensions remain
    - At least one objective issue exists
    - ``workflow::create-plan`` is not already in the queue
    - No triage stages are pending
    - ``workflow::create-plan`` has not already been resolved this cycle

    Front-loads it into the workflow prefix so it stays ahead of triage.
    """
    ensure_plan_defaults(plan)
    order: list[str] = plan["queue_order"]

    if WORKFLOW_CREATE_PLAN_ID in order:
        return _EMPTY()
    # Already resolved this cycle — sentinel is set when injected and
    # cleared at cycle boundaries (force-rescan, score seeding, queue
    # drain, trusted import).
    if plan.get("create_plan_resolved_this_cycle"):
        return _EMPTY()
    if any(sid in order for sid in TRIAGE_IDS):
        return _EMPTY()
    if not _subjective_review_current_for_cycle(plan, state, policy=policy):
        return _EMPTY()

    if not has_objective_backlog(state, policy):
        return _EMPTY()

    plan["create_plan_resolved_this_cycle"] = True
    return _inject(plan, WORKFLOW_CREATE_PLAN_ID)


def sync_import_scores_needed(
    plan: PlanModel,
    state: StateModel,
    *,
    assessment_mode: str | None = None,
    import_file: str | None = None,
    import_payload: dict[str, Any] | None = None,
) -> QueueSyncResult:
    """Inject ``workflow::import-scores`` after issues-only import.

    Only injects when:
    - Assessment mode was ``issues_only`` (scores were skipped)
    - ``workflow::import-scores`` is not already in the queue

    Front-loads it into the workflow prefix so it stays ahead of triage.
    """
    ensure_plan_defaults(plan)
    order: list[str] = plan["queue_order"]
    refresh_state = _ensure_refresh_state(plan)
    pending_meta = PendingImportScoresMeta.from_mapping(
        refresh_state.get(_PENDING_IMPORT_SCORES_KEY)
    )
    latest_issues_only = _latest_assessment_audit(state, modes={"issues_only"})
    latest_trusted = _latest_assessment_audit(state, modes=_TRUSTED_ASSESSMENT_MODES)

    if _pending_import_scores_stale(
        order=order,
        pending_meta=pending_meta,
        latest_issues_only=latest_issues_only,
        latest_trusted=latest_trusted,
    ):
        _clear_pending_import_scores(plan)
        return QueueSyncResult(pruned=[WORKFLOW_IMPORT_SCORES_ID])

    if WORKFLOW_IMPORT_SCORES_ID in order:
        if assessment_mode == "issues_only":
            _record_pending_import_scores(
                refresh_state,
                import_file=import_file,
                import_payload=import_payload,
                latest_issues_only=latest_issues_only,
            )
            return QueueSyncResult(resurfaced=[WORKFLOW_IMPORT_SCORES_ID])
        return _EMPTY()
    if assessment_mode != "issues_only":
        return _EMPTY()
    result = _inject(plan, WORKFLOW_IMPORT_SCORES_ID)
    _record_pending_import_scores(
        refresh_state,
        import_file=import_file,
        import_payload=import_payload,
        latest_issues_only=latest_issues_only,
    )
    return result


class ScoreSnapshot:
    """Minimal score snapshot for rebaseline — avoids importing state.py."""

    __slots__ = ("strict", "overall", "objective", "verified")

    def __init__(
        self,
        *,
        strict: float | None,
        overall: float | None,
        objective: float | None,
        verified: float | None,
    ) -> None:
        self.strict = strict
        self.overall = overall
        self.objective = objective
        self.verified = verified


def sync_communicate_score_needed(
    plan: PlanModel,
    state: StateModel,
    *,
    policy: SubjectiveVisibility | None = None,
    current_scores: ScoreSnapshot | None = None,
) -> QueueSyncResult:
    """Inject ``workflow::communicate-score`` and rebaseline scores.

    Injects when:
    - All initial subjective reviews are complete (no unscored dims)
    - ``workflow::communicate-score`` is not already in the queue
    - Score has not already been communicated this cycle
      (``previous_plan_start_scores`` absent)

    When injected and *current_scores* is provided, ``plan_start_scores``
    is rebaselined to the current score so the score display unfreezes at
    the new value.  The previous baseline is preserved in
    ``previous_plan_start_scores`` so the communicate-score queue item can
    show the old → new delta — and so mid-cycle scans know not to
    re-inject.
    """
    ensure_plan_defaults(plan)
    order: list[str] = plan["queue_order"]

    if WORKFLOW_COMMUNICATE_SCORE_ID in order:
        return _EMPTY()
    # Already communicated this cycle — previous_plan_start_scores is set
    # at injection time and cleared at cycle boundaries.
    if "previous_plan_start_scores" in plan:
        return _EMPTY()
    if not _subjective_review_current_for_cycle(plan, state, policy=policy):
        return _EMPTY()

    if current_scores is not None:
        _rebaseline_plan_start_scores(plan, current_scores)
    # Set sentinel even when rebaseline was a no-op (no plan_start_scores
    # to rebaseline) so mid-cycle scans don't re-inject.
    if not plan.get("previous_plan_start_scores"):
        plan["previous_plan_start_scores"] = {}
    return _inject(plan, WORKFLOW_COMMUNICATE_SCORE_ID)


def _rebaseline_plan_start_scores(
    plan: PlanModel,
    scores: ScoreSnapshot,
) -> None:
    """Snapshot the current score as the new baseline, preserving the old one."""
    old_start = plan.get("plan_start_scores")
    if not isinstance(old_start, dict) or not old_start:
        return
    if scores.strict is None:
        return

    plan["previous_plan_start_scores"] = dict(old_start)
    plan["plan_start_scores"] = {
        "strict": scores.strict,
        "overall": scores.overall,
        "objective": scores.objective,
        "verified": scores.verified,
    }


__all__ = [
    "PendingImportScoresMeta",
    "ScoreSnapshot",
    "clear_create_plan_sentinel",
    "clear_score_communicated_sentinel",
    "import_scores_meta_matches",
    "pending_import_scores_meta",
    "sync_communicate_score_needed",
    "sync_create_plan_needed",
    "sync_import_scores_needed",
    "sync_score_checkpoint_needed",
]
