"""Workflow-specific synthetic work queue item builders."""

from __future__ import annotations

from desloppify.engine._work_queue.types import WorkQueueItem


def build_score_checkpoint_item(plan: dict, state: dict) -> WorkQueueItem | None:
    """Build a synthetic work item for ``workflow::score-checkpoint`` if queued."""
    from desloppify.engine._plan.stale_dimensions import WORKFLOW_SCORE_CHECKPOINT_ID

    if WORKFLOW_SCORE_CHECKPOINT_ID not in plan.get("queue_order", []):
        return None

    from desloppify import state as state_mod

    snapshot = state_mod.score_snapshot(state)
    strict = snapshot.strict if snapshot.strict is not None else 0.0
    plan_start = (plan.get("plan_start_scores") or {}).get("strict")
    delta = round(strict - plan_start, 1) if plan_start is not None else None
    delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if delta else ""

    return {
        "id": WORKFLOW_SCORE_CHECKPOINT_ID,
        "tier": 1,
        "confidence": "high",
        "detector": "workflow",
        "file": ".",
        "kind": "workflow_action",
        "summary": f"Score checkpoint: strict {strict:.1f}/100{delta_str}",
        "detail": {
            "strict": strict,
            "plan_start_strict": plan_start,
            "delta": delta,
        },
        "primary_command": (
            'desloppify plan triage --stage observe --report '
            '"Analysis of score and dimensions..."'
        ),
        "blocked_by": [],
        "is_blocked": False,
    }


def build_create_plan_item(plan: dict) -> WorkQueueItem | None:
    """Build a synthetic work item for ``workflow::create-plan`` if queued."""
    from desloppify.engine._plan.stale_dimensions import WORKFLOW_CREATE_PLAN_ID

    if WORKFLOW_CREATE_PLAN_ID not in plan.get("queue_order", []):
        return None

    return {
        "id": WORKFLOW_CREATE_PLAN_ID,
        "tier": 1,
        "confidence": "high",
        "detector": "workflow",
        "file": ".",
        "kind": "workflow_action",
        "summary": "Create prioritized plan from review results",
        "detail": {},
        "primary_command": (
            'desloppify plan triage --stage observe --report '
            '"Analysis of findings for plan creation..."'
        ),
        "blocked_by": [],
        "is_blocked": False,
    }


def build_import_scores_item(plan: dict, state: dict) -> WorkQueueItem | None:
    """Build a synthetic work item for ``workflow::import-scores`` if queued."""
    from desloppify.engine._plan.stale_dimensions import WORKFLOW_IMPORT_SCORES_ID

    if WORKFLOW_IMPORT_SCORES_ID not in plan.get("queue_order", []):
        return None

    return {
        "id": WORKFLOW_IMPORT_SCORES_ID,
        "tier": 1,
        "confidence": "high",
        "detector": "workflow",
        "file": ".",
        "kind": "workflow_action",
        "summary": "Import assessment scores with attestation",
        "detail": {
            "explanation": (
                "Review issues were imported but assessment scores were skipped "
                "(untrusted source). Re-import with attestation to update dimension scores."
            ),
        },
        "primary_command": (
            'desloppify review --import issues.json --attested-external '
            '--attest "I validated this review was completed without awareness '
            'of overall score and is unbiased."'
        ),
        "blocked_by": [],
        "is_blocked": False,
    }


def build_communicate_score_item(plan: dict, state: dict) -> WorkQueueItem | None:
    """Build a synthetic work item for ``workflow::communicate-score`` if queued."""
    from desloppify.engine._plan.stale_dimensions import WORKFLOW_COMMUNICATE_SCORE_ID

    if WORKFLOW_COMMUNICATE_SCORE_ID not in plan.get("queue_order", []):
        return None

    from desloppify import state as state_mod

    snapshot = state_mod.score_snapshot(state)
    strict = snapshot.strict if snapshot.strict is not None else 0.0
    plan_start = (plan.get("plan_start_scores") or {}).get("strict")
    delta = round(strict - plan_start, 1) if plan_start is not None else None
    delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if delta else ""

    return {
        "id": WORKFLOW_COMMUNICATE_SCORE_ID,
        "tier": 1,
        "confidence": "high",
        "detector": "workflow",
        "file": ".",
        "kind": "workflow_action",
        "summary": f"Communicate updated score to user: strict {strict:.1f}/100{delta_str}",
        "detail": {
            "strict": strict,
            "plan_start_strict": plan_start,
            "delta": delta,
        },
        "primary_command": (
            f'desloppify plan resolve "{WORKFLOW_COMMUNICATE_SCORE_ID}" '
            '--note "Score communicated" --confirm'
        ),
        "blocked_by": [],
        "is_blocked": False,
    }


__all__ = [
    "build_communicate_score_item",
    "build_create_plan_item",
    "build_import_scores_item",
    "build_score_checkpoint_item",
]
