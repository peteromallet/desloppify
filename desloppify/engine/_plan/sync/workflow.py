"""Workflow gate sync — inject workflow action items when preconditions are met."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def _refresh_state(plan: PlanModel) -> dict[str, Any]:
    refresh_state = plan.get("refresh_state")
    if not isinstance(refresh_state, dict):
        refresh_state = {}
        plan["refresh_state"] = refresh_state
    return refresh_state


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
) -> dict[str, Any]:
    provenance = {}
    if isinstance(import_payload, dict):
        raw_provenance = import_payload.get("provenance")
        if isinstance(raw_provenance, dict):
            provenance = raw_provenance
    recorded_file = (
        str(import_file).strip()
        if isinstance(import_file, str) and import_file.strip()
        else str(issues_only_audit.get("import_file", "")).strip()
        if isinstance(issues_only_audit, dict)
        else ""
    )
    timestamp = ""
    if isinstance(issues_only_audit, dict):
        timestamp = str(issues_only_audit.get("timestamp", "")).strip()
    return {
        "timestamp": timestamp,
        "import_file": recorded_file,
        "normalized_import_file": _normalize_match_path(recorded_file),
        "packet_sha256": str(provenance.get("packet_sha256", "")).strip(),
    }


def pending_import_scores_meta(
    plan: PlanModel,
    state: StateModel,
) -> dict[str, Any] | None:
    """Return normalized pending score-import metadata, if any."""
    ensure_plan_defaults(plan)
    refresh_state = _refresh_state(plan)
    meta = refresh_state.get(_PENDING_IMPORT_SCORES_KEY)
    if isinstance(meta, dict) and meta:
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
    meta: dict[str, Any] | None,
    *,
    import_file: str,
    import_payload: dict[str, Any],
) -> tuple[bool, str]:
    """Return (matches, reason) for whether the import matches the pending batch.

    Checks packet_sha256 first (strongest signal), falls back to normalized
    file path.  Returns a single human-readable reason on mismatch.
    """
    if not isinstance(meta, dict) or not meta:
        return True, ""

    provenance = import_payload.get("provenance")
    provenance_dict = provenance if isinstance(provenance, dict) else {}

    expected_hash = str(meta.get("packet_sha256", "")).strip()
    current_hash = str(provenance_dict.get("packet_sha256", "")).strip()
    if expected_hash and current_hash:
        if current_hash == expected_hash:
            return True, ""
        return False, f"expected packet_sha256 {expected_hash}, got {current_hash}"

    expected_file = str(meta.get("normalized_import_file", "")).strip()
    current_file = _normalize_match_path(import_file) or ""
    if expected_file and current_file and current_file != expected_file:
        return False, f"expected import file {meta.get('import_file')}, got {import_file}"

    return True, ""


def _clear_pending_import_scores(plan: PlanModel) -> None:
    order = plan["queue_order"]
    if WORKFLOW_IMPORT_SCORES_ID in order:
        order[:] = [item for item in order if item != WORKFLOW_IMPORT_SCORES_ID]
    refresh_state = _refresh_state(plan)
    refresh_state.pop(_PENDING_IMPORT_SCORES_KEY, None)


def _no_unscored(
    state: StateModel,
    policy: SubjectiveVisibility | None,
) -> bool:
    """Return True when no unscored (placeholder) subjective dimensions remain."""
    if policy is not None:
        return not policy.unscored_ids
    return not stale_policy_mod.current_unscored_ids(
        state, subjective_prefix=SUBJECTIVE_PREFIX,
    )


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

    Front-loads it into the workflow prefix so it stays ahead of triage.
    """
    ensure_plan_defaults(plan)
    order: list[str] = plan["queue_order"]

    if WORKFLOW_CREATE_PLAN_ID in order:
        return _EMPTY()
    if any(sid in order for sid in TRIAGE_IDS):
        return _EMPTY()
    if not _no_unscored(state, policy):
        return _EMPTY()

    if not has_objective_backlog(state, policy):
        return _EMPTY()

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
    refresh_state = _refresh_state(plan)
    pending_meta = refresh_state.get(_PENDING_IMPORT_SCORES_KEY)
    latest_issues_only = _latest_assessment_audit(state, modes={"issues_only"})
    latest_trusted = _latest_assessment_audit(state, modes=_TRUSTED_ASSESSMENT_MODES)

    stale_pending = False
    if WORKFLOW_IMPORT_SCORES_ID in order:
        if latest_issues_only is None:
            stale_pending = True
        elif latest_trusted is not None:
            latest_issues_ts = str(latest_issues_only.get("timestamp", "")).strip()
            latest_trusted_ts = str(latest_trusted.get("timestamp", "")).strip()
            pending_ts = ""
            if isinstance(pending_meta, dict):
                pending_ts = str(pending_meta.get("timestamp", "")).strip()
            compare_ts = pending_ts or latest_issues_ts
            if compare_ts and latest_trusted_ts and latest_trusted_ts >= compare_ts:
                stale_pending = True
    if stale_pending:
        _clear_pending_import_scores(plan)
        return QueueSyncResult(pruned=[WORKFLOW_IMPORT_SCORES_ID])

    if WORKFLOW_IMPORT_SCORES_ID in order:
        if assessment_mode == "issues_only":
            # Update metadata to track the latest issues-only batch
            refresh_state[_PENDING_IMPORT_SCORES_KEY] = _build_pending_import_scores_meta(
                import_file=import_file,
                import_payload=import_payload,
                issues_only_audit=latest_issues_only,
            )
            return QueueSyncResult(resurfaced=[WORKFLOW_IMPORT_SCORES_ID])
        return _EMPTY()
    if assessment_mode != "issues_only":
        return _EMPTY()
    result = _inject(plan, WORKFLOW_IMPORT_SCORES_ID)
    refresh_state[_PENDING_IMPORT_SCORES_KEY] = _build_pending_import_scores_meta(
        import_file=import_file,
        import_payload=import_payload,
        issues_only_audit=latest_issues_only,
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
    scores_just_imported: bool = False,
    current_scores: ScoreSnapshot | None = None,
) -> QueueSyncResult:
    """Inject ``workflow::communicate-score`` and rebaseline scores.

    Injects when:
    - All initial subjective reviews are complete (no unscored dims), OR
      scores were just imported (trusted/attested/override)
    - ``workflow::communicate-score`` is not already in the queue
    - Score has not already been communicated this cycle
      (``previous_plan_start_scores`` absent), unless a trusted score import
      explicitly refreshed the live score mid-cycle

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
    if "previous_plan_start_scores" in plan and not scores_just_imported:
        return _EMPTY()
    if not scores_just_imported and not _no_unscored(state, policy):
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
    "ScoreSnapshot",
    "import_scores_meta_matches",
    "pending_import_scores_meta",
    "sync_communicate_score_needed",
    "sync_create_plan_needed",
    "sync_import_scores_needed",
    "sync_score_checkpoint_needed",
]
