"""Completion strategy/policy validation helpers for triage workflow."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify.engine.plan_triage import TRIAGE_CMD_ORGANIZE
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_triage import extract_issue_citations

from ..display.dashboard import show_plan_summary
from ..review_coverage import (
    cluster_issue_ids,
    open_review_ids_from_state,
    triage_coverage,
)
from ..stages.helpers import (
    active_triage_issue_scope,
    scoped_manual_clusters_with_issues,
    triage_scoped_plan,
    unclustered_review_issues,
    unenriched_clusters,
)
from .completion_stages import (
    _auto_confirm_enrich_for_complete,
    _require_enrich_stage_for_complete,
    _require_organize_stage_for_complete,
    _require_sense_check_stage_for_complete,
)


@dataclass(frozen=True)
class CompletionReadiness:
    """Single completion-boundary verdict shared by command and runner paths."""

    ok: bool
    message: str = ""
    open_review_ids: frozenset[str] = frozenset()
    manual_clusters: tuple[str, ...] = ()
    organized: int = 0
    total: int = 0


def _resolve_strategy_input(
    strategy: str | None,
    *,
    meta: dict,
    has_only_additions: bool = False,
) -> str | None:
    if strategy:
        return strategy
    if has_only_additions:
        return "same"
    print(colorize("  --strategy is required.", "red"))
    existing = meta.get("strategy_summary", "")
    if existing:
        print(colorize(f"  Current strategy: {existing}", "dim"))
        print(colorize('  Use --strategy "same" to keep it, or provide a new summary.', "dim"))
    else:
        print(
            colorize(
                '  Provide --strategy "execution plan describing priorities, ordering, and verification approach"',
                "dim",
            )
        )
    return None


def _strategy_valid_or_error(
    strategy: str,
    *,
    include_guidance: bool,
) -> bool:
    if strategy.strip().lower() == "same":
        return True
    if len(strategy.strip()) >= 200:
        return True
    print(colorize(f"  Strategy too short: {len(strategy.strip())} chars (minimum 200).", "red"))
    if include_guidance:
        print(colorize("  The strategy should describe:", "dim"))
        print(colorize("    - Execution order and priorities", "dim"))
        print(colorize("    - What each cluster accomplishes", "dim"))
        print(colorize("    - How to verify the work is correct", "dim"))
    return False


def _completion_clusters_valid(plan: dict, state: dict | None = None) -> bool:
    return evaluate_completion_readiness(
        plan,
        state,
        require_confirmed_stages=False,
    ).ok


def _required_completion_stages_valid(stages: dict) -> tuple[bool, str]:
    """Validate that the triage completion stages are present and confirmed."""
    for required in ("strategize", "observe", "reflect", "organize", "enrich", "sense-check"):
        if required not in stages:
            return False, f"Stage {required} not recorded."
        if not stages[required].get("confirmed_at"):
            return False, f"Stage {required} not confirmed."
    return True, ""


def _validate_cluster_dependency_cycles(clusters: dict) -> tuple[bool, str]:
    """Reject self-referential cluster dependencies."""
    for name, cluster in clusters.items():
        deps = cluster.get("depends_on_clusters", [])
        if name in deps:
            return False, f"Cluster {name} depends on itself."
    return True, ""


def _find_all_trivial_clusters(clusters: dict) -> list[str]:
    """Return manual clusters whose action steps are all marked trivial."""
    trivial_clusters: list[str] = []
    for name, cluster in clusters.items():
        if cluster.get("auto") or not cluster_issue_ids(cluster):
            continue
        steps = cluster.get("action_steps") or []
        if steps and all(
            isinstance(step, dict) and step.get("effort") == "trivial"
            for step in steps
        ):
            trivial_clusters.append(name)
    return trivial_clusters


def evaluate_completion_readiness(
    plan: dict,
    state: dict | None,
    *,
    require_confirmed_stages: bool = False,
) -> CompletionReadiness:
    """Evaluate whether triage completion is ready from one owned boundary."""
    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    if require_confirmed_stages:
        ok, message = _required_completion_stages_valid(stages)
        if not ok:
            return CompletionReadiness(ok=False, message=message)

    triage_scope = active_triage_issue_scope(plan, state)
    in_scope_open_ids = (
        open_review_ids_from_state(state) if state is not None and triage_scope is None else (triage_scope or set())
    )
    if state is not None and not in_scope_open_ids:
        return CompletionReadiness(ok=True)

    manual_clusters = scoped_manual_clusters_with_issues(plan, state)
    if not manual_clusters:
        any_clusters = [
            name for name, cluster in plan.get("clusters", {}).items()
            if cluster_issue_ids(cluster)
        ]
        if not any_clusters:
            print(colorize("  Cannot complete: no clusters with issues exist.", "red"))
            print(colorize('  Create clusters: desloppify plan cluster create <name> --description "..."', "dim"))
            return CompletionReadiness(ok=False, message="No clusters with issues exist.")

    gaps = unenriched_clusters(plan, state)
    if gaps:
        print(colorize(f"  Cannot complete: {len(gaps)} cluster(s) still need enrichment.", "red"))
        for name, missing in gaps:
            print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
        print(colorize("  Small clusters (<5 issues) need at least 1 action step per issue.", "dim"))
        print(colorize('  Fix: desloppify plan cluster update <name> --description "..." --steps "step1" "step2"', "dim"))
        return CompletionReadiness(ok=False, message=f"{len(gaps)} cluster(s) still need enrichment.")

    unclustered = unclustered_review_issues(plan, state)
    if unclustered:
        print(colorize(f"  Cannot complete: {len(unclustered)} review issue(s) have no action plan.", "red"))
        for fid in unclustered[:5]:
            short = fid.rsplit("::", 2)[-2] if "::" in fid else fid
            print(colorize(f"    {short}", "yellow"))
        if len(unclustered) > 5:
            print(colorize(f"    ... and {len(unclustered) - 5} more", "yellow"))
        print(colorize("  Add to a cluster or wontfix each unclustered issue.", "dim"))
        return CompletionReadiness(
            ok=False,
            message=f"{len(unclustered)} review issue(s) not in any cluster.",
        )

    scoped_clusters = triage_scoped_plan(plan, state).get("clusters", {})
    ok, message = _validate_cluster_dependency_cycles(scoped_clusters)
    if not ok:
        return CompletionReadiness(ok=False, message=message)

    organized, total, _ = triage_coverage(plan, open_review_ids=in_scope_open_ids)
    trivial_clusters = _find_all_trivial_clusters(scoped_clusters)
    if trivial_clusters:
        names = ", ".join(sorted(trivial_clusters))
        return CompletionReadiness(
            ok=True,
            message=f"Advisory: all action steps are marked trivial in cluster(s): {names}",
            open_review_ids=frozenset(in_scope_open_ids),
            manual_clusters=tuple(manual_clusters),
            organized=organized,
            total=total,
        )

    return CompletionReadiness(
        ok=True,
        open_review_ids=frozenset(in_scope_open_ids),
        manual_clusters=tuple(manual_clusters),
        organized=organized,
        total=total,
    )


def _resolve_completion_strategy(strategy: str | None, *, meta: dict) -> str | None:
    return _resolve_strategy_input(strategy, meta=meta)


def _completion_strategy_valid(strategy: str) -> bool:
    return _strategy_valid_or_error(strategy, include_guidance=True)


def _require_prior_strategy_for_confirm(meta: dict) -> bool:
    if meta.get("strategy_summary", ""):
        return True
    print(colorize("  Cannot confirm existing: no prior triage has been completed.", "red"))
    print(colorize("  The full OBSERVE → REFLECT → ORGANIZE → COMMIT flow is required the first time.", "dim"))
    print(colorize(f"  Create and enrich clusters, then: {TRIAGE_CMD_ORGANIZE}", "dim"))
    return False


def _confirm_existing_stages_valid(*, stages: dict, has_only_additions: bool, si) -> bool:
    if has_only_additions:
        from ..stages.rendering import _print_new_issues_since_last  # noqa: PLC0415

        _print_new_issues_since_last(si)
        return True
    if "strategize" not in stages:
        print(colorize("  Cannot confirm existing: strategize stage not complete.", "red"))
        print(colorize("  You must review cross-cycle history first.", "dim"))
        print(colorize('  Run: desloppify plan triage --stage strategize --report "{...}"', "dim"))
        return False
    if "observe" not in stages:
        print(colorize("  Cannot confirm existing: observe stage not complete.", "red"))
        print(colorize("  You must read issues first.", "dim"))
        print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        return False
    if "reflect" not in stages:
        print(colorize("  Cannot confirm existing: reflect stage not complete.", "red"))
        print(colorize("  You must compare against completed work first.", "dim"))
        print(colorize('  Run: desloppify plan triage --stage reflect --report "..."', "dim"))
        return False
    return True


def _confirm_note_valid(note: str | None) -> bool:
    if not note:
        print(colorize("  --note is required for confirm-existing.", "red"))
        print(colorize('  Explain why the existing plan is still valid (min 100 chars).', "dim"))
        return False
    if len(note) < 100:
        print(colorize(f"  Note too short: {len(note)} chars (minimum 100).", "red"))
        return False
    return True


def _resolve_confirm_existing_strategy(
    strategy: str | None,
    *,
    has_only_additions: bool,
    meta: dict,
) -> str | None:
    return _resolve_strategy_input(
        strategy,
        meta=meta,
        has_only_additions=has_only_additions,
    )


def _confirm_strategy_valid(strategy: str) -> bool:
    return _strategy_valid_or_error(strategy, include_guidance=False)


def _confirmed_text_or_error(*, plan: dict, state: dict, confirmed: str | None) -> str | None:
    from ..confirmations.basic import MIN_ATTESTATION_LEN  # noqa: PLC0415

    if confirmed and len(confirmed.strip()) >= MIN_ATTESTATION_LEN:
        return confirmed.strip()
    print(colorize("  Current plan:", "bold"))
    show_plan_summary(plan, state)
    if confirmed:
        print(colorize(f"\n  --confirmed text too short ({len(confirmed.strip())} chars, min {MIN_ATTESTATION_LEN}).", "red"))
    print(colorize('\n  Add --confirmed "I validate this plan..." to proceed.', "dim"))
    return None


def _note_cites_new_issues_or_error(note: str, si) -> bool:
    new_ids = si.new_since_last
    if not new_ids:
        return True
    review_issues = getattr(si, "review_issues", getattr(si, "open_issues", {}))
    valid_ids = set(review_issues.keys())
    cited = extract_issue_citations(note, valid_ids)
    new_cited = cited & new_ids
    if new_cited:
        return True
    print(colorize("  Note must cite at least 1 new/changed issue.", "red"))
    print(colorize(f"  {len(new_ids)} new issue(s) since last triage:", "dim"))
    for fid in sorted(new_ids)[:5]:
        print(colorize(f"    {fid}", "dim"))
    if len(new_ids) > 5:
        print(colorize(f"    ... and {len(new_ids) - 5} more", "dim"))
    return False


__all__ = [
    "_auto_confirm_enrich_for_complete",
    "CompletionReadiness",
    "_completion_clusters_valid",
    "_completion_strategy_valid",
    "_confirm_existing_stages_valid",
    "_confirm_note_valid",
    "_confirm_strategy_valid",
    "_confirmed_text_or_error",
    "_note_cites_new_issues_or_error",
    "_require_enrich_stage_for_complete",
    "_require_organize_stage_for_complete",
    "_require_prior_strategy_for_confirm",
    "_require_sense_check_stage_for_complete",
    "_required_completion_stages_valid",
    "_resolve_completion_strategy",
    "_resolve_confirm_existing_strategy",
    "evaluate_completion_readiness",
]
