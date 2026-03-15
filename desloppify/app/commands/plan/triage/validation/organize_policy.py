"""Organize-stage validation helpers and reflect-ledger reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from desloppify.base.output.terminal import colorize

from ..review_coverage import cluster_issue_ids, manual_clusters_with_issues
from ..stages.helpers import unclustered_review_issues, unenriched_clusters
from .reflect_accounting import BacklogDecision, ReflectDisposition


@dataclass(frozen=True)
class ActualDisposition:
    """What actually happened to an issue in plan state."""

    kind: Literal["clustered", "skipped", "unplaced"]
    cluster_name: str = ""

    def describe(self, intended: ReflectDisposition | None = None) -> str:
        """Human-readable description for error messages."""
        if self.kind == "skipped":
            return "permanently skipped"
        if self.kind == "clustered":
            if intended and intended.decision == "cluster" and self.cluster_name != intended.target:
                return f'in cluster "{self.cluster_name}" (expected "{intended.target}")'
            return f'clustered in "{self.cluster_name}"'
        if self.kind == "unplaced":
            if intended and intended.decision == "cluster":
                return "not in any cluster"
            return "not skipped, not clustered"
        return "unknown state"


@dataclass(frozen=True)
class LedgerMismatch:
    """One issue where plan state diverges from the reflect disposition."""

    intended: ReflectDisposition
    actual: ActualDisposition

    @property
    def issue_id(self) -> str:
        return self.intended.issue_id

    @property
    def expected_decision(self) -> str:
        return self.intended.decision

    @property
    def expected_target(self) -> str:
        return self.intended.target

    @property
    def actual_state(self) -> str:
        return self.actual.describe(self.intended)


def _manual_clusters_or_error(
    plan: dict,
    *,
    open_review_ids: set[str] | None = None,
) -> list[str] | None:
    manual_clusters = manual_clusters_with_issues(plan)
    if manual_clusters:
        return manual_clusters
    if open_review_ids is not None and not open_review_ids:
        return []
    any_clusters = [
        name for name, cluster in plan.get("clusters", {}).items()
        if cluster_issue_ids(cluster)
    ]
    if any_clusters:
        print(colorize("  Cannot organize: only auto-clusters exist.", "red"))
        print(colorize("  Create manual clusters that group issues by root cause:", "dim"))
    else:
        print(colorize("  Cannot organize: no clusters with issues exist.", "red"))
    print(colorize('    desloppify plan cluster create <name> --description "..."', "dim"))
    print(colorize("    desloppify plan cluster add <name> <issue-patterns>", "dim"))
    return None


def _clusters_enriched_or_error(plan: dict) -> bool:
    gaps = unenriched_clusters(plan)
    if not gaps:
        return True
    print(colorize(f"  Cannot organize: {len(gaps)} cluster(s) need enrichment.", "red"))
    for name, missing in gaps:
        print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
    print()
    print(colorize("  Each cluster needs a description and action steps:", "dim"))
    print(
        colorize(
            '    desloppify plan cluster update <name> --description "what this cluster addresses" --steps "step 1" "step 2"',
            "dim",
        )
    )
    return False


def _unclustered_review_issues_or_error(plan: dict, state: dict) -> bool:
    """Block if open review issues aren't in any manual cluster. Return True if OK."""
    unclustered = unclustered_review_issues(plan, state)
    if not unclustered:
        return True
    print(colorize(f"  Cannot organize: {len(unclustered)} review issue(s) have no cluster.", "red"))
    for fid in unclustered[:10]:
        short = fid.rsplit("::", 2)[-2] if "::" in fid else fid
        print(colorize(f"    {short}", "yellow"))
    if len(unclustered) > 10:
        print(colorize(f"    ... and {len(unclustered) - 10} more", "yellow"))
    print()
    print(colorize("  Every review issue needs an action plan. Either:", "dim"))
    print(colorize("    1. Add to a cluster: desloppify plan cluster add <name> <pattern>", "dim"))
    print(
        colorize(
            '    2. Wontfix it: desloppify plan skip --permanent <pattern> --note "reason" --attest "..."',
            "dim",
        )
    )
    return False


def _organize_report_or_error(report: str | None) -> str | None:
    if not report:
        print(colorize("  --report is required for --stage organize.", "red"))
        print(colorize("  Summarize your prioritized organization:", "dim"))
        print(colorize("  - Did you defer contradictory issues before clustering?", "dim"))
        print(colorize("  - What clusters did you create and why?", "dim"))
        print(colorize("  - Explicit priority ordering: which cluster 1st, 2nd, 3rd and why?", "dim"))
        print(colorize("  - What depends on what? What unblocks the most?", "dim"))
        return None
    if len(report) < 100:
        print(colorize(f"  Report too short: {len(report)} chars (minimum 100).", "red"))
        print(colorize("  Explain what you organized, your priorities, and focus order.", "dim"))
        return None
    return report


def _build_actual_disposition_index(plan: dict) -> dict[str, ActualDisposition]:
    """Build a lookup from issue ID to its actual disposition in plan state."""
    index: dict[str, ActualDisposition] = {}

    for cluster_name, cluster in plan.get("clusters", {}).items():
        if cluster.get("auto"):
            continue
        for fid in cluster_issue_ids(cluster):
            index[fid] = ActualDisposition(kind="clustered", cluster_name=cluster_name)

    for fid in (plan.get("skipped", {}) or {}):
        if isinstance(fid, str):
            index[fid] = ActualDisposition(kind="skipped")

    return index


def _disposition_matches(intended: ReflectDisposition, actual: ActualDisposition) -> bool:
    """True when the actual plan state satisfies the intended disposition."""
    if intended.decision == "permanent_skip":
        return actual.kind == "skipped"
    if intended.decision == "cluster":
        return actual.kind == "clustered" and actual.cluster_name == intended.target
    return False


def validate_organize_against_dispositions(
    *,
    plan: dict,
) -> list[LedgerMismatch]:
    """Check that plan mutations match the unified issue_dispositions map.

    Preferred over ``validate_organize_against_reflect_ledger`` when the
    disposition map exists.  Only checks entries with a ``decision`` field
    (i.e. entries that have been through observe auto-skip or reflect).
    """
    meta = plan.get("epic_triage_meta", {})
    dispositions = meta.get("issue_dispositions", {})
    if not dispositions:
        return []

    # Only validate entries that have a decision
    decided = [
        (issue_id, disp)
        for issue_id, disp in dispositions.items()
        if disp.get("decision")
    ]
    if not decided:
        return []

    actuals = _build_actual_disposition_index(plan)
    unplaced = ActualDisposition(kind="unplaced")
    mismatches: list[LedgerMismatch] = []

    for issue_id, disp in decided:
        decision = disp["decision"]
        target = disp.get("target", "")
        # Normalize to ReflectDisposition for the mismatch report
        reflect_decision = "permanent_skip" if decision == "skip" else decision
        intended = ReflectDisposition(
            issue_id=issue_id,
            decision=reflect_decision,
            target=target,
        )
        actual = actuals.get(issue_id, unplaced)
        if not _disposition_matches(intended, actual):
            mismatches.append(LedgerMismatch(intended=intended, actual=actual))

    return mismatches


def validate_organize_against_reflect_ledger(
    *,
    plan: dict,
    stages: dict,
) -> list[LedgerMismatch]:
    """Check that plan mutations match the reflect disposition ledger."""
    raw_ledger = stages.get("reflect", {}).get("disposition_ledger")
    if not raw_ledger:
        return []

    ledger = [ReflectDisposition.from_dict(d) for d in raw_ledger]
    actuals = _build_actual_disposition_index(plan)
    unplaced = ActualDisposition(kind="unplaced")

    return [
        LedgerMismatch(intended=d, actual=actuals.get(d.issue_id, unplaced))
        for d in ledger
        if not _disposition_matches(d, actuals.get(d.issue_id, unplaced))
    ]


def _validate_organize_against_ledger_or_error(
    *,
    plan: dict,
    stages: dict,
) -> bool:
    """Block organize if plan state diverges from dispositions or the reflect ledger."""
    # Prefer unified disposition map when available
    mismatches = validate_organize_against_dispositions(plan=plan)
    if not mismatches:
        # Fall back to legacy reflect ledger validation
        mismatches = validate_organize_against_reflect_ledger(
            plan=plan,
            stages=stages,
        )
    if not mismatches:
        return True

    print(
        colorize(
            f"  Cannot organize: {len(mismatches)} issue(s) diverge from the reflect plan.",
            "red",
        )
    )
    for mismatch in mismatches[:10]:
        short_id = mismatch.issue_id.rsplit("::", 1)[-1]
        print(
            colorize(
                f"    {short_id}: reflect said {mismatch.expected_decision} "
                f'"{mismatch.expected_target}", but {mismatch.actual_state}',
                "yellow",
            )
        )
    if len(mismatches) > 10:
        print(colorize(f"    ... and {len(mismatches) - 10} more", "yellow"))
    print()
    print(
        colorize(
            "  Fix the plan to match the reflect ledger, or re-run reflect to update dispositions.",
            "dim",
        )
    )
    return False


def validate_backlog_promotions_executed(
    *,
    plan: dict,
    stages: dict,
) -> list[str]:
    """Warn when reflect requested backlog promotions that organize didn't execute.

    Returns a list of warning strings (non-blocking). Empty means all good.
    """
    reflect_data = stages.get("reflect", {})
    raw_decisions = reflect_data.get("backlog_decisions", [])
    if not raw_decisions:
        return []

    decisions = [BacklogDecision.from_dict(d) for d in raw_decisions]
    promote_decisions = [d for d in decisions if d.decision == "promote"]
    if not promote_decisions:
        return []

    # Check which promoted clusters actually got promoted (are in queue_order
    # or have execution_status set to active)
    clusters = plan.get("clusters", {})
    warnings: list[str] = []
    for decision in promote_decisions:
        cluster = clusters.get(decision.cluster_name)
        if cluster is None:
            continue
        # A promoted cluster should have been activated
        execution_status = cluster.get("execution_status", "")
        if execution_status not in ("active", "in_progress"):
            warnings.append(
                f"Reflect requested promoting {decision.cluster_name} "
                f"but it was not promoted during organize."
            )
    return warnings


__all__ = [
    "ActualDisposition",
    "LedgerMismatch",
    "_clusters_enriched_or_error",
    "_manual_clusters_or_error",
    "_organize_report_or_error",
    "_unclustered_review_issues_or_error",
    "_validate_organize_against_ledger_or_error",
    "validate_backlog_promotions_executed",
    "validate_organize_against_dispositions",
    "validate_organize_against_reflect_ledger",
]
