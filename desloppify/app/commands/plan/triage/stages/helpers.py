"""Stage-gate and coverage helpers for triage command handlers."""

from __future__ import annotations

from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.constants import is_synthetic_id
from desloppify.engine._plan.triage.protection import protected_review_issue_ids
from desloppify.engine._state.issue_semantics import (
    is_review_work_item,
)
from desloppify.engine.plan_triage import TRIAGE_IDS

from ..review_coverage import (
    active_triage_issue_ids,
    cluster_issue_ids,
    live_active_triage_issue_ids,
    manual_clusters_with_issues,
)


def _require_triage_pending(plan: dict, *, action: str) -> bool:
    """Require at least one triage stage ID to be present in queue for an action."""
    order = set(plan.get("queue_order", []))
    if order & TRIAGE_IDS:
        return True
    print(colorize(f"  No triage stage in the queue — nothing to {action}.", "yellow"))
    return False


def _validate_stage_report(
    report: str | None,
    *,
    stage: str,
    min_chars: int,
    missing_guidance: list[str] | None = None,
    short_guidance: list[str] | None = None,
) -> str | None:
    """Validate staged report presence/length and print consistent guidance."""
    if not report:
        print(colorize(f"  --report is required for --stage {stage}.", "red"))
        for line in missing_guidance or []:
            print(colorize(f"  {line}", "dim"))
        return None
    cleaned = report.strip()
    if len(cleaned) < min_chars:
        print(
            colorize(
                f"  Report too short: {len(cleaned)} chars (minimum {min_chars}).",
                "red",
            )
        )
        for line in short_guidance or []:
            print(colorize(f"  {line}", "dim"))
        return None
    return cleaned


def active_triage_issue_scope(
    plan: dict,
    state: dict | None = None,
) -> set[str] | None:
    """Return the active triage issue scope, or None when no scope is frozen.

    `None` means "do not scope" for legacy/non-triage flows.
    An empty set means a frozen triage run exists but none of its issues are live.
    """
    frozen = active_triage_issue_ids(plan, state)
    meta = plan.get("epic_triage_meta", {})
    has_explicit_scope = isinstance(meta, dict) and isinstance(
        meta.get("active_triage_issue_ids"), list
    )
    if not frozen:
        if has_explicit_scope:
            return set()
        return None
    if state is None:
        return frozen
    return live_active_triage_issue_ids(plan, state)


def scoped_manual_clusters_with_issues(
    plan: dict,
    state: dict | None = None,
) -> list[str]:
    """Return manual clusters relevant to the current triage session."""
    scope = active_triage_issue_scope(plan, state)
    clusters = plan.get("clusters", {})
    names = manual_clusters_with_issues(plan)
    if scope is None:
        return names
    return [
        name
        for name in names
        if set(cluster_issue_ids(clusters.get(name, {}))) & scope
    ]


def triage_scoped_plan(
    plan: dict,
    state: dict | None = None,
) -> dict:
    """Return a plan view filtered to the current triage session when active."""
    scope = active_triage_issue_scope(plan, state)
    if scope is None:
        return plan
    allowed = set(scoped_manual_clusters_with_issues(plan, state))
    return {
        **plan,
        "clusters": {
            name: cluster
            for name, cluster in plan.get("clusters", {}).items()
            if name in allowed
        },
    }


def unenriched_clusters(
    plan: dict,
    state: dict | None = None,
) -> list[tuple[str, list[str]]]:
    """Return clusters with issues that are missing required enrichment.

    Requirements:
    - Every cluster needs a description and at least one action_step.
    - Small clusters (< 5 issues) need at least 1 action step per issue,
      so each item has a concrete plan. Large clusters (>= 5) just need
      steps overall (cluster-level plan is sufficient).
    """
    gaps: list[tuple[str, list[str]]] = []
    clusters = plan.get("clusters", {})
    for name in scoped_manual_clusters_with_issues(plan, state):
        cluster = clusters.get(name, {})
        issue_ids = cluster_issue_ids(cluster)
        missing: list[str] = []
        if not cluster.get("description"):
            missing.append("description")
        steps = cluster.get("action_steps") or []
        issue_count = len(issue_ids)
        if not steps:
            missing.append("action_steps")
        elif issue_count < 5 and len(steps) < issue_count:
            missing.append(
                f"action_steps (have {len(steps)}, need >= {issue_count} for small cluster)"
            )
        if missing:
            gaps.append((name, missing))
    return gaps


def unclustered_review_issues(plan: dict, state: dict | None = None) -> list[str]:
    """Return review issue IDs that aren't in any manual cluster.

    When *state* is provided, uses open review/concerns issues from state
    (the canonical source). Falls back to scanning queue_order for backwards
    compatibility.
    """
    clusters = plan.get("clusters", {})
    clustered_ids: set[str] = set()
    for cluster in clusters.values():
        if not cluster.get("auto"):
            clustered_ids.update(cluster_issue_ids(cluster))
    skipped_ids = {
        fid for fid in (plan.get("skipped", {}) or {}).keys() if isinstance(fid, str)
    }
    protected_ids = protected_review_issue_ids(plan)

    if state is not None:
        # Only count review-type issues for ledger purposes — mechanical
        # defects are covered by cluster-level backlog decisions, not
        # per-item ledger entries.
        review_ids = [
            fid for fid, finding in (state.get("work_items") or state.get("issues", {})).items()
            if finding.get("status") == "open"
            and is_review_work_item(finding)
            and fid not in protected_ids
        ]
        frozen_ids = (plan.get("epic_triage_meta", {}) or {}).get("active_triage_issue_ids")
        if isinstance(frozen_ids, list) and frozen_ids:
            frozen_id_set = live_active_triage_issue_ids(plan, state)
            review_ids = [fid for fid in review_ids if fid in frozen_id_set]
    else:
        review_ids = [
            fid for fid in plan.get("queue_order", [])
            if not is_synthetic_id(fid)
            and (fid.startswith("review::") or fid.startswith("concerns::"))
            and fid not in protected_ids
        ]

    return [
        fid for fid in review_ids
        if fid not in clustered_ids and fid not in skipped_ids
    ]


def value_check_targets(plan: dict, state: dict | None = None) -> list[str]:
    """Return the current execution targets that value-check must judge once each."""
    targets = list(scoped_manual_clusters_with_issues(plan, state))
    targets.extend(unclustered_review_issues(plan, state))
    seen: set[str] = set()
    ordered: list[str] = []
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        ordered.append(target)
    return ordered
