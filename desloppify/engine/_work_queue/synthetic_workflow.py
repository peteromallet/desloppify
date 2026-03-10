"""Workflow-specific synthetic work queue item builders."""

from __future__ import annotations

import shlex

from desloppify.engine.plan_queue import (
    WORKFLOW_COMMUNICATE_SCORE_ID,
    WORKFLOW_CREATE_PLAN_ID,
    WORKFLOW_DEFERRED_DISPOSITION_ID,
    WORKFLOW_IMPORT_SCORES_ID,
    WORKFLOW_SCORE_CHECKPOINT_ID,
    pending_import_scores_meta,
)
from desloppify.engine.plan_triage import (
    triage_manual_stage_command,
    triage_run_stages_command,
    triage_runner_commands,
)
from desloppify.engine._work_queue.types import WorkQueueItem

_TRIAGE_STAGE_SPECS: tuple[tuple[str, str], ...] = (
    ("observe", "triage::observe"),
    ("reflect", "triage::reflect"),
    ("organize", "triage::organize"),
    ("enrich", "triage::enrich"),
    ("sense-check", "triage::sense-check"),
)


def _confirm_attestation_hint(stage: str) -> str:
    if stage == "observe":
        return "I have thoroughly reviewed..."
    if stage == "reflect":
        return "My strategy accounts for..."
    if stage == "organize":
        return "This plan is correct..."
    if stage == "enrich":
        return "Steps are executor-ready..."
    if stage == "sense-check":
        return "Content and structure verified..."
    return "..."


def _runner_planning_tools(
    *,
    only_stages: str | None = None,
    manual_fallback: str | None = None,
) -> list[dict[str, str]]:
    tools = [
        {"label": label, "command": command}
        for label, command in triage_runner_commands(only_stages=only_stages)
    ]
    if manual_fallback:
        tools.append({"label": "Manual fallback", "command": manual_fallback})
    tools.append({"label": "Dashboard", "command": "desloppify plan triage"})
    return tools


def _triage_progression_target(plan: dict) -> tuple[str | None, bool]:
    """Return current triage stage target and whether it requires confirmation."""
    meta = plan.get("epic_triage_meta", {})
    triage_stages = meta.get("triage_stages", {}) or {}
    for stage, _sid in _TRIAGE_STAGE_SPECS:
        stage_payload = triage_stages.get(stage)
        if isinstance(stage_payload, dict) and stage_payload and not stage_payload.get("confirmed_at"):
            return stage, True

    order = set(plan.get("queue_order", []))
    for stage, sid in _TRIAGE_STAGE_SPECS:
        if sid not in order:
            continue
        return stage, False

    if "triage::commit" in order:
        return "commit", False

    return None, False


def _create_plan_primary_command(plan: dict) -> str:
    stage, needs_confirm = _triage_progression_target(plan)
    if stage is None:
        return triage_run_stages_command()
    if needs_confirm:
        attestation = _confirm_attestation_hint(stage)
        return (
            f'desloppify plan triage --confirm {stage} '
            f'--attestation "{attestation}"'
        )
    if stage == "commit":
        return triage_run_stages_command()
    return triage_run_stages_command(only_stages=stage)


def _create_plan_planning_tools(plan: dict) -> list[dict[str, str]]:
    stage, needs_confirm = _triage_progression_target(plan)
    if needs_confirm:
        return []
    if stage == "commit":
        return _runner_planning_tools(
            manual_fallback=triage_manual_stage_command("commit"),
        )
    if stage:
        return _runner_planning_tools(
            only_stages=stage,
            manual_fallback=triage_manual_stage_command(stage),
        )
    return _runner_planning_tools(
        only_stages="observe",
        manual_fallback=triage_manual_stage_command("observe"),
    )


def build_score_checkpoint_item(plan: dict, state: dict) -> WorkQueueItem | None:
    """Build a synthetic work item for ``workflow::score-checkpoint`` if queued."""
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
            "planning_tools": _runner_planning_tools(
                only_stages="observe",
                manual_fallback=triage_manual_stage_command("observe"),
            ),
        },
        "primary_command": triage_run_stages_command(only_stages="observe"),
        "blocked_by": [],
        "is_blocked": False,
    }


def build_create_plan_item(plan: dict) -> WorkQueueItem | None:
    """Build a synthetic work item for ``workflow::create-plan`` if queued."""
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
        "detail": {
            "planning_tools": _create_plan_planning_tools(plan),
        },
        "primary_command": _create_plan_primary_command(plan),
        "blocked_by": [],
        "is_blocked": False,
    }


def build_import_scores_item(plan: dict, state: dict) -> WorkQueueItem | None:
    """Build a synthetic work item for ``workflow::import-scores`` if queued."""
    if WORKFLOW_IMPORT_SCORES_ID not in plan.get("queue_order", []):
        return None
    meta = pending_import_scores_meta(plan, state) or {}
    import_file = str(meta.get("import_file", "")).strip() or "issues.json"
    quoted_import_file = shlex.quote(import_file)
    packet_sha = str(meta.get("packet_sha256", "")).strip()
    explanation = (
        "Review issues were imported but assessment scores were skipped "
        "(untrusted source). Re-import the same batch with attestation to update dimension scores."
    )
    if import_file != "issues.json":
        explanation += f" Expected import file: `{import_file}`."
    if packet_sha:
        explanation += f" Expected packet sha256: `{packet_sha}`."

    return {
        "id": WORKFLOW_IMPORT_SCORES_ID,
        "tier": 1,
        "confidence": "high",
        "detector": "workflow",
        "file": ".",
        "kind": "workflow_action",
        "summary": "Import assessment scores with attestation",
        "detail": {
            "explanation": explanation,
            "expected_import_file": import_file,
            "packet_sha256": packet_sha,
        },
        "primary_command": (
            f"desloppify review --import {quoted_import_file} --attested-external "
            '--attest "I validated this review was completed without awareness '
            'of overall score and is unbiased."'
        ),
        "blocked_by": [],
        "is_blocked": False,
    }


def build_communicate_score_item(plan: dict, state: dict) -> WorkQueueItem | None:
    """Build a synthetic work item for ``workflow::communicate-score`` if queued."""
    if WORKFLOW_COMMUNICATE_SCORE_ID not in plan.get("queue_order", []):
        return None

    from desloppify import state as state_mod

    snapshot = state_mod.score_snapshot(state)
    strict = snapshot.strict if snapshot.strict is not None else 0.0

    # Use previous_plan_start_scores (stashed at rebaseline) for the delta
    # so the user sees old-baseline → current, not current → current.
    prev_start = (plan.get("previous_plan_start_scores") or {}).get("strict")
    if prev_start is None:
        prev_start = (plan.get("plan_start_scores") or {}).get("strict")
    delta = round(strict - prev_start, 1) if prev_start is not None else None
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
            "previous_plan_start_strict": prev_start,
            "delta": delta,
        },
        "primary_command": (
            f'desloppify plan resolve "{WORKFLOW_COMMUNICATE_SCORE_ID}" '
            '--note "Score communicated" --confirm'
        ),
        "blocked_by": [],
        "is_blocked": False,
    }


def _temporary_skipped_ids(plan: dict) -> list[str]:
    skipped = plan.get("skipped", {})
    if not isinstance(skipped, dict):
        return []
    deferred: list[str] = []
    for issue_id, entry in skipped.items():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("kind", "temporary")) == "temporary":
            deferred.append(str(issue_id))
    deferred.sort()
    return deferred


def _deferred_cluster_breakdown(
    plan: dict,
    deferred_ids: list[str],
) -> tuple[int, int]:
    deferred_set = set(deferred_ids)
    if not deferred_set:
        return 0, 0

    clusters = plan.get("clusters", {})
    if not isinstance(clusters, dict):
        return 0, len(deferred_ids)

    covered_by_cluster: set[str] = set()
    cluster_count = 0
    for cluster in clusters.values():
        if not isinstance(cluster, dict):
            continue
        issue_ids = cluster.get("issue_ids", [])
        if not isinstance(issue_ids, list):
            continue
        matched = {str(issue_id) for issue_id in issue_ids if str(issue_id) in deferred_set}
        if not matched:
            continue
        cluster_count += 1
        covered_by_cluster.update(matched)

    individual_count = len(deferred_set - covered_by_cluster)
    return cluster_count, individual_count


def build_deferred_disposition_item(plan: dict) -> WorkQueueItem | None:
    """Build a synthetic item prompting deferred backlog disposition."""
    deferred_ids = _temporary_skipped_ids(plan)
    if not deferred_ids:
        return None

    count = len(deferred_ids)
    cluster_count, individual_count = _deferred_cluster_breakdown(plan, deferred_ids)
    cluster_label = "cluster" if cluster_count == 1 else "clusters"
    individual_label = "item" if individual_count == 1 else "items"
    reactivate_cmd = 'desloppify plan unskip "*"'
    subset_reactivate_cmd = "desloppify plan unskip <cluster-or-id>"
    inspect_cmd = "desloppify plan queue --include-skipped"
    inspect_item_cmd = "desloppify show <cluster-or-id>"
    wontfix_cmd = (
        'desloppify plan skip --permanent "*" '
        '--note "<why this deferred work should stay wontfix>" '
        '--attest "I have actually reviewed these deferred items and I am not gaming the score by skipping them permanently." '
        "--confirm"
    )
    subset_wontfix_cmd = (
        "desloppify plan skip --permanent <cluster-or-id> "
        '--note "<why this deferred work should stay wontfix>" '
        '--attest "I have actually reviewed these deferred items and I am not gaming the score by skipping them permanently."'
    )

    return {
        "id": WORKFLOW_DEFERRED_DISPOSITION_ID,
        "tier": 1,
        "confidence": "high",
        "detector": "workflow",
        "file": ".",
        "kind": "workflow_action",
        "summary": (
            "Deferred backlog decision required: "
            f"{cluster_count} {cluster_label} + {individual_count} individual {individual_label} "
            "must be reactivated or marked wontfix."
        ),
        "detail": {
            "temporary_skipped_count": count,
            "deferred_cluster_count": cluster_count,
            "deferred_individual_count": individual_count,
            "reactivate_command": reactivate_cmd,
            "wontfix_command": wontfix_cmd,
            "planning_tools": [
                {
                    "label": "Review deferred backlog",
                    "command": inspect_cmd,
                },
                {
                    "label": "Inspect a specific cluster or item",
                    "command": inspect_item_cmd,
                },
                {
                    "label": "Reactivate a subset",
                    "command": subset_reactivate_cmd,
                },
                {
                    "label": "Mark a subset as permanent wontfix",
                    "command": subset_wontfix_cmd,
                },
            ],
            "decision_options": [
                {
                    "label": "Reactivate deferred work",
                    "command": reactivate_cmd,
                },
                {
                    "label": "Convert deferred work to wontfix",
                    "command": wontfix_cmd,
                },
            ],
        },
        "primary_command": reactivate_cmd,
        "blocked_by": [],
        "is_blocked": False,
    }


__all__ = [
    "build_communicate_score_item",
    "build_create_plan_item",
    "build_deferred_disposition_item",
    "build_import_scores_item",
    "build_score_checkpoint_item",
]
