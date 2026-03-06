"""Stage persistence helpers for triage command handlers."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine._plan.stale_dimensions import review_issue_snapshot_hash
from desloppify.engine.plan import save_plan
from desloppify.state import utc_now


def refresh_stage_snapshot(plan: dict, state: dict) -> None:
    """Mark stage progress as aligned with the current review-issue snapshot."""
    meta = plan.setdefault("epic_triage_meta", {})
    meta["stage_snapshot_hash"] = review_issue_snapshot_hash(state)
    meta["stage_refresh_required"] = False


def record_triage_stage(
    plan: dict,
    state: dict,
    *,
    stage: str,
    report: str,
    cited_ids: list[str],
    issue_count: int,
    extra: dict[str, object] | None = None,
    plan_path: Path | None = None,
) -> dict[str, object]:
    """Persist one stage payload, refresh snapshot metadata, and save the plan."""
    meta = plan.setdefault("epic_triage_meta", {})
    stages = meta.setdefault("triage_stages", {})
    payload: dict[str, object] = {
        "stage": stage,
        "report": report,
        "cited_ids": list(cited_ids),
        "timestamp": utc_now(),
        "issue_count": issue_count,
    }
    if extra:
        payload.update(extra)
    stages[stage] = payload
    refresh_stage_snapshot(plan, state)
    save_plan(plan, plan_path)
    return payload
