"""Pure data collection helpers for the triage strategist stage."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from desloppify.engine._plan.schema import PlanModel
from desloppify.engine._plan.triage.core import detect_recurring_patterns
from desloppify.engine._state.issue_semantics import is_review_work_item
from desloppify.engine._state.schema import StateModel

# Statuses meaning "issue was addressed by fixing code" (not dismissals like
# wontfix/false_positive).  Includes the legacy "resolved" and "done" aliases
# that can appear in older state files.
_ACTIVELY_RESOLVED_STATUSES = frozenset({"fixed", "resolved", "done", "auto_resolved"})


@dataclass(frozen=True)
class ScoreTrajectory:
    strict_scores: list[float]
    strict_delta: float
    trend: str
    best_scan_delta: float
    worst_scan_delta: float
    cycle_start_score: float | None = None  # from plan_start_scores or previous
    all_time_high: float | None = None  # highest strict_score across full scan_history


@dataclass(frozen=True)
class DimensionTrajectory:
    name: str
    strict_scores: list[float]
    trend: str
    headroom: float
    recent_investment: int


@dataclass(frozen=True)
class FileChurnEntry:
    file: str
    resolved_count: int
    current_open_count: int
    detectors: list[str]


@dataclass(frozen=True)
class ReworkLoopEntry:
    dimension: str
    resolved_count: int
    new_open_count: int
    reopen_count: int
    affected_files: list[str]


@dataclass(frozen=True)
class CompletedClusterSummary:
    name: str
    thesis: str
    issue_count: int
    completed_at: str


@dataclass(frozen=True)
class ExecutionPatterns:
    total_resolved: int
    total_skipped: int
    total_done: int
    skip_rate: float
    avg_cluster_size: float


@dataclass(frozen=True)
class DebtTrajectory:
    current_wontfix: int
    trend: str
    worst_dimension: str | None
    worst_dimension_gap: float


@dataclass(frozen=True)
class CommitHistoryInsights:
    total_commits: int
    recent_commits: int
    committed_issue_count: int
    latest_note: str | None
    recent_cluster_names: list[str]


@dataclass(frozen=True)
class StrategistInput:
    score_trajectory: ScoreTrajectory
    dimension_trajectories: dict[str, DimensionTrajectory]
    file_churn: list[FileChurnEntry]
    rework_loops: list[ReworkLoopEntry]
    completed_clusters: list[CompletedClusterSummary]
    execution_patterns: ExecutionPatterns
    debt_trajectory: DebtTrajectory
    commit_history: CommitHistoryInsights
    recurring_patterns: dict[str, dict[str, list[str]]]
    current_dimension_scores: dict[str, Any]
    open_issue_count: int
    scan_count: int
    backlog_by_dimension: dict[str, int]
    skipped_by_reason: dict[str, int]
    deferred_count: int
    prioritized_ids: list[str]
    cluster_names: list[str]
    promoted_count: int

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "score_trajectory": asdict(self.score_trajectory),
            "dimension_trajectories": {
                name: asdict(entry) for name, entry in self.dimension_trajectories.items()
            },
            "file_churn": [asdict(entry) for entry in self.file_churn],
            "rework_loops": [asdict(entry) for entry in self.rework_loops],
            "completed_clusters": [asdict(entry) for entry in self.completed_clusters],
            "execution_patterns": asdict(self.execution_patterns),
            "debt_trajectory": asdict(self.debt_trajectory),
            "commit_history": asdict(self.commit_history),
            "recurring_patterns": self.recurring_patterns,
            "current_dimension_scores": self.current_dimension_scores,
            "open_issue_count": self.open_issue_count,
            "scan_count": self.scan_count,
            "backlog_by_dimension": self.backlog_by_dimension,
            "skipped_by_reason": self.skipped_by_reason,
            "deferred_count": self.deferred_count,
            "prioritized_ids": self.prioritized_ids,
            "cluster_names": self.cluster_names,
            "promoted_count": self.promoted_count,
        }


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_iso_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _trend_from_delta(delta: float, *, stagnant_threshold: float = 0.5) -> str:
    if delta > stagnant_threshold:
        return "improving"
    if delta < -stagnant_threshold:
        return "declining"
    return "stable"


def _dimension_name_for_issue(issue: dict[str, Any]) -> str:
    """Extract dimension from an issue.

    Checks both ``detail.dimension`` (review issues) and
    ``detail.dimension_name`` (synthetic/work-queue items) because this
    function is called on all work_items, not just review issues.
    """
    detail = issue.get("detail", {})
    if isinstance(detail, dict):
        for key in ("dimension", "dimension_name"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "unknown"


def _open_review_and_resolved_review_issues(
    state: StateModel,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    work_items = state.get("work_items") or state.get("issues", {})
    open_review: dict[str, dict[str, Any]] = {}
    resolved_review: dict[str, dict[str, Any]] = {}
    for issue_id, issue in work_items.items():
        if not isinstance(issue, dict) or not is_review_work_item(issue):
            continue
        status = str(issue.get("status", ""))
        if status == "open":
            open_review[issue_id] = issue
        elif status in _ACTIVELY_RESOLVED_STATUSES or issue.get("resolved_at"):
            resolved_review[issue_id] = issue
    return open_review, resolved_review


def score_trajectory(
    scan_history: list[dict[str, Any]],
    window: int = 5,
    *,
    cycle_start_score: float | None = None,
) -> ScoreTrajectory:
    all_entries = [entry for entry in scan_history if isinstance(entry, dict)]

    # Compute all_time_high from the FULL history
    all_strict = [
        strict
        for entry in all_entries
        if (strict := _as_float(entry.get("strict_score"))) is not None
    ]
    all_time_high = round(max(all_strict), 2) if all_strict else None

    # Windowed scores for recent momentum
    recent = all_entries[-window:]
    strict_scores = [
        strict
        for entry in recent
        if (strict := _as_float(entry.get("strict_score"))) is not None
    ]
    if not strict_scores:
        return ScoreTrajectory([], 0.0, "stable", 0.0, 0.0, cycle_start_score=cycle_start_score, all_time_high=all_time_high)
    deltas = [
        round(current - previous, 2)
        for previous, current in zip(strict_scores, strict_scores[1:], strict=False)
    ]
    strict_delta = round(strict_scores[-1] - strict_scores[0], 2)

    # Determine trend from windowed delta
    trend = _trend_from_delta(strict_delta)

    # Override to "recovering" when windowed trend says improving but current
    # score is still more than 2 points below the all-time high
    if (
        trend == "improving"
        and all_time_high is not None
        and strict_scores[-1] < all_time_high - 2.0
    ):
        trend = "recovering"

    # Also override to "recovering" when improving but still below cycle start
    if (
        trend == "improving"
        and cycle_start_score is not None
        and strict_scores[-1] < cycle_start_score - 0.5
    ):
        trend = "recovering"

    return ScoreTrajectory(
        strict_scores=[round(score, 2) for score in strict_scores],
        strict_delta=strict_delta,
        trend=trend,
        best_scan_delta=max(deltas, default=0.0),
        worst_scan_delta=min(deltas, default=0.0),
        cycle_start_score=cycle_start_score,
        all_time_high=all_time_high,
    )


def dimension_trajectories(
    scan_history: list[dict[str, Any]],
    current_dim_scores: dict[str, Any],
    work_items: dict[str, dict[str, Any]],
    window: int = 5,
) -> dict[str, DimensionTrajectory]:
    recent = [entry for entry in scan_history if isinstance(entry, dict)][-window:]
    historical: dict[str, list[float]] = defaultdict(list)
    for entry in recent:
        dimension_scores = entry.get("dimension_scores")
        if not isinstance(dimension_scores, dict):
            continue
        for name, score_data in dimension_scores.items():
            if not isinstance(score_data, dict):
                continue
            strict = _as_float(score_data.get("strict"))
            if strict is None:
                strict = _as_float(score_data.get("score"))
            if strict is not None:
                historical[str(name)].append(round(strict, 2))

    investment_by_dim: Counter[str] = Counter()
    for issue in work_items.values():
        if not isinstance(issue, dict):
            continue
        if issue.get("resolved_at") or str(issue.get("status", "")) in _ACTIVELY_RESOLVED_STATUSES:
            investment_by_dim[_dimension_name_for_issue(issue)] += 1

    names = set(historical) | {
        str(name)
        for name, score_data in current_dim_scores.items()
        if isinstance(score_data, dict)
    }
    trajectories: dict[str, DimensionTrajectory] = {}
    for name in sorted(names):
        scores = list(historical.get(name, []))
        current = current_dim_scores.get(name, {})
        strict = None
        if isinstance(current, dict):
            strict = _as_float(current.get("strict"))
            if strict is None:
                strict = _as_float(current.get("score"))
        if strict is not None and (not scores or scores[-1] != round(strict, 2)):
            scores.append(round(strict, 2))
        scores = scores[-window:]
        delta = scores[-1] - scores[0] if len(scores) >= 2 else 0.0
        trend = _trend_from_delta(delta)
        if len(scores) >= 3 and max(scores) - min(scores) <= 0.5:
            trend = "stagnant"
        headroom = round(100.0 - (scores[-1] if scores else strict or 100.0), 2)
        trajectories[name] = DimensionTrajectory(
            name=name,
            strict_scores=scores,
            trend=trend,
            headroom=max(0.0, headroom),
            recent_investment=investment_by_dim.get(name, 0),
        )
    return trajectories


def file_churn_hotspots(work_items: dict[str, dict[str, Any]]) -> list[FileChurnEntry]:
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"resolved": 0, "open": 0, "detectors": set()}
    )
    for issue in work_items.values():
        if not isinstance(issue, dict):
            continue
        file_path = str(issue.get("file", "")).strip()
        if not file_path:
            continue
        bucket = buckets[file_path]
        bucket["detectors"].add(str(issue.get("detector", "")))
        status = str(issue.get("status", ""))
        if status == "open":
            bucket["open"] += 1
        elif issue.get("resolved_at") or status in _ACTIVELY_RESOLVED_STATUSES:
            bucket["resolved"] += 1
    hotspots = [
        FileChurnEntry(
            file=file_path,
            resolved_count=int(data["resolved"]),
            current_open_count=int(data["open"]),
            detectors=sorted(detector for detector in data["detectors"] if detector),
        )
        for file_path, data in buckets.items()
        if data["resolved"] and data["open"]
    ]
    hotspots.sort(
        key=lambda entry: (
            -(entry.resolved_count + entry.current_open_count),
            -len(entry.detectors),
            entry.file,
        )
    )
    return hotspots


def rework_loop_detection(work_items: dict[str, dict[str, Any]]) -> list[ReworkLoopEntry]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"resolved": 0, "open": 0, "reopen": 0, "files": set()}
    )
    for issue in work_items.values():
        if not isinstance(issue, dict):
            continue
        dimension = _dimension_name_for_issue(issue)
        if dimension == "unknown":
            continue
        bucket = grouped[dimension]
        file_path = str(issue.get("file", "")).strip()
        if file_path:
            bucket["files"].add(file_path)
        bucket["reopen"] += int(issue.get("reopen_count", 0) or 0)
        status = str(issue.get("status", ""))
        if status == "open":
            bucket["open"] += 1
        elif issue.get("resolved_at") or status in _ACTIVELY_RESOLVED_STATUSES:
            bucket["resolved"] += 1

    loops = [
        ReworkLoopEntry(
            dimension=dimension,
            resolved_count=int(data["resolved"]),
            new_open_count=int(data["open"]),
            reopen_count=int(data["reopen"]),
            affected_files=sorted(data["files"])[:10],
        )
        for dimension, data in grouped.items()
        if (data["resolved"] and data["open"]) or data["reopen"]
    ]
    loops.sort(
        key=lambda entry: (
            -(entry.resolved_count + entry.new_open_count + entry.reopen_count),
            entry.dimension,
        )
    )
    return loops


def completed_cluster_summary_from_progression(
    progression_events: list[dict[str, Any]],
) -> list[CompletedClusterSummary]:
    summaries: list[CompletedClusterSummary] = []
    for event in progression_events:
        if not isinstance(event, dict) or event.get("event_type") != "triage_complete":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        completed_at = str(event.get("timestamp", ""))
        cluster_summaries = payload.get("cluster_summaries")
        if not isinstance(cluster_summaries, list):
            continue
        for cluster in cluster_summaries:
            if not isinstance(cluster, dict):
                continue
            summaries.append(
                CompletedClusterSummary(
                    name=str(cluster.get("name", "")).strip() or "?",
                    thesis=str(cluster.get("thesis", "")).strip(),
                    issue_count=int(cluster.get("issue_count", 0) or 0),
                    completed_at=completed_at,
                )
            )
    return summaries[-10:]


def completed_cluster_summary_from_plan(
    plan: PlanModel,
    meta: dict[str, Any],
) -> list[CompletedClusterSummary]:
    last_completed_at = str(meta.get("last_completed_at", ""))
    completed = plan.get("completed_clusters", [])
    summaries: list[CompletedClusterSummary] = []
    if not isinstance(completed, list):
        return summaries
    for cluster in completed:
        if not isinstance(cluster, dict):
            continue
        completed_at = str(cluster.get("completed_at", ""))
        if last_completed_at and completed_at and completed_at <= last_completed_at:
            continue
        issue_ids = cluster.get("issue_ids", [])
        summaries.append(
            CompletedClusterSummary(
                name=str(cluster.get("name", "")).strip() or "?",
                thesis=str(cluster.get("thesis") or cluster.get("description") or "").strip(),
                issue_count=len(issue_ids) if isinstance(issue_ids, list) else 0,
                completed_at=completed_at,
            )
        )
    return summaries[-10:]


def execution_pattern_analysis(
    execution_log: list[dict[str, Any]],
    window_days: int = 30,
) -> ExecutionPatterns:
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    relevant: list[dict[str, Any]] = []
    for entry in execution_log:
        if not isinstance(entry, dict):
            continue
        timestamp = _parse_iso_datetime(entry.get("timestamp"))
        if timestamp is not None and timestamp < cutoff:
            continue
        relevant.append(entry)
    total_resolved = sum(
        len(entry.get("issue_ids", [])) if isinstance(entry.get("issue_ids"), list) else 0
        for entry in relevant
        if entry.get("action") == "resolve"
    )
    total_done = sum(
        len(entry.get("issue_ids", [])) if isinstance(entry.get("issue_ids"), list) else 0
        for entry in relevant
        if entry.get("action") == "done"
    )
    total_skipped = sum(
        len(entry.get("issue_ids", [])) if isinstance(entry.get("issue_ids"), list) else 0
        for entry in relevant
        if entry.get("action") == "skip"
    )
    cluster_sizes = [
        len(entry.get("issue_ids", []))
        for entry in relevant
        if entry.get("action") == "cluster_done" and isinstance(entry.get("issue_ids"), list)
    ]
    denominator = total_resolved + total_done + total_skipped
    skip_rate = round(total_skipped / denominator, 3) if denominator else 0.0
    avg_cluster_size = round(sum(cluster_sizes) / len(cluster_sizes), 2) if cluster_sizes else 0.0
    return ExecutionPatterns(
        total_resolved=total_resolved,
        total_skipped=total_skipped,
        total_done=total_done,
        skip_rate=skip_rate,
        avg_cluster_size=avg_cluster_size,
    )


def wontfix_debt_trajectory(
    scan_history: list[dict[str, Any]],
    work_items: dict[str, dict[str, Any]],
    dim_scores: dict[str, Any],
) -> DebtTrajectory:
    current_wontfix = sum(
        1
        for issue in work_items.values()
        if isinstance(issue, dict)
        and str(issue.get("status", "")) in {"wontfix", "false_positive"}
    )
    gaps = []
    for name, score_data in dim_scores.items():
        if not isinstance(score_data, dict):
            continue
        overall = _as_float(score_data.get("score"))
        strict = _as_float(score_data.get("strict"))
        if overall is None or strict is None:
            continue
        gaps.append((str(name), round(overall - strict, 2)))
    worst_dimension, worst_gap = (None, 0.0)
    if gaps:
        worst_dimension, worst_gap = max(gaps, key=lambda item: item[1])

    recent_gaps = []
    for entry in [history for history in scan_history if isinstance(history, dict)][-5:]:
        overall = _as_float(entry.get("overall_score"))
        strict = _as_float(entry.get("strict_score"))
        if overall is None or strict is None:
            continue
        recent_gaps.append(round(overall - strict, 2))
    trend = "stable"
    if len(recent_gaps) >= 2:
        delta = recent_gaps[-1] - recent_gaps[0]
        if delta > 0.5:
            trend = "growing"
        elif delta < -0.5:
            trend = "shrinking"
    return DebtTrajectory(
        current_wontfix=current_wontfix,
        trend=trend,
        worst_dimension=worst_dimension,
        worst_dimension_gap=worst_gap,
    )


def commit_history_analysis(
    commit_log: list[dict[str, Any]],
    *,
    window_days: int = 30,
) -> CommitHistoryInsights:
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    records = [record for record in commit_log if isinstance(record, dict)]
    recent = []
    for record in records:
        recorded_at = _parse_iso_datetime(record.get("recorded_at"))
        if recorded_at is None or recorded_at >= cutoff:
            recent.append(record)
    cluster_names = sorted(
        {
            str(record.get("cluster_name", "")).strip()
            for record in recent
            if str(record.get("cluster_name", "")).strip()
        }
    )
    latest_note = None
    for record in reversed(records):
        note = str(record.get("note", "")).strip()
        if note:
            latest_note = note
            break
    return CommitHistoryInsights(
        total_commits=len(records),
        recent_commits=len(recent),
        committed_issue_count=sum(
            len(record.get("issue_ids", []))
            for record in records
            if isinstance(record.get("issue_ids"), list)
        ),
        latest_note=latest_note,
        recent_cluster_names=cluster_names[:10],
    )


def lifecycle_inventory(
    state: StateModel,
    plan: PlanModel,
) -> dict[str, Any]:
    work_items = state.get("work_items") or state.get("issues", {})
    queue_order = plan.get("queue_order", [])
    skipped = plan.get("skipped", {})
    promoted_ids = plan.get("promoted_ids", [])
    prioritized_ids = [
        issue_id
        for issue_id in queue_order
        if isinstance(issue_id, str)
        and not issue_id.startswith(("triage::", "workflow::", "subjective::"))
    ]
    backlog_by_dimension: Counter[str] = Counter()
    if isinstance(work_items, dict):
        queued = set(prioritized_ids)
        skipped_ids = set(skipped.keys()) if isinstance(skipped, dict) else set()
        for issue_id, issue in work_items.items():
            if not isinstance(issue, dict) or str(issue.get("status", "")) != "open":
                continue
            if issue_id in queued or issue_id in skipped_ids:
                continue
            backlog_by_dimension[_dimension_name_for_issue(issue)] += 1

    skipped_by_reason: Counter[str] = Counter()
    if isinstance(skipped, dict):
        for entry in skipped.values():
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("kind", "")).strip() or "unknown"
            skipped_by_reason[kind] += 1

    clusters = plan.get("clusters", {})
    cluster_names = [
        name
        for name, cluster in clusters.items()
        if isinstance(cluster, dict) and cluster.get("issue_ids")
    ] if isinstance(clusters, dict) else []

    return {
        "backlog_by_dimension": dict(sorted(backlog_by_dimension.items())),
        "skipped_by_reason": dict(sorted(skipped_by_reason.items())),
        "deferred_count": len(plan.get("deferred", [])) if isinstance(plan.get("deferred"), list) else 0,
        "prioritized_ids": prioritized_ids,
        "cluster_names": sorted(cluster_names),
        "promoted_count": len(promoted_ids) if isinstance(promoted_ids, list) else 0,
    }


def collect_strategist_input(
    state: StateModel,
    plan: PlanModel,
    *,
    lookback_scans: int = 5,
    progression_events: list[dict[str, Any]] | None = None,
) -> StrategistInput:
    scan_history = state.get("scan_history", []) if isinstance(state.get("scan_history"), list) else []
    meta = plan.get("epic_triage_meta", {}) if isinstance(plan.get("epic_triage_meta"), dict) else {}
    work_items = state.get("work_items") or state.get("issues", {})
    open_review, resolved_review = _open_review_and_resolved_review_issues(state)
    recurring = detect_recurring_patterns(open_review, resolved_review)
    progression = progression_events or []
    completed_clusters = completed_cluster_summary_from_progression(progression)
    if not completed_clusters:
        completed_clusters = completed_cluster_summary_from_plan(plan, meta)

    inventory = lifecycle_inventory(state, plan)

    # Extract cycle start score from plan for cross-cycle regression detection
    _plan_start = plan.get("plan_start_scores") or {}
    _prev_start = plan.get("previous_plan_start_scores") or {}
    # Use the higher of plan_start or previous_plan_start as the cycle baseline
    _start_strict = _as_float(_plan_start.get("strict")) if _plan_start else None
    _prev_strict = _as_float(_prev_start.get("strict")) if _prev_start else None
    _cycle_start = max(filter(None, [_start_strict, _prev_strict]), default=None)

    return StrategistInput(
        score_trajectory=score_trajectory(scan_history, window=lookback_scans, cycle_start_score=_cycle_start),
        dimension_trajectories=dimension_trajectories(
            scan_history,
            state.get("dimension_scores", {}) if isinstance(state.get("dimension_scores"), dict) else {},
            work_items if isinstance(work_items, dict) else {},
            window=lookback_scans,
        ),
        file_churn=file_churn_hotspots(work_items if isinstance(work_items, dict) else {}),
        rework_loops=rework_loop_detection(work_items if isinstance(work_items, dict) else {}),
        completed_clusters=completed_clusters,
        execution_patterns=execution_pattern_analysis(
            plan.get("execution_log", []) if isinstance(plan.get("execution_log"), list) else []
        ),
        debt_trajectory=wontfix_debt_trajectory(
            scan_history,
            work_items if isinstance(work_items, dict) else {},
            state.get("dimension_scores", {}) if isinstance(state.get("dimension_scores"), dict) else {},
        ),
        commit_history=commit_history_analysis(
            plan.get("commit_log", []) if isinstance(plan.get("commit_log"), list) else []
        ),
        recurring_patterns=recurring,
        current_dimension_scores=state.get("dimension_scores", {}) if isinstance(state.get("dimension_scores"), dict) else {},
        open_issue_count=sum(
            1
            for issue in (work_items or {}).values()
            if isinstance(issue, dict) and str(issue.get("status", "")) == "open"
        ),
        scan_count=int(state.get("scan_count", len(scan_history)) or 0),
        backlog_by_dimension=inventory["backlog_by_dimension"],
        skipped_by_reason=inventory["skipped_by_reason"],
        deferred_count=inventory["deferred_count"],
        prioritized_ids=inventory["prioritized_ids"],
        cluster_names=inventory["cluster_names"],
        promoted_count=inventory["promoted_count"],
    )


__all__ = [
    "CommitHistoryInsights",
    "CompletedClusterSummary",
    "DebtTrajectory",
    "DimensionTrajectory",
    "ExecutionPatterns",
    "FileChurnEntry",
    "ReworkLoopEntry",
    "ScoreTrajectory",
    "StrategistInput",
    "collect_strategist_input",
    "commit_history_analysis",
    "completed_cluster_summary_from_plan",
    "completed_cluster_summary_from_progression",
    "dimension_trajectories",
    "execution_pattern_analysis",
    "file_churn_hotspots",
    "lifecycle_inventory",
    "rework_loop_detection",
    "score_trajectory",
    "wontfix_debt_trajectory",
]
