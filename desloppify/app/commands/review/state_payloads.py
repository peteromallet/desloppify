"""Typed state payload helpers for review command flows."""

from __future__ import annotations

from typing import TypedDict, cast

from desloppify.engine._state.schema_types_review import (
    AssessmentImportAuditEntry,
)


class SubjectiveAssessmentPayload(TypedDict, total=False):
    score: float
    source: str
    assessment_import_id: str
    assessed_at: str
    needs_review_refresh: bool
    stale_since: str
    refresh_reason: str
    provisional_override: bool
    provisional_until_scan: int
    placeholder: bool
    components: list[str]
    component_scores: dict[str, float]


def subjective_assessment_store(
    state: dict,
) -> dict[str, SubjectiveAssessmentPayload]:
    """Return normalized subjective assessment mapping from state."""
    store = state.get("subjective_assessments")
    if not isinstance(store, dict):
        store = {}
        state["subjective_assessments"] = store

    normalized: dict[str, SubjectiveAssessmentPayload] = {}
    for key, value in list(store.items()):
        if not isinstance(key, str):
            continue
        payload: SubjectiveAssessmentPayload
        if isinstance(value, dict):
            payload = cast(SubjectiveAssessmentPayload, value)
        elif isinstance(value, int | float) and not isinstance(value, bool):
            payload = {"score": float(value)}
            store[key] = payload
        else:
            payload = {}
            store[key] = payload
        normalized[key] = payload
    return normalized


def append_assessment_import_audit(
    state: dict,
    entry: AssessmentImportAuditEntry,
) -> None:
    """Append typed assessment import audit entry into state."""
    audit = state.get("assessment_import_audit")
    if not isinstance(audit, list):
        audit = []
        state["assessment_import_audit"] = audit
    audit.append(entry)


__all__ = [
    "AssessmentImportAuditEntry",
    "SubjectiveAssessmentPayload",
    "append_assessment_import_audit",
    "subjective_assessment_store",
]
