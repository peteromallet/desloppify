"""Prompt/data contracts for whole-plan triage orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from desloppify.engine._plan.cluster_semantics import cluster_autofix_hint
from desloppify.engine._plan.schema import (
    Cluster,
    EPIC_PREFIX,
    PlanModel,
    ensure_plan_defaults,
    triage_clusters,
)
from desloppify.engine._plan.triage.snapshot import build_triage_snapshot
from desloppify.engine._state.issue_semantics import is_triage_finding
from desloppify.engine._state.schema import StateModel


@dataclass(init=False)
class TriageInput:
    """All data needed to produce/update triage clusters."""

    review_issues: dict[str, dict]       # id -> issue (review + concerns)
    objective_backlog_issues: dict[str, dict]  # id -> issue (non-review, for context)
    auto_clusters: dict[str, dict]       # auto/ clusters available for promotion
    existing_clusters: dict[str, Cluster]
    dimension_scores: dict[str, Any]      # for context
    new_since_last: set[str]             # issue IDs new since last triage
    resolved_since_last: set[str]        # issue IDs resolved since last
    previously_dismissed: list[str]      # IDs dismissed in prior triage
    triage_version: int                  # next version number
    resolved_issues: dict[str, dict]   # full issue objects for resolved IDs
    completed_clusters: list[dict]       # clusters completed since last triage
    value_check_targets: list[str] | None

    def __init__(
        self,
        *,
        review_issues: dict[str, dict] | None = None,
        objective_backlog_issues: dict[str, dict] | None = None,
        auto_clusters: dict[str, dict] | None = None,
        existing_clusters: dict[str, Cluster],
        dimension_scores: dict[str, Any],
        new_since_last: set[str],
        resolved_since_last: set[str],
        previously_dismissed: list[str],
        triage_version: int,
        resolved_issues: dict[str, dict],
        completed_clusters: list[dict],
        value_check_targets: list[str] | None = None,
        open_issues: dict[str, dict] | None = None,
        mechanical_issues: dict[str, dict] | None = None,
    ) -> None:
        if review_issues is not None and open_issues is not None:
            raise TypeError("Pass either review_issues or open_issues, not both.")
        if objective_backlog_issues is not None and mechanical_issues is not None:
            raise TypeError(
                "Pass either objective_backlog_issues or mechanical_issues, not both."
            )

        self.review_issues = (
            review_issues
            if review_issues is not None
            else (open_issues if open_issues is not None else {})
        )
        self.objective_backlog_issues = (
            objective_backlog_issues
            if objective_backlog_issues is not None
            else (mechanical_issues if mechanical_issues is not None else {})
        )
        self.auto_clusters = auto_clusters if auto_clusters is not None else {}
        self.existing_clusters = existing_clusters
        self.dimension_scores = dimension_scores
        self.new_since_last = new_since_last
        self.resolved_since_last = resolved_since_last
        self.previously_dismissed = previously_dismissed
        self.triage_version = triage_version
        self.resolved_issues = resolved_issues
        self.completed_clusters = completed_clusters
        self.value_check_targets = value_check_targets

    @property
    def open_issues(self) -> dict[str, dict]:
        """Backward-compatible alias for older triage callsites."""
        return self.review_issues

    @property
    def mechanical_issues(self) -> dict[str, dict]:
        """Backward-compatible alias for older triage callsites."""
        return self.objective_backlog_issues

@dataclass
class DismissedIssue:
    """A issue the LLM says doesn't make sense."""

    issue_id: str
    reason: str

@dataclass
class ContradictionNote:
    """Record of a resolved contradiction."""

    kept: str
    dismissed: str
    reason: str

@dataclass
class AutoClusterDecision:
    """A triage decision for an auto-cluster."""

    cluster: str
    action: str  # "promote", "skip", "defer", or "break_up"
    reason: str = ""
    priority: str = ""  # e.g. "after dead-code-fixes", "last", "first"
    sub_clusters: list[str] = field(default_factory=list)  # for break_up action

@dataclass
class TriageResult:
    """Parsed and validated LLM triage output."""

    strategy_summary: str
    epics: list[dict]
    dismissed_issues: list[DismissedIssue] = field(default_factory=list)
    contradiction_notes: list[ContradictionNote] = field(default_factory=list)
    priority_rationale: str = ""
    auto_cluster_decisions: list[AutoClusterDecision] = field(default_factory=list)

    @property
    def clusters(self) -> list[dict]:
        """Canonical cluster view for triage results."""
        return self.epics


def _issue_dimension(issue: dict) -> str:
    detail = issue.get("detail", {})
    if isinstance(detail, dict):
        dimension = detail.get("dimension", "")
        if isinstance(dimension, str):
            return dimension
    return ""


def _recurring_dimensions(
    review_issues: dict[str, dict],
    resolved_issues: dict[str, dict],
) -> dict[str, dict[str, list[str]]]:
    open_by_dim: dict[str, list[str]] = {}
    for issue_id, issue in review_issues.items():
        dimension = _issue_dimension(issue)
        if dimension:
            open_by_dim.setdefault(dimension, []).append(issue_id)

    resolved_by_dim: dict[str, list[str]] = {}
    for issue_id, issue in resolved_issues.items():
        dimension = _issue_dimension(issue)
        if dimension:
            resolved_by_dim.setdefault(dimension, []).append(issue_id)

    recurring: dict[str, dict[str, list[str]]] = {}
    for dimension in sorted(set(open_by_dim) & set(resolved_by_dim)):
        recurring[dimension] = {
            "open": sorted(open_by_dim[dimension]),
            "resolved": sorted(resolved_by_dim[dimension]),
        }
    return recurring


def _split_open_issue_buckets(
    issues: dict[str, dict],
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Split open issues into review (individual triage) and mechanical (cluster triage).

    With the unified pipeline, all defects are triage findings. Review issues
    get individual treatment; mechanical defects flow through auto-cluster
    summaries.
    """
    open_review: dict[str, dict] = {}
    open_mechanical: dict[str, dict] = {}
    for issue_id, issue in issues.items():
        if issue.get("status") != "open":
            continue
        kind = issue.get("work_item_kind", issue.get("issue_kind", ""))
        if kind in ("review_defect", "review_concern"):
            open_review[issue_id] = issue
        elif kind == "mechanical_defect":
            open_mechanical[issue_id] = issue
        elif is_triage_finding(issue):
            # Fallback for items without explicit kind — infer from semantics
            from desloppify.engine._state.issue_semantics import is_review_work_item
            if is_review_work_item(issue):
                open_review[issue_id] = issue
            else:
                open_mechanical[issue_id] = issue
    return open_review, open_mechanical


def _recent_completed_clusters(meta: dict, plan: PlanModel) -> list[dict]:
    last_completed = meta.get("last_completed_at", "")
    all_completed: list[dict] = plan.get("completed_clusters", [])
    if not last_completed:
        return list(all_completed)
    return [
        cluster for cluster in all_completed
        if cluster.get("completed_at", "") > last_completed
    ]


def collect_triage_input(plan: PlanModel, state: StateModel) -> TriageInput:
    """Gather all data needed for the triage LLM prompt."""
    ensure_plan_defaults(plan)
    issues = (state.get("work_items") or state.get("issues", {}))
    meta = plan.get("epic_triage_meta", {})
    epics = triage_clusters(plan)
    auto_clusters = {
        name: cluster
        for name, cluster in plan.get("clusters", {}).items()
        if cluster.get("auto") and not name.startswith(EPIC_PREFIX)
    }
    open_review, open_mechanical = _split_open_issue_buckets(issues)
    snapshot = build_triage_snapshot(plan, state)

    triaged_ids = set(meta.get("triaged_ids", []))
    current_review_ids = set(open_review.keys())
    new_since = set(snapshot.new_since_triage_ids)
    resolved_since = triaged_ids - current_review_ids
    previously_dismissed = list(meta.get("dismissed_ids", []))
    version = int(meta.get("version", 0)) + 1

    # Resolved issue objects (for REFLECT stage)
    resolved_issue_objs = {
        fid: issues[fid] for fid in resolved_since if fid in issues
    }

    return TriageInput(
        review_issues=open_review,
        objective_backlog_issues=open_mechanical,
        auto_clusters=auto_clusters,
        existing_clusters=dict(epics),
        dimension_scores=state.get("dimension_scores", {}),
        new_since_last=new_since,
        resolved_since_last=resolved_since,
        previously_dismissed=previously_dismissed,
        triage_version=version,
        resolved_issues=resolved_issue_objs,
        completed_clusters=_recent_completed_clusters(meta, plan),
    )

_TRIAGE_SYSTEM_PROMPT = """\
You are maintaining the meta-plan for this codebase. Produce a coherent
prioritized strategy for all open review issues, and decide which mechanical
backlog items should be promoted into the active queue now.

Your plan should:
- Cluster issues by ROOT CAUSE, not by dimension or detector
- Give each cluster a clear thesis: one imperative sentence
- Order clusters by dependency: what must be done first for later work to make sense
- Dismiss issues that don't make sense, are contradictory, or are false positives
- Mark which clusters are agent-safe (can be executed mechanically) vs need human judgment
- Avoid creating work that contradicts other work in the plan
- Be ambitious but realistic — aim to resolve all issues coherently

Available directions for clusters: delete, merge, flatten, enforce, simplify, decompose, extract, inline.

Available plan tools (the agent executing your plan has access to these):
- `desloppify plan queue` — view the explicit execution queue in priority order
- `desloppify backlog` — inspect broader open work outside the execution queue
- `desloppify plan promote <id-or-pattern>` — move backlog work into the active queue
- `desloppify plan focus <name>` — focus the queue on one cluster
- `desloppify plan skip <id> --permanent --note "why" --attest "..."` — permanently dismiss
- `desloppify plan skip <id> --note "revisit later"` — temporarily defer
- `desloppify plan resolve <id> --note "what I did" --attest "..."` — mark resolved
- `desloppify plan reorder <id> top|bottom|before|after <target>` — reorder
- `desloppify plan cluster show <name>` — inspect a cluster
- `desloppify scan` — re-scan after making changes to verify progress
- `desloppify show review --status open` — see all open review issues

Your output defines the active work plan for all open defects. Review issues are
triaged individually; auto-clusters are triaged at the cluster level (promote/skip/break_up).
Every auto-cluster must have an explicit decision. Dismissed issues will be removed from
the queue with your stated reason.

Respond with a single JSON object matching this schema:
{
  "strategy_summary": "2-4 sentence narrative: what the meta-plan says, top priorities, current state",
  "clusters": [
    {
      "name": "slug-name",
      "thesis": "imperative one-liner",
      "direction": "delete|merge|flatten|enforce|simplify|decompose|extract|inline",
      "root_cause": "why this cluster exists",
      "issue_ids": ["id1", "id2"],
      "dismissed": ["id3"],
      "agent_safe": true,
      "dependency_order": 1,
      "action_steps": [
        {
          "title": "Short imperative step title",
          "detail": "Concrete implementation detail with file paths/locations",
          "issue_refs": ["id1"]
        }
      ],
      "status": "pending"
    }
  ],
  "dismissed_issues": [
    {"issue_id": "id", "reason": "why this issue doesn't make sense"}
  ],
  "contradiction_notes": [
    {"kept": "issue_id", "dismissed": "issue_id", "reason": "why"}
  ],
  "priority_rationale": "why the dependency_order is what it is",
  "auto_cluster_decisions": [
    {"cluster": "auto/security", "action": "promote", "priority": "first", "reason": "high-value security fixes"},
    {"cluster": "auto/unused", "action": "skip", "reason": "mostly test assert noise"},
    {"cluster": "auto/test_coverage", "action": "defer", "reason": "clean up code quality issues first — tests lock in current patterns"}
  ]
}
"""

def _append_existing_clusters_section(parts: list[str], clusters: dict[str, Cluster]) -> None:
    if not clusters:
        return
    parts.append("## Existing clusters")
    for name, cluster in sorted(clusters.items()):
        status = cluster.get("status", "pending")
        thesis = cluster.get("thesis", "")
        direction = cluster.get("direction", "")
        issue_ids = cluster.get("issue_ids", [])
        parts.append(
            f"- {name} [{status}] ({direction}): {thesis}"
            f"\n  Issues: {', '.join(issue_ids[:10])}"
            f"{'...' if len(issue_ids) > 10 else ''}"
        )
    parts.append("")


def _append_changed_issue_section(
    parts: list[str],
    *,
    title: str,
    issue_ids: set[str],
    issues: dict[str, dict] | None = None,
) -> None:
    if not issue_ids:
        return
    parts.append(f"## {title} ({len(issue_ids)})")
    for issue_id in sorted(issue_ids):
        if issues is None:
            parts.append(f"- {issue_id}")
            continue
        issue = issues.get(issue_id, {})
        parts.append(f"- {issue_id}: {issue.get('summary', '(no summary)')}")
    parts.append("")


def _append_resolved_issue_context(parts: list[str], resolved_issues: dict[str, dict]) -> None:
    if not resolved_issues:
        return
    parts.append(
        "## Resolved review issues available for recurrence context "
        f"({len(resolved_issues)})"
    )
    resolved_ids = sorted(resolved_issues)
    for issue_id in resolved_ids[:30]:
        issue = resolved_issues.get(issue_id, {})
        summary = str(issue.get("summary", "(no summary)"))
        dimension = _issue_dimension(issue)
        dim_suffix = f" [{dimension}]" if dimension else ""
        parts.append(f"- {issue_id}{dim_suffix}: {summary}")
    if len(resolved_ids) > 30:
        parts.append(f"- ... and {len(resolved_ids) - 30} more resolved issues")
    parts.append("")


def _append_completed_clusters_section(parts: list[str], completed_clusters: list[dict]) -> None:
    if not completed_clusters:
        return
    parts.append(
        "## Completed clusters since last triage "
        f"({len(completed_clusters)})"
    )
    completed = sorted(
        completed_clusters,
        key=lambda cluster: str(cluster.get("completed_at", "")),
        reverse=True,
    )
    for cluster in completed[:10]:
        name = str(cluster.get("name", "(unnamed cluster)"))
        thesis = str(cluster.get("thesis") or cluster.get("description") or "")
        completed_at = str(cluster.get("completed_at", ""))
        issue_ids = cluster.get("issue_ids", [])
        issue_count = len(issue_ids) if isinstance(issue_ids, list) else 0
        parts.append(
            f"- {name}: {thesis} (issues: {issue_count}, completed_at: {completed_at})"
        )
    if len(completed) > 10:
        parts.append(f"- ... and {len(completed) - 10} more completed clusters")
    parts.append("")


def _append_recurring_dimensions_section(
    parts: list[str],
    review_issues: dict[str, dict],
    resolved_issues: dict[str, dict],
) -> None:
    recurring = _recurring_dimensions(review_issues, resolved_issues)
    if not recurring:
        return
    parts.append(
        "## Potential recurring dimensions (resolved issues still have open peers)"
    )
    for dimension, bucket in recurring.items():
        open_count = len(bucket["open"])
        resolved_count = len(bucket["resolved"])
        parts.append(
            f"- {dimension}: {open_count} open / {resolved_count} recently resolved"
        )
    parts.append("")


def _append_open_review_issues_section(parts: list[str], review_issues: dict[str, dict]) -> None:
    parts.append(f"## All open review issues ({len(review_issues)})")
    for issue_id, issue in sorted(review_issues.items()):
        detail = issue.get("detail", {}) if isinstance(issue.get("detail"), dict) else {}
        suggestion = detail.get("suggestion", "")
        dimension = detail.get("dimension", "")
        confidence = issue.get("confidence", "medium")
        file_path = issue.get("file", "")
        summary = issue.get("summary", "")
        parts.append(f"- [{confidence}] {issue_id}")
        parts.append(f"  File: {file_path}")
        if dimension:
            parts.append(f"  Dimension: {dimension}")
        parts.append(f"  Summary: {summary}")
        if suggestion:
            parts.append(f"  Suggestion: {suggestion}")
    parts.append("")


def _append_dimension_scores_section(parts: list[str], dimension_scores: dict[str, Any]) -> None:
    if not dimension_scores:
        return
    parts.append("## Dimension scores (context)")
    for name, data in sorted(dimension_scores.items()):
        if not isinstance(data, dict):
            continue
        score = data.get("score", "?")
        strict = data.get("strict", score)
        issues = data.get("failing", 0)
        parts.append(f"- {name}: {score}% (strict: {strict}%, {issues} issues)")
    parts.append("")


def _append_mechanical_backlog_section(
    parts: list[str],
    objective_backlog_issues: dict[str, dict],
    auto_clusters: dict[str, dict],
) -> None:
    if not objective_backlog_issues:
        return

    clustered_ids: set[str] = set()
    for cluster in auto_clusters.values():
        issue_ids = cluster.get("issue_ids", [])
        if isinstance(issue_ids, list):
            clustered_ids.update(
                issue_id
                for issue_id in issue_ids
                if isinstance(issue_id, str) and issue_id in objective_backlog_issues
            )

    unclustered = {
        issue_id: issue
        for issue_id, issue in objective_backlog_issues.items()
        if issue_id not in clustered_ids
    }
    clustered_issue_count = len(clustered_ids)
    auto_cluster_count = sum(
        1 for cluster in auto_clusters.values()
        if any(
            isinstance(issue_id, str) and issue_id in objective_backlog_issues
            for issue_id in cluster.get("issue_ids", [])
        )
    )

    parts.append(
        "## Auto-cluster candidates "
        f"({len(objective_backlog_issues)} items: {clustered_issue_count} in "
        f"{auto_cluster_count} auto-clusters, {len(unclustered)} unclustered)"
    )
    parts.append(
        "These are detector-created findings grouped by rule type. Each auto-cluster "
        "is a first-class triage candidate — decide its fate just like review issues."
    )
    parts.append(
        "You MUST make an explicit decision for each auto-cluster listed below. "
        "Include every auto-cluster in your `auto_cluster_decisions` output with one of: "
        "promote (add to active queue with a priority position), "
        "skip (with a specific reason — e.g. 'mostly false positives per sampling'), "
        "defer (keep in backlog — revisit after higher-impact work is done), or "
        "break_up (split into smaller sub-clusters with a reason).\n\n"
        "IMPORTANT: Prioritize code quality fixes (dead code, naming, smells, duplication, "
        "structural issues) BEFORE test coverage. Writing tests for sloppy code locks in the "
        "slop. Clean up the code first, then add tests to protect the clean version. "
        "Defer test_coverage clusters unless code quality dimensions are already above 80%."
    )

    rendered_clusters: list[tuple[str, dict, int]] = []
    for name, cluster in auto_clusters.items():
        raw_issue_ids = cluster.get("issue_ids", [])
        if not isinstance(raw_issue_ids, list):
            continue
        member_count = sum(
            1 for issue_id in raw_issue_ids
            if isinstance(issue_id, str) and issue_id in objective_backlog_issues
        )
        if member_count <= 0:
            continue
        rendered_clusters.append((name, cluster, member_count))

    if rendered_clusters:
        parts.append("### Auto-clusters (decision required for each)")
        parts.append(
            "Each cluster below includes a statistical summary with severity breakdown "
            "and sample issues. Decide for each: promote, skip (with reason), or break_up."
        )
        rendered_clusters.sort(key=lambda item: (-item[2], item[0]))
        visible_clusters = rendered_clusters[:15]
        for name, cluster, member_count in visible_clusters:
            autofix_hint = _cluster_autofix_hint(cluster)
            hint_suffix = f" [autofix: {autofix_hint}]" if autofix_hint else ""
            summary = _cluster_backlog_summary(name, cluster, member_count)
            parts.append(f"- {name} ({member_count} items){hint_suffix}")
            parts.append(f"  {summary}")
            # Statistical summary: severity/confidence breakdown + samples
            stats = _cluster_stats(cluster, objective_backlog_issues)
            if stats:
                parts.append(f"  {stats}")
        if len(rendered_clusters) > len(visible_clusters):
            remaining = rendered_clusters[len(visible_clusters):]
            remaining_issues = sum(item[2] for item in remaining)
            parts.append(
                f"- ... and {len(remaining)} more clusters ({remaining_issues} issues)"
            )

    if unclustered:
        parts.append(
            f"### Unclustered items ({len(unclustered)} items — needs human judgment or isolated findings)"
        )
        parts.append(
            "Promote individually with `desloppify plan promote <issue-id>`, or group related items into a manual cluster."
        )
        sample_ids = sorted(
            unclustered,
            key=lambda issue_id: (
                _confidence_sort_key(unclustered[issue_id]),
                issue_id,
            ),
        )[:10]
        for issue_id in sample_ids:
            issue = unclustered[issue_id]
            confidence = str(issue.get("confidence", "medium"))
            summary = str(issue.get("summary", "(no summary)"))
            parts.append(f"- [{confidence}] {issue_id} — {summary}")
        if len(unclustered) > len(sample_ids):
            parts.append(
                f"- ... and {len(unclustered) - len(sample_ids)} more unclustered items"
            )

    parts.append("Browse full backlog: `desloppify backlog`")
    parts.append("Inspect a cluster: `desloppify plan cluster show auto/<name>`")
    parts.append("Inspect an issue: `desloppify show <issue-id>`")
    parts.append("")


def _cluster_stats(cluster: dict[str, Any], all_issues: dict[str, dict]) -> str:
    """Build a compact statistical summary for an auto-cluster."""
    issue_ids = cluster.get("issue_ids", [])
    if not isinstance(issue_ids, list):
        return ""
    members = [
        all_issues[iid] for iid in issue_ids
        if isinstance(iid, str) and iid in all_issues
    ]
    if not members:
        return ""

    # Severity/confidence breakdown
    from collections import Counter
    severities: Counter[str] = Counter()
    confidences: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    for m in members:
        detail = m.get("detail") or {}
        if isinstance(detail, dict):
            severities[detail.get("severity", "unknown")] += 1
            rules[detail.get("kind", detail.get("test_name", "unknown"))] += 1
        confidences[str(m.get("confidence", "medium"))] += 1

    parts: list[str] = []
    if severities:
        sev_str = ", ".join(f"{k}: {v}" for k, v in severities.most_common(3))
        parts.append(f"severity=[{sev_str}]")
    if confidences:
        conf_str = ", ".join(f"{k}: {v}" for k, v in confidences.most_common(3))
        parts.append(f"confidence=[{conf_str}]")
    if rules:
        top_rules = rules.most_common(5)
        rule_str = ", ".join(f"{k}({v})" for k, v in top_rules)
        if len(rules) > 5:
            rule_str += f", +{len(rules) - 5} more"
        parts.append(f"top_rules=[{rule_str}]")

    # Sample issues (3-5)
    samples = members[:5]
    sample_strs = []
    for s in samples:
        f = s.get("file", "")
        summary = str(s.get("summary", ""))[:80]
        sample_strs.append(f"{f}: {summary}")
    if sample_strs:
        parts.append("samples: " + " | ".join(sample_strs))

    return " ".join(parts)


def _cluster_autofix_hint(cluster: dict[str, Any]) -> str:
    return cluster_autofix_hint(cluster) or ""


def _cluster_backlog_summary(name: str, cluster: dict[str, Any], member_count: int) -> str:
    description = str(cluster.get("description") or "").strip()
    if description:
        return description
    title = name.removeprefix("auto/").replace("-", " ")
    if title:
        return f"Address {member_count} {title} findings"
    return f"Address {member_count} detector findings"


def _confidence_sort_key(issue: dict[str, Any]) -> int:
    confidence = str(issue.get("confidence", "medium")).lower()
    order = {"high": 0, "medium": 1, "low": 2}
    return order.get(confidence, 1)


def _append_previously_dismissed_section(parts: list[str], dismissed_ids: list[str]) -> None:
    if not dismissed_ids:
        return
    parts.append(f"## Previously dismissed ({len(dismissed_ids)})")
    parts.append("Maintain unless contradicted by new evidence.")
    for issue_id in dismissed_ids:
        parts.append(f"- {issue_id}")
    parts.append("")


def build_triage_prompt(si: TriageInput) -> str:
    """Build the user-facing prompt content with all issue data."""
    parts: list[str] = []
    _append_existing_clusters_section(parts, si.existing_clusters)
    _append_changed_issue_section(
        parts,
        title="New issues since last triage",
        issue_ids=si.new_since_last,
        issues=si.review_issues,
    )
    _append_changed_issue_section(
        parts,
        title="Resolved since last triage",
        issue_ids=si.resolved_since_last,
    )
    _append_resolved_issue_context(parts, si.resolved_issues)
    _append_completed_clusters_section(parts, si.completed_clusters)
    _append_recurring_dimensions_section(parts, si.review_issues, si.resolved_issues)
    _append_open_review_issues_section(parts, si.review_issues)
    _append_dimension_scores_section(parts, si.dimension_scores)
    _append_mechanical_backlog_section(
        parts,
        si.objective_backlog_issues,
        si.auto_clusters,
    )
    _append_previously_dismissed_section(parts, si.previously_dismissed)
    return "\n".join(parts)

__all__ = [
    "_TRIAGE_SYSTEM_PROMPT",
    "AutoClusterDecision",
    "ContradictionNote",
    "DismissedIssue",
    "TriageInput",
    "TriageResult",
    "build_triage_prompt",
    "collect_triage_input",
]
