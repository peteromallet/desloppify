"""Stage-gate and fold-confirm helpers for triage completion."""

from __future__ import annotations

from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_triage import (
    TRIAGE_CMD_ORGANIZE,
    TRIAGE_STAGE_LABELS,
    compute_triage_progress,
)

from .enrich_checks import _underspecified_steps
from ..review_coverage import manual_clusters_with_issues
from ..stages.helpers import unenriched_clusters
from .stage_policy import (
    AutoConfirmStageRequest,
    confirm_stage,
)


_COMPLETE_AUTO_CONFIRM_STAGE_CONFIG = {
    "organize": {
        "label": "Organize",
        "blocked_heading": "Cannot complete: organize stage not confirmed.",
        "confirm_cmd": "desloppify plan triage --confirm organize",
        "inline_hint": "Or pass --attestation to auto-confirm organize inline.",
    },
    "enrich": {
        "label": "Enrich",
        "blocked_heading": "Cannot complete: enrich stage not confirmed.",
        "confirm_cmd": "desloppify plan triage --confirm enrich",
        "inline_hint": "Or pass --attestation to auto-confirm enrich inline.",
    },
    "sense-check": {
        "label": "Sense-check",
        "blocked_heading": "Cannot complete: sense-check stage not confirmed.",
        "confirm_cmd": "desloppify plan triage --confirm sense-check",
        "inline_hint": "Or pass --attestation to auto-confirm sense-check inline.",
    },
}


def _manual_cluster_names(plan: dict) -> list[str]:
    return [name for name, cluster in plan.get("clusters", {}).items() if not cluster.get("auto")]


def _first_missing_recorded_stage(stages: dict, *, through_stage: str) -> str | None:
    progress = compute_triage_progress(stages)
    recorded = {stage.name: stage.recorded for stage in progress.stages}
    for stage_name, _label in TRIAGE_STAGE_LABELS:
        if not recorded.get(stage_name, False):
            return stage_name
        if stage_name == through_stage:
            return None
    return None


def _auto_confirm_stage_for_complete(
    *,
    plan: dict,
    stages: dict,
    stage: str,
    attestation: str | None,
    save_plan_fn=None,
) -> bool:
    stage_record = stages.get(stage)
    if stage_record is None:
        return False

    config = _COMPLETE_AUTO_CONFIRM_STAGE_CONFIG[stage]
    return confirm_stage(
        plan=plan,
        stage_record=stage_record,
        attestation=attestation,
        request=AutoConfirmStageRequest(
            stage_name=stage,
            stage_label=config["label"],
            blocked_heading=config["blocked_heading"],
            confirm_cmd=config["confirm_cmd"],
            inline_hint=config["inline_hint"],
            cluster_names=_manual_cluster_names(plan),
        ),
        save_plan_fn=save_plan_fn,
    )


def _require_enrich_stage_for_complete(
    *,
    plan: dict,
    meta: dict,
    stages: dict,
    underspec: list[tuple[str, int, int]] | None = None,
) -> bool:
    missing = _first_missing_recorded_stage(stages, through_stage="enrich")
    if missing is None:
        return True
    if missing != "enrich":
        return _require_organize_stage_for_complete(plan=plan, meta=meta, stages=stages)

    if underspec is None:
        underspec = _underspecified_steps(plan)
    if underspec:
        print(colorize("  Cannot complete: enrich stage not done.", "red"))
        print(colorize(f"  {len(underspec)} cluster(s) have underspecified steps (missing detail or issue_refs):", "yellow"))
        for name, bare, total in underspec[:5]:
            print(colorize(f"    {name}: {bare}/{total} steps need enrichment", "yellow"))
        print(colorize('  Fix: desloppify plan cluster update <name> --update-step N --detail "sub-details"', "dim"))
        print(colorize('  Then: desloppify plan triage --stage enrich --report "..."', "dim"))
    else:
        print(colorize("  Cannot complete: enrich stage not recorded.", "red"))
        print(colorize("  Steps look enriched. Record the stage:", "dim"))
        print(colorize('    desloppify plan triage --stage enrich --report "..."', "dim"))
    return False


def _auto_confirm_enrich_for_complete(
    *,
    plan: dict,
    stages: dict,
    attestation: str | None,
    save_plan_fn=None,
    underspec: list[tuple[str, int, int]] | None = None,
) -> bool:
    if "enrich" not in stages:
        return False

    if underspec is None:
        underspec = _underspecified_steps(plan)
    if underspec:
        total_bare = sum(n for _, n, _ in underspec)
        print(colorize(f"  Cannot auto-confirm enrich: {total_bare} step(s) still lack detail or issue_refs.", "red"))
        for name, bare, total in underspec[:5]:
            print(colorize(f"    {name}: {bare}/{total} steps", "yellow"))
        print(colorize('  Fix: desloppify plan cluster update <name> --update-step N --detail "sub-details"', "dim"))
        return False

    return _auto_confirm_stage_for_complete(
        plan=plan,
        stages=stages,
        stage="enrich",
        attestation=attestation,
        save_plan_fn=save_plan_fn,
    )


def _require_sense_check_stage_for_complete(
    *,
    plan: dict,
    meta: dict,
    stages: dict,
) -> bool:
    missing = _first_missing_recorded_stage(stages, through_stage="sense-check")
    if missing is None:
        return True
    if missing != "sense-check":
        return _require_enrich_stage_for_complete(plan=plan, meta=meta, stages=stages)

    print(colorize("  Cannot complete: sense-check stage not recorded.", "red"))
    print(colorize('  Run: desloppify plan triage --stage sense-check --report "..."', "dim"))
    return False


def _require_organize_stage_for_complete(
    *,
    plan: dict,
    meta: dict,
    stages: dict,
) -> bool:
    missing = _first_missing_recorded_stage(stages, through_stage="organize")
    if missing is None:
        return True
    if missing == "strategize":
        print(colorize("  Cannot complete: strategize stage not done yet.", "red"))
        print(colorize('  Start with: desloppify plan triage --stage strategize --report "{...}"', "dim"))
        return False
    if missing == "observe":
        print(colorize("  Cannot complete: no stages done yet.", "red"))
        print(colorize('  Start with: desloppify plan triage --stage observe --report "..."', "dim"))
        return False

    print(colorize("  Cannot complete: organize stage not done.", "red"))
    gaps = unenriched_clusters(plan)
    if gaps:
        print(colorize(f"  {len(gaps)} cluster(s) still need enrichment:", "yellow"))
        for name, missing in gaps:
            print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
        print(colorize('  Fix: desloppify plan cluster update <name> --description "..." --steps "step1" "step2"', "dim"))
        print(colorize(f"  Then: {TRIAGE_CMD_ORGANIZE}", "dim"))
    else:
        manual = manual_clusters_with_issues(plan)
        if manual:
            print(colorize("  Clusters are enriched. Record the organize stage first:", "dim"))
            print(colorize(f"    {TRIAGE_CMD_ORGANIZE}", "dim"))
        else:
            print(colorize("  Create enriched clusters first, then record organize:", "dim"))
            print(colorize(f"    {TRIAGE_CMD_ORGANIZE}", "dim"))
    if meta.get("strategy_summary"):
        print(colorize('  Or fast-track: --confirm-existing --note "why plan is still valid" --strategy "..."', "dim"))
    return False


__all__ = [
    "_auto_confirm_enrich_for_complete",
    "_auto_confirm_stage_for_complete",
    "_require_enrich_stage_for_complete",
    "_require_organize_stage_for_complete",
    "_require_sense_check_stage_for_complete",
]
