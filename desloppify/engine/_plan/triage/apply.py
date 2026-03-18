"""Plan mutation helpers for cluster triage."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.engine._plan.cluster_semantics import EXECUTION_STATUS_ACTIVE
from desloppify.engine._plan.policy.stale import review_issue_snapshot_hash
from desloppify.engine._plan.schema import (
    EPIC_PREFIX,
    Cluster,
    PlanModel,
    ensure_plan_defaults,
)
from desloppify.engine._plan.skip_policy import skip_kind_state_status
from desloppify.engine._state.issue_semantics import is_triage_finding
from desloppify.engine._state.schema import StateModel, ensure_state_defaults, utc_now

from .dismiss import dismiss_triage_issues
from .prompt import AutoClusterDecision, TriageResult


@dataclass
class TriageMutationResult:
    """What changed when triage was applied to the plan."""

    epics_created: int = 0
    epics_updated: int = 0
    epics_completed: int = 0
    issues_dismissed: int = 0
    issues_reassigned: int = 0
    strategy_summary: str = ""
    triage_version: int = 0
    dry_run: bool = False
    auto_clusters_promoted: int = 0
    auto_clusters_skipped: int = 0
    auto_clusters_broken_up: int = 0

    @property
    def clusters_created(self) -> int:
        return self.epics_created

    @property
    def clusters_updated(self) -> int:
        return self.epics_updated

    @property
    def clusters_completed(self) -> int:
        return self.epics_completed


def _epic_sort_key(epic_data: dict) -> int:
    return int(epic_data.get("dependency_order", 999))


def _normalized_epic_name(raw_name: str) -> str:
    return raw_name if raw_name.startswith(EPIC_PREFIX) else f"{EPIC_PREFIX}{raw_name}"


def _update_existing_epic_cluster(
    existing: Cluster,
    epic_data: dict,
    *,
    now: str,
    version: int,
) -> None:
    existing["thesis"] = epic_data["thesis"]
    existing["direction"] = epic_data["direction"]
    existing["root_cause"] = epic_data.get("root_cause", "")
    existing["issue_ids"] = epic_data["issue_ids"]
    existing["dismissed"] = epic_data.get("dismissed", [])
    existing["agent_safe"] = epic_data.get("agent_safe", False)
    existing["dependency_order"] = epic_data["dependency_order"]
    existing["action_steps"] = epic_data.get("action_steps", [])
    existing["execution_status"] = EXECUTION_STATUS_ACTIVE
    existing["updated_at"] = now
    existing["triage_version"] = version
    existing["description"] = epic_data["thesis"]
    # Don't overwrite in_progress status from agent
    if existing.get("status") != "in_progress":
        existing["status"] = epic_data.get("status", "pending")


def _create_epic_cluster(
    *,
    epic_name: str,
    epic_data: dict,
    now: str,
    version: int,
) -> Cluster:
    return {
        "name": epic_name,
        "description": epic_data["thesis"],
        "issue_ids": epic_data["issue_ids"],
        "auto": True,
        "cluster_key": f"epic::{epic_name}",
        "action": f"desloppify plan focus {epic_name}",
        "execution_status": EXECUTION_STATUS_ACTIVE,
        "user_modified": False,
        "created_at": now,
        "updated_at": now,
        # Epic fields
        "thesis": epic_data["thesis"],
        "direction": epic_data["direction"],
        "root_cause": epic_data.get("root_cause", ""),
        "supersedes": [],
        "dismissed": epic_data.get("dismissed", []),
        "agent_safe": epic_data.get("agent_safe", False),
        "dependency_order": epic_data["dependency_order"],
        "action_steps": epic_data.get("action_steps", []),
        "source_clusters": [],
        "status": epic_data.get("status", "pending"),
        "triage_version": version,
    }


def _upsert_triage_clusters(
    *,
    clusters: dict[str, Cluster],
    triage: TriageResult,
    now: str,
    version: int,
) -> tuple[int, int]:
    created = 0
    updated = 0
    for epic_data in sorted(triage.clusters, key=_epic_sort_key):
        raw_name = epic_data["name"]
        epic_name = _normalized_epic_name(raw_name)
        existing = clusters.get(epic_name)
        if existing and existing.get("thesis"):
            _update_existing_epic_cluster(existing, epic_data, now=now, version=version)
            updated += 1
            continue
        clusters[epic_name] = _create_epic_cluster(
            epic_name=epic_name,
            epic_data=epic_data,
            now=now,
            version=version,
        )
        created += 1
    return created, updated


def _reorder_queue_by_dependency(
    *,
    order: list[str],
    triage: TriageResult,
    dismissed_ids: list[str],
) -> None:
    epic_issue_ids: set[str] = set()
    epic_ordered_ids: list[str] = []
    dismissed_set = set(dismissed_ids)
    for epic_data in sorted(triage.clusters, key=_epic_sort_key):
        for fid in epic_data["issue_ids"]:
            if fid in epic_issue_ids or fid in dismissed_set:
                continue
            epic_issue_ids.add(fid)
            epic_ordered_ids.append(fid)

    non_epic_items = [fid for fid in order if fid not in epic_issue_ids]
    order.clear()
    order.extend(epic_ordered_ids)
    order.extend(non_epic_items)


def _set_triage_meta(
    *,
    plan: PlanModel,
    state: StateModel,
    triage: TriageResult,
    now: str,
    version: int,
    dismissed_ids: list[str],
    trigger: str,
) -> None:
    current_hash = review_issue_snapshot_hash(state)
    open_review_ids = sorted(
        fid
        for fid, issue in (state.get("work_items") or state.get("issues", {})).items()
        if issue.get("status") == "open"
        and is_triage_finding(issue)
    )

    plan["epic_triage_meta"] = {
        "triaged_ids": open_review_ids,
        "last_run": now,
        "version": version,
        "dismissed_ids": dismissed_ids,
        "issue_snapshot_hash": current_hash,
        "strategy_summary": triage.strategy_summary,
        "trigger": trigger,
    }


def _apply_auto_cluster_decisions(
    *,
    plan: PlanModel,
    decisions: list[AutoClusterDecision],
    order: list[str],
    now: str,
    version: int,
    result: TriageMutationResult,
) -> None:
    """Process auto_cluster_decisions from the triage result.

    - promote: add cluster issue IDs to queue_order
    - skip: mark the cluster as skipped in the plan
    - break_up: record the decision for downstream processing
    """
    clusters = plan["clusters"]

    for decision in decisions:
        cluster_name = decision.cluster
        cluster = clusters.get(cluster_name)
        if cluster is None:
            continue

        action = decision.action

        if action == "promote":
            issue_ids = cluster.get("issue_ids", [])
            existing_in_order = set(order)
            new_ids = [
                fid for fid in issue_ids
                if isinstance(fid, str) and fid not in existing_in_order
            ]
            # Determine insertion position based on priority hint
            priority = (decision.priority or "").lower().strip()
            if priority == "first":
                for i, fid in enumerate(new_ids):
                    order.insert(i, fid)
            elif priority.startswith("after "):
                target = priority[len("after "):]
                insert_idx = len(order)
                for idx, item in enumerate(order):
                    if target in item:
                        insert_idx = idx + 1
                        break
                for i, fid in enumerate(new_ids):
                    order.insert(insert_idx + i, fid)
            elif priority.startswith("before "):
                target = priority[len("before "):]
                insert_idx = len(order)
                for idx, item in enumerate(order):
                    if target in item:
                        insert_idx = idx
                        break
                for i, fid in enumerate(new_ids):
                    order.insert(insert_idx + i, fid)
            else:
                # "last" or unrecognized: append to end
                order.extend(new_ids)

            cluster["execution_status"] = EXECUTION_STATUS_ACTIVE
            cluster["updated_at"] = now
            cluster["triage_version"] = version
            result.auto_clusters_promoted += 1

        elif action == "skip":
            cluster["triage_skip"] = {
                "reason": decision.reason,
                "skipped_at": now,
                "triage_version": version,
            }
            cluster["updated_at"] = now
            result.auto_clusters_skipped += 1

        elif action == "defer":
            cluster["triage_defer"] = {
                "reason": decision.reason,
                "decided_at": now,
                "triage_version": version,
            }
            cluster["execution_status"] = "deferred"
            cluster["updated_at"] = now
            result.auto_clusters_skipped += 1

        elif action == "break_up":
            cluster["triage_break_up"] = {
                "reason": decision.reason,
                "sub_clusters": decision.sub_clusters,
                "decided_at": now,
                "triage_version": version,
            }
            cluster["updated_at"] = now
            result.auto_clusters_broken_up += 1


def apply_triage_to_plan(
    plan: PlanModel,
    state: StateModel,
    triage: TriageResult,
    *,
    trigger: str = "manual",
) -> TriageMutationResult:
    """Apply parsed triage result to the living plan.

    1. Creates/updates triage clusters in plan["clusters"]
    2. Marks dismissed issues as triaged_out skips
    3. Reorders queue_order to group cluster members by dependency_order
    4. Updates epic_triage_meta with snapshot hash
    """
    ensure_plan_defaults(plan)
    ensure_state_defaults(state)
    now = utc_now()
    result = TriageMutationResult()
    result.strategy_summary = triage.strategy_summary

    clusters = plan["clusters"]
    skipped: dict = plan["skipped"]
    order: list[str] = plan["queue_order"]
    meta = plan.get("epic_triage_meta", {})
    version = int(meta.get("version", 0)) + 1
    result.triage_version = version

    created, updated = _upsert_triage_clusters(
        clusters=clusters,
        triage=triage,
        now=now,
        version=version,
    )
    result.epics_created += created
    result.epics_updated += updated

    dismissed_ids, dismiss_count = dismiss_triage_issues(
        triage=triage,
        order=order,
        skipped=skipped,
        now=now,
        version=version,
        scan_count=int(state.get("scan_count", 0)),
    )
    result.issues_dismissed += dismiss_count

    # Sync state status for dismissed issues so state is authoritative.
    issues = (state.get("work_items") or state.get("issues", {}))
    triaged_out_status = skip_kind_state_status("triaged_out")
    for fid in dismissed_ids:
        issue = issues.get(fid)
        if issue and issue.get("status") == "open" and triaged_out_status:
            issue["status"] = triaged_out_status
            issue["note"] = f"Triaged out by epic triage v{version}"

    _reorder_queue_by_dependency(
        order=order,
        triage=triage,
        dismissed_ids=dismissed_ids,
    )

    # Process auto-cluster decisions (backward-compatible: no-op if empty)
    if triage.auto_cluster_decisions:
        _apply_auto_cluster_decisions(
            plan=plan,
            decisions=triage.auto_cluster_decisions,
            order=order,
            now=now,
            version=version,
            result=result,
        )

    _set_triage_meta(
        plan=plan,
        state=state,
        triage=triage,
        now=now,
        version=version,
        dismissed_ids=dismissed_ids,
        trigger=trigger,
    )
    plan["updated"] = now

    return result

__all__ = ["TriageMutationResult", "apply_triage_to_plan"]
