"""State mutation helpers for triage stage records."""

from __future__ import annotations

from typing import TypedDict

from desloppify.state_io import utc_now

from ..stage_queue import cascade_clear_later_confirmations


class ObserveAssessmentRecord(TypedDict):
    """Persisted observe-stage verdict for one cited issue hash."""

    hash: str
    verdict: str
    verdict_reasoning: str
    files_read: list[str]
    recommendation: str


class StrategizeRecord(TypedDict, total=False):
    stage: str
    report: str
    timestamp: str
    score_trend: str
    focus_dimensions: list[str]
    anti_pattern_count: int
    confirmed_at: str
    confirmed_text: str


class ObserveRecord(TypedDict, total=False):
    stage: str
    report: str
    cited_ids: list[str]
    timestamp: str
    issue_count: int
    dimension_names: list[str]
    dimension_counts: dict[str, int]
    assessments: list[ObserveAssessmentRecord]
    confirmed_at: str
    confirmed_text: str


class ReflectRecord(TypedDict, total=False):
    stage: str
    report: str
    cited_ids: list[str]
    timestamp: str
    issue_count: int
    missing_issue_ids: list[str]
    duplicate_issue_ids: list[str]
    recurring_dims: list[str]
    disposition_ledger: list[dict[str, str]]
    confirmed_at: str
    confirmed_text: str


class OrganizeRecord(TypedDict, total=False):
    stage: str
    report: str
    cited_ids: list[str]
    timestamp: str
    issue_count: int
    confirmed_at: str
    confirmed_text: str
    reused_existing_plan: bool
    completion_note: str


class EnrichRecord(TypedDict, total=False):
    stage: str
    report: str
    timestamp: str
    shallow_count: int
    confirmed_at: str
    confirmed_text: str


class SenseCheckRecord(TypedDict, total=False):
    stage: str
    report: str
    timestamp: str
    confirmed_at: str
    confirmed_text: str
    value_decisions: dict[str, str]
    value_targets: list[str]


TriageStages = dict[
    str,
    StrategizeRecord | ObserveRecord | ReflectRecord | OrganizeRecord | EnrichRecord | SenseCheckRecord,
]


def resolve_reusable_report(
    report: str | None,
    existing_stage: dict | ObserveRecord | ReflectRecord | OrganizeRecord | EnrichRecord | SenseCheckRecord | None,
) -> tuple[str | None, bool]:
    if report:
        return report, False
    if existing_stage and existing_stage.get("report"):
        return existing_stage["report"], True
    return None, False


def record_observe_stage(
    stages: TriageStages,
    *,
    report: str,
    issue_count: int,
    cited_ids: list[str],
    existing_stage: ObserveRecord | None,
    is_reuse: bool,
    assessments: list[ObserveAssessmentRecord] | None = None,
    dimension_names: list[str] | None = None,
    dimension_counts: dict[str, int] | None = None,
) -> list[str]:
    observe: ObserveRecord = {
        "stage": "observe",
        "report": report,
        "cited_ids": cited_ids,
        "timestamp": utc_now(),
        "issue_count": issue_count,
    }
    if dimension_names is not None:
        observe["dimension_names"] = dimension_names
    if dimension_counts is not None:
        observe["dimension_counts"] = dimension_counts
    if assessments is not None:
        observe["assessments"] = assessments
    if is_reuse and existing_stage and existing_stage.get("confirmed_at"):
        observe["confirmed_at"] = existing_stage["confirmed_at"]
        observe["confirmed_text"] = existing_stage.get("confirmed_text", "")
    stages["observe"] = observe
    cleared = cascade_clear_later_confirmations(stages, "observe")
    if not is_reuse:
        observe.pop("confirmed_at", None)
        observe.pop("confirmed_text", None)
    return cleared


def record_strategize_stage(
    stages: TriageStages,
    *,
    report: str,
    briefing: dict,
    is_reuse: bool = False,
    existing_stage: StrategizeRecord | None = None,
) -> list[str]:
    strategize: StrategizeRecord = {
        "stage": "strategize",
        "report": report,
        "timestamp": utc_now(),
        "score_trend": str(briefing.get("score_trend", "stable")),
        "focus_dimensions": [
            str(entry.get("name", "")).strip()
            for entry in briefing.get("focus_dimensions", [])
            if isinstance(entry, dict) and str(entry.get("name", "")).strip()
        ],
        "anti_pattern_count": len(briefing.get("anti_patterns", []) or []),
        "confirmed_at": utc_now(),
        "confirmed_text": "auto-confirmed",
    }
    if is_reuse and existing_stage:
        strategize["confirmed_at"] = existing_stage.get("confirmed_at", strategize["confirmed_at"])
        strategize["confirmed_text"] = existing_stage.get("confirmed_text", strategize["confirmed_text"])
    stages["strategize"] = strategize
    return cascade_clear_later_confirmations(stages, "strategize")


def record_organize_stage(
    stages: TriageStages,
    *,
    report: str,
    issue_count: int,
    existing_stage: OrganizeRecord | None,
    is_reuse: bool,
) -> list[str]:
    organize: OrganizeRecord = {
        "stage": "organize",
        "report": report,
        "cited_ids": [],
        "timestamp": utc_now(),
        "issue_count": issue_count,
    }
    if is_reuse and existing_stage and existing_stage.get("confirmed_at"):
        organize["confirmed_at"] = existing_stage["confirmed_at"]
        organize["confirmed_text"] = existing_stage.get("confirmed_text", "")
    stages["organize"] = organize
    return cascade_clear_later_confirmations(stages, "organize")


def record_enrich_stage(
    stages: TriageStages,
    *,
    report: str,
    shallow_count: int,
    existing_stage: EnrichRecord | None,
    is_reuse: bool,
) -> list[str]:
    enrich: EnrichRecord = {
        "stage": "enrich",
        "report": report,
        "timestamp": utc_now(),
        "shallow_count": shallow_count,
    }
    if is_reuse and existing_stage and existing_stage.get("confirmed_at"):
        enrich["confirmed_at"] = existing_stage["confirmed_at"]
        enrich["confirmed_text"] = existing_stage.get("confirmed_text", "")
    stages["enrich"] = enrich
    return cascade_clear_later_confirmations(stages, "enrich")


def record_sense_check_stage(
    stages: TriageStages,
    *,
    report: str,
    existing_stage: SenseCheckRecord | None,
    is_reuse: bool,
    value_targets: list[str] | None = None,
) -> list[str]:
    sense_check: SenseCheckRecord = {
        "stage": "sense-check",
        "report": report,
        "timestamp": utc_now(),
    }
    if value_targets:
        sense_check["value_targets"] = list(value_targets)
    elif existing_stage and existing_stage.get("value_targets"):
        sense_check["value_targets"] = list(existing_stage["value_targets"])
    if is_reuse and existing_stage and existing_stage.get("confirmed_at"):
        sense_check["confirmed_at"] = existing_stage["confirmed_at"]
        sense_check["confirmed_text"] = existing_stage.get("confirmed_text", "")
    stages["sense-check"] = sense_check
    return cascade_clear_later_confirmations(stages, "sense-check")


def record_confirm_existing_completion(
    *,
    stages: TriageStages,
    note: str,
    issue_count: int,
    confirmed_text: str,
) -> None:
    stages["organize"] = {
        "stage": "organize",
        "report": f"[confirmed-existing] {note}",
        "cited_ids": [],
        "timestamp": utc_now(),
        "issue_count": issue_count,
        "confirmed_at": utc_now(),
        "confirmed_text": confirmed_text,
        "reused_existing_plan": True,
        "completion_note": note,
    }


__all__ = [
    "ObserveAssessmentRecord",
    "ObserveRecord",
    "ReflectRecord",
    "StrategizeRecord",
    "TriageStages",
    "record_confirm_existing_completion",
    "record_enrich_stage",
    "record_observe_stage",
    "record_organize_stage",
    "record_strategize_stage",
    "record_sense_check_stage",
    "resolve_reusable_report",
]
