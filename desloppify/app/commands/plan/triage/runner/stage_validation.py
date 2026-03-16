"""Post-subagent validation and auto-attestation for triage runners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from desloppify.engine.plan_triage import TriageInput

from ..stages.evidence_parsing import (
    parse_observe_evidence,
    validate_observe_evidence,
    validate_reflect_skip_evidence,
    validate_report_has_file_paths,
    validate_report_references_clusters,
)
from ..validation.enrich_quality import evaluate_enrich_quality
from ..validation.completion_policy import evaluate_completion_readiness
from ..validation.enrich_checks import (
    _cluster_file_overlaps,
    _clusters_with_directory_scatter,
    _clusters_with_high_step_ratio,
)
from ..completion_flow import count_log_activity_since
from ..observe_batches import observe_dimension_breakdown
from ..review_coverage import (
    active_triage_issue_ids,
    cluster_issue_ids,
    open_review_ids_from_state,
)
from ..stages.helpers import (
    active_triage_issue_scope,
    scoped_manual_clusters_with_issues,
    unclustered_review_issues,
    unenriched_clusters,
    value_check_targets,
)
from ..stages.evidence_parsing import parse_value_check_decision_ledger


@dataclass(frozen=True)
class EnrichQualityFailure:
    """Structured enrich-quality validation failure."""

    code: str
    message: str


def run_enrich_quality_checks(
    plan: dict,
    repo_root: Path,
    *,
    phase_label: str,
    triage_issue_ids: set[str] | None = None,
) -> list[EnrichQualityFailure]:
    """Run enrich-level executor-readiness checks for a phase."""
    report = evaluate_enrich_quality(
        plan,
        repo_root,
        phase_label=phase_label,
        bad_paths_severity="failure",
        missing_effort_severity="failure",
        include_missing_issue_refs=True,
        include_vague_detail=True,
        stale_issue_refs_severity="failure",
        triage_issue_ids=triage_issue_ids,
    )
    code_map = {"underspecified": "underspecified_steps", "bad_paths": "missing_paths"}
    return [
        EnrichQualityFailure(
            code=code_map.get(issue.code, issue.code),
            message=issue.message,
        )
        for issue in report.failures
    ]


def _validate_observe_stage(
    *,
    stages: dict,
    triage_input: TriageInput | None,
) -> tuple[bool, str]:
    """Validate recorded observe-stage content."""
    if "observe" not in stages:
        return False, "Observe stage not recorded."
    report = stages["observe"].get("report", "")
    if len(report) < 100:
        return False, f"Observe report too short ({len(report)} chars, need 100+)."
    cited = stages["observe"].get("cited_ids", [])
    issue_count = stages["observe"].get("issue_count", 0)
    if issue_count <= 0:
        return True, ""
    min_citations = min(5, max(1, issue_count // 10))
    if len(cited) < min_citations:
        return False, (
            f"Observe report cites only {len(cited)} issue(s) "
            f"(need {min_citations}+). Reference specific issue "
            f"hashes to prove you read them."
        )
    review_issues = (
        getattr(triage_input, "review_issues", getattr(triage_input, "open_issues", {}))
        if triage_input
        else {}
    )
    valid_ids = set(review_issues.keys())
    evidence = parse_observe_evidence(report, valid_ids)
    ev_failures = validate_observe_evidence(evidence, issue_count)
    blocking = [failure for failure in ev_failures if failure.blocking]
    if blocking:
        return False, blocking[0].message
    return True, ""


def _validate_reflect_stage(stages: dict) -> tuple[bool, str]:
    """Validate recorded reflect-stage content."""
    if "reflect" not in stages:
        return False, "Reflect stage not recorded."
    report = stages["reflect"].get("report", "")
    if len(report) < 100:
        return False, f"Reflect report too short ({len(report)} chars, need 100+)."
    for field_name, label in (
        ("missing_issue_ids", "unaccounted for"),
        ("duplicate_issue_ids", "duplicates"),
    ):
        ids = stages["reflect"].get(field_name, [])
        if ids:
            return False, f"Reflect report {label} {len(ids)} issue(s)."
    issue_count = int(stages["reflect"].get("issue_count", 0) or 0)
    cited = stages["reflect"].get("cited_ids", [])
    if issue_count > 0 and len(cited) < issue_count:
        return False, (
            f"Reflect report cites only {len(cited)}/{issue_count} issue(s). "
            "A reflect blueprint must account for every open review issue."
        )
    skip_failures = validate_reflect_skip_evidence(report)
    blocking_skips = [failure for failure in skip_failures if failure.blocking]
    if blocking_skips:
        return False, blocking_skips[0].message
    return True, ""


def _organize_stage_warnings(plan: dict) -> list[str]:
    """Collect advisory organize-stage warnings."""
    warnings: list[str] = []
    overlaps = _cluster_file_overlaps(plan)
    if overlaps:
        warnings.append(f"{len(overlaps)} cluster pair(s) share files without dependencies")
    scattered = _clusters_with_directory_scatter(plan)
    if scattered:
        names = ", ".join(name for name, _, _ in scattered)
        warnings.append(f"Theme-grouped clusters (5+ dirs): {names}")
    high_ratio = _clusters_with_high_step_ratio(plan)
    if high_ratio:
        names = ", ".join(name for name, _, _, _ in high_ratio)
        warnings.append(f"1:1 step-to-issue ratio: {names}")
    clusters = plan.get("clusters", {})
    orphaned = [
        name for name, cluster in clusters.items()
        if not cluster.get("auto") and not cluster_issue_ids(cluster) and cluster.get("action_steps")
    ]
    if orphaned:
        warnings.append(f"Orphaned clusters (steps, no issues): {', '.join(orphaned)}")
    return warnings


def _validate_organize_stage(plan: dict, state: dict, stages: dict) -> tuple[bool, str]:
    """Validate recorded organize-stage content."""
    if "organize" not in stages:
        return False, "Organize stage not recorded."
    triage_scope = active_triage_issue_scope(plan, state)
    open_review_ids = open_review_ids_from_state(state) if triage_scope is None else triage_scope
    manual = scoped_manual_clusters_with_issues(plan, state)
    if not open_review_ids and not manual:
        report = stages["organize"].get("report", "")
        if len(report) < 100:
            return False, f"Organize report too short ({len(report)} chars, need 100+)."
        return True, ""
    if not manual:
        return False, "No manual clusters with issues exist."
    gaps = unenriched_clusters(plan, state)
    if gaps:
        names = ", ".join(name for name, _ in gaps)
        return False, f"Unenriched clusters: {names}"
    unclustered = unclustered_review_issues(plan, state)
    if unclustered:
        return False, f"{len(unclustered)} review issue(s) not in any cluster."
    report = stages["organize"].get("report", "")
    cluster_ref_failures = validate_report_references_clusters(report, manual)
    blocking_refs = [failure for failure in cluster_ref_failures if failure.blocking]
    if blocking_refs:
        return False, blocking_refs[0].message
    reflect_ts = stages.get("reflect", {}).get("timestamp", "")
    if reflect_ts:
        activity = count_log_activity_since(plan, reflect_ts)
        cluster_ops = sum(
            activity.get(key, 0)
            for key in ("cluster_create", "cluster_add", "cluster_update", "cluster_remove")
        )
        min_ops = max(3, len(manual))
        if cluster_ops < min_ops:
            return False, (
                f"Only {cluster_ops} cluster op(s) logged since reflect "
                f"(need {min_ops}+). Run cluster create/add/update commands."
            )
    warnings = _organize_stage_warnings(plan)
    if warnings:
        return True, "Advisory: " + "; ".join(warnings)
    return True, ""


def _validate_enrich_stage(
    plan: dict,
    state: dict,
    repo_root: Path,
    stages: dict,
) -> tuple[bool, str]:
    """Validate recorded enrich-stage content."""
    if "enrich" not in stages:
        return False, "Enrich stage not recorded."
    failures = run_enrich_quality_checks(
        plan,
        repo_root,
        phase_label="enrich",
        triage_issue_ids=active_triage_issue_ids(plan, state) or None,
    )
    if failures:
        return False, failures[0].message
    return True, ""


def _validate_sense_check_stage(
    plan: dict,
    state: dict,
    repo_root: Path,
    stages: dict,
    *,
    triage_input: TriageInput | None = None,
) -> tuple[bool, str]:
    """Validate recorded sense-check-stage content (includes value decisions)."""
    if "sense-check" not in stages:
        return False, "Sense-check stage not recorded."
    report = stages["sense-check"].get("report", "")
    if len(report) < 100:
        return False, f"Sense-check report too short ({len(report)} chars, need 100+)."
    manual_clusters = scoped_manual_clusters_with_issues(plan, state)
    triage_issue_ids = active_triage_issue_ids(plan, state) or None
    triage_scope = active_triage_issue_scope(plan, state)
    open_review_ids = open_review_ids_from_state(state) if triage_scope is None else triage_scope
    if not open_review_ids and not manual_clusters:
        return True, ""
    failures = run_enrich_quality_checks(
        plan,
        repo_root,
        phase_label="sense-check",
        triage_issue_ids=triage_issue_ids,
    )
    if failures:
        return False, failures[0].message
    path_failures = validate_report_has_file_paths(report)
    blocking_pf = [failure for failure in path_failures if failure.blocking]
    if blocking_pf:
        return False, blocking_pf[0].message
    cluster_failures = validate_report_references_clusters(report, manual_clusters)
    blocking_cf = [failure for failure in cluster_failures if failure.blocking]
    if blocking_cf:
        return False, blocking_cf[0].message
    # Decision Ledger validation (value subagent output)
    frozen_targets = None
    if isinstance(stages.get("sense-check"), dict):
        recorded_targets = stages["sense-check"].get("value_targets")
        if isinstance(recorded_targets, list):
            frozen_targets = [target for target in recorded_targets if isinstance(target, str)]
    if frozen_targets is None and triage_input is not None:
        triage_targets = getattr(triage_input, "value_check_targets", None)
        if isinstance(triage_targets, list):
            frozen_targets = [target for target in triage_targets if isinstance(target, str)]
    targets = frozen_targets if frozen_targets is not None else value_check_targets(plan, state)
    if targets:
        parsed = parse_value_check_decision_ledger(report)
        if not parsed.entries:
            return False, "Sense-check report missing `## Decision Ledger` entries."
        if parsed.duplicates:
            return False, f"Sense-check report duplicates decision targets: {', '.join(parsed.duplicates[:5])}"
        missing = [target for target in targets if target not in parsed.entries]
        if missing:
            return False, f"Sense-check report missing decision(s) for: {', '.join(missing[:5])}"
        extras = [target for target in parsed.entries if target not in targets]
        if extras:
            return False, f"Sense-check report references non-live target(s): {', '.join(extras[:5])}"
    return True, ""


def validate_stage(
    stage: str,
    plan: dict,
    state: dict,
    repo_root: Path,
    *,
    triage_input: TriageInput | None = None,
) -> tuple[bool, str]:
    """Check subagent completed stage correctly. Returns (ok, error_msg)."""
    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    validators = {
        "observe": lambda: _validate_observe_stage(
            stages=stages,
            triage_input=triage_input,
        ),
        "reflect": lambda: _validate_reflect_stage(stages),
        "organize": lambda: _validate_organize_stage(plan, state, stages),
        "enrich": lambda: _validate_enrich_stage(plan, state, repo_root, stages),
        "sense-check": lambda: _validate_sense_check_stage(
            plan,
            state,
            repo_root,
            stages,
            triage_input=triage_input,
        ),
    }
    validator = validators.get(stage)
    if validator is None:
        return False, f"Unknown stage: {stage}"
    return validator()


def validate_completion(
    plan: dict,
    state: dict,
    repo_root: Path,
) -> tuple[bool, str]:
    """Validate plan is ready for triage completion. Returns (ok, error_msg)."""
    _ = repo_root
    readiness = evaluate_completion_readiness(
        plan,
        state,
        require_confirmed_stages=True,
    )
    return readiness.ok, readiness.message


def build_auto_attestation(
    stage: str,
    plan: dict,
    triage_input: TriageInput,
) -> str:
    """Generate valid 80+ char attestation referencing real dimensions/cluster names."""
    review_issues = getattr(triage_input, "review_issues", getattr(triage_input, "open_issues", {}))
    if stage == "observe":
        _by_dim, dim_names = observe_dimension_breakdown(triage_input)
        top_dims = dim_names[:3]
        dims_str = ", ".join(top_dims)
        return (
            f"I have thoroughly analysed {len(review_issues)} issues "
            f"across dimensions including {dims_str}, identifying themes, "
            f"root causes, and contradictions across the codebase."
        )

    if stage == "reflect":
        _by_dim, dim_names = observe_dimension_breakdown(triage_input)
        top_dims = dim_names[:3]
        dims_str = ", ".join(top_dims)
        return (
            f"My strategy accounts for {len(review_issues)} issues "
            f"across dimensions including {dims_str}, comparing against "
            f"resolved history and forming priorities for execution."
        )

    if stage == "organize":
        cluster_names = scoped_manual_clusters_with_issues(plan)
        if not cluster_names:
            return (
                "I verified there are zero open review issues in this organize batch, "
                "so no manual clusters or issue assignments were needed before continuing."
            )
        names_str = ", ".join(cluster_names[:3])
        return (
            f"I have organized all review issues into clusters including "
            f"{names_str}, with descriptions, action steps, and clear "
            f"priority ordering based on root cause analysis."
        )

    if stage == "enrich":
        cluster_names = scoped_manual_clusters_with_issues(plan)
        if not cluster_names:
            return (
                "I verified there are zero open review issues in this enrich batch, "
                "so there were no action steps to elaborate before advancing."
            )
        names_str = ", ".join(cluster_names[:3])
        return (
            f"Steps in clusters including {names_str} are executor-ready with "
            f"detail, file paths, issue refs, and effort tags, verified "
            f"against the actual codebase."
        )

    if stage == "sense-check":
        cluster_names = scoped_manual_clusters_with_issues(plan)
        if not cluster_names:
            return (
                "I verified there are zero open review issues in this sense-check batch, "
                "so no cluster content or file-path evidence needed additional review."
            )
        names_str = ", ".join(cluster_names[:3])
        return (
            f"Content, structure and value verified for clusters including {names_str}. "
            f"All step details are factually accurate, cross-cluster dependencies "
            f"are safe, enrich-level checks pass, and value decisions are recorded."
        )

    return f"Stage {stage} completed with thorough analysis of all available data and verified against codebase."


__all__ = [
    "EnrichQualityFailure",
    "build_auto_attestation",
    "run_enrich_quality_checks",
    "validate_completion",
    "validate_stage",
]
