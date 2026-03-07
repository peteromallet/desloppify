"""Core batch processing helpers for holistic review workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from desloppify.base.compatibility import NotRequired
from typing import TypedDict, cast

from desloppify.intelligence.review.feedback_contract import (
    DIMENSION_NOTE_ISSUES_KEY,
    HIGH_SCORE_ISSUES_NOTE_THRESHOLD,
    LEGACY_DIMENSION_NOTE_ISSUES_KEY,
    LEGACY_REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY,
    LOW_SCORE_ISSUE_THRESHOLD,
    REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY,
)
from desloppify.intelligence.review.importing.contracts_types import (
    ReviewIssuePayload,
)
from desloppify.intelligence.review.importing.contracts_validation import (
    validate_review_issue_payload,
)
from desloppify.intelligence.review.importing.payload import (
    normalize_legacy_findings_alias,
)
from desloppify.intelligence.review.issue_merge import (
    merge_list_fields,
    normalize_word_set,
    pick_longer_text,
    track_merged_from,
)

from .prompt_template import render_batch_prompt
from .scoring import DimensionMergeScorer

_DIMENSION_SCORER = DimensionMergeScorer()


class BatchIssuePayload(ReviewIssuePayload, total=False):  # type: ignore[call-arg]
    """Normalized issue payload passed across batch merge/import seams."""

    impact_scope: str
    fix_scope: str


class BatchDimensionNotePayload(TypedDict, total=False):
    """Normalized per-dimension evidence and scoring context."""

    evidence: list[str]
    impact_scope: str
    fix_scope: str
    confidence: str
    issues_preventing_higher_score: str
    sub_axes: dict[str, float]


class BatchQualityPayload(TypedDict, total=False):
    """Quality telemetry attached to each normalized batch output."""

    dimension_coverage: float
    evidence_density: float
    high_score_missing_issue_note: float
    high_score_without_risk: NotRequired[float]


class BatchResultPayload(TypedDict):
    """Canonical normalized batch payload consumed by merge routines."""

    assessments: dict[str, float]
    issues: list[BatchIssuePayload]
    dimension_notes: dict[str, BatchDimensionNotePayload]
    quality: BatchQualityPayload


@dataclass(frozen=True)
class NormalizedBatchIssue:
    """Typed internal issue contract for normalized batch payloads."""

    dimension: str
    identifier: str
    summary: str
    confidence: str
    suggestion: str
    related_files: list[str]
    evidence: list[str]
    impact_scope: str
    fix_scope: str
    reasoning: str = ""
    evidence_lines: list[int] | None = None

    def to_payload(self) -> BatchIssuePayload:
        payload: BatchIssuePayload = {  # type: ignore[assignment]
            "dimension": self.dimension,
            "identifier": self.identifier,
            "summary": self.summary,
            "confidence": self.confidence,
            "suggestion": self.suggestion,
            "related_files": list(self.related_files),
            "evidence": list(self.evidence),
            "impact_scope": self.impact_scope,
            "fix_scope": self.fix_scope,
        }
        if self.reasoning:
            payload["reasoning"] = self.reasoning
        if self.evidence_lines:
            payload["evidence_lines"] = list(self.evidence_lines)
        return payload


def parse_batch_selection(raw: str | None, batch_count: int) -> list[int]:
    """Parse optional 1-based CSV list of batches."""
    if not raw:
        return list(range(batch_count))

    selected: list[int] = []
    seen: set[int] = set()
    for token in raw.split(","):
        text = token.strip()
        if not text:
            continue
        idx_1 = int(text)
        if idx_1 < 1 or idx_1 > batch_count:
            raise ValueError(f"batch index {idx_1} out of range 1..{batch_count}")
        idx_0 = idx_1 - 1
        if idx_0 in seen:
            continue
        seen.add(idx_0)
        selected.append(idx_0)
    return selected


def extract_json_payload(raw: str, *, log_fn) -> dict[str, object] | None:
    """Best-effort extraction of first JSON object from agent output text."""
    text = raw.strip()
    if not text:
        return None

    decoder = json.JSONDecoder()
    last_decode_error: json.JSONDecodeError | None = None
    for start, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            last_decode_error = exc
            continue
        if (
            isinstance(obj, dict)
            and isinstance(obj.get("assessments"), dict)
            and isinstance(obj.get("issues"), list)
        ):
            return obj
    if last_decode_error is not None:
        log_fn(f"  batch output JSON parse failed: {last_decode_error.msg}")
    else:
        log_fn("  batch output JSON parse failed: no valid payload found")
    return None


def _validate_dimension_note(
    key: str,
    note_raw: object,
) -> tuple[list[object], str, str, str, str]:
    """Validate a single dimension_notes entry and return parsed fields.

    Returns (evidence, impact_scope, fix_scope, confidence, issues_preventing_higher_score).
    Raises ValueError on invalid structure.
    """
    if not isinstance(note_raw, dict):
        raise ValueError(
            f"dimension_notes missing object for assessed dimension: {key}"
        )
    evidence = note_raw.get("evidence")
    impact_scope = note_raw.get("impact_scope")
    fix_scope = note_raw.get("fix_scope")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(
            f"dimension_notes.{key}.evidence must be a non-empty array"
        )
    if not isinstance(impact_scope, str) or not impact_scope.strip():
        raise ValueError(
            f"dimension_notes.{key}.impact_scope must be a non-empty string"
        )
    if not isinstance(fix_scope, str) or not fix_scope.strip():
        raise ValueError(
            f"dimension_notes.{key}.fix_scope must be a non-empty string"
        )

    confidence_raw = str(note_raw.get("confidence", "medium")).strip().lower()
    confidence = (
        confidence_raw if confidence_raw in {"high", "medium", "low"} else "medium"
    )
    issues_note = str(note_raw.get(DIMENSION_NOTE_ISSUES_KEY, "")).strip()
    if not issues_note:
        issues_note = str(note_raw.get(LEGACY_DIMENSION_NOTE_ISSUES_KEY, "")).strip()
    return evidence, impact_scope, fix_scope, confidence, issues_note


def _normalize_abstraction_sub_axes(
    note_raw: dict[str, object],
    abstraction_sub_axes: tuple[str, ...],
) -> dict[str, float]:
    """Extract and clamp abstraction_fitness sub-axis scores from a note."""
    sub_axes_raw = note_raw.get("sub_axes")
    if sub_axes_raw is not None and not isinstance(sub_axes_raw, dict):
        raise ValueError(
            "dimension_notes.abstraction_fitness.sub_axes must be an object"
        )
    if not isinstance(sub_axes_raw, dict):
        return {}

    normalized: dict[str, float] = {}
    for axis in abstraction_sub_axes:
        axis_value = sub_axes_raw.get(axis)
        if axis_value is None:
            continue
        if isinstance(axis_value, bool) or not isinstance(
            axis_value, int | float
        ):
            raise ValueError(
                f"dimension_notes.abstraction_fitness.sub_axes.{axis} "
                "must be numeric"
            )
        normalized[axis] = round(
            max(0.0, min(100.0, float(axis_value))),
            1,
        )
    return normalized


def _normalize_issues(
    raw_issues: object,
    dimension_notes: dict[str, BatchDimensionNotePayload],
    *,
    max_batch_issues: int,
    allowed_dims: set[str],
    low_score_dimensions: set[str] | None = None,
) -> list[NormalizedBatchIssue]:
    """Validate and normalize the issues array from a batch payload."""
    if not isinstance(raw_issues, list):
        raise ValueError("issues must be an array")

    issues: list[NormalizedBatchIssue] = []
    errors: list[str] = []
    for idx, item in enumerate(raw_issues):
        issue: ReviewIssuePayload | None
        issue, issue_errors = validate_review_issue_payload(
            item,
            label=f"issues[{idx}]",
            allowed_dimensions=allowed_dims,
            allow_dismissed=False,
        )
        if issue_errors:
            errors.extend(issue_errors)
            continue
        if issue is None:
            raise ValueError(
                "batch issue payload missing after validation succeeded"
            )

        dim = issue["dimension"]
        note = dimension_notes.get(dim, {})
        impact_scope = str(
            (item if isinstance(item, dict) else {}).get(
                "impact_scope", note.get("impact_scope", "")
            )
        ).strip()
        fix_scope = str(
            (item if isinstance(item, dict) else {}).get(
                "fix_scope", note.get("fix_scope", "")
            )
        ).strip()
        if not impact_scope or not fix_scope:
            errors.append(
                f"issues[{idx}] requires impact_scope and fix_scope "
                "(or dimension_notes defaults)"
            )
            continue
        issues.append(
            NormalizedBatchIssue(
                dimension=issue["dimension"],
                identifier=issue["identifier"],
                summary=issue["summary"],
                confidence=issue["confidence"],
                suggestion=issue["suggestion"],
                related_files=list(issue.get("related_files", [])),
                evidence=list(issue.get("evidence", [])),
                impact_scope=impact_scope,
                fix_scope=fix_scope,
                reasoning=str(issue.get("reasoning", "")),
                evidence_lines=list(issue.get("evidence_lines", []))
                if isinstance(issue.get("evidence_lines"), list)
                else None,
            )
        )
    if errors:
        visible = errors[:10]
        remaining = len(errors) - len(visible)
        if remaining > 0:
            visible.append(f"... {remaining} additional issue schema error(s) omitted")
        raise ValueError("; ".join(visible))
    if len(issues) <= max_batch_issues:
        return issues

    required_dims = set(low_score_dimensions or set())
    if not required_dims:
        return issues[:max_batch_issues]

    # Preserve at least one issue per low-score dimension before trimming.
    selected: list[NormalizedBatchIssue] = []
    selected_indexes: set[int] = set()
    covered: set[str] = set()
    for idx, issue in enumerate(issues):
        if len(selected) >= max_batch_issues:
            break
        dim = issue.dimension.strip()
        if dim not in required_dims or dim in covered:
            continue
        selected.append(issue)
        selected_indexes.add(idx)
        covered.add(dim)

    for idx, issue in enumerate(issues):
        if len(selected) >= max_batch_issues:
            break
        if idx in selected_indexes:
            continue
        selected.append(issue)
    return selected


def _low_score_dimensions(assessments: dict[str, float]) -> set[str]:
    """Return assessed dimensions requiring explicit defect issues."""
    return {
        dim
        for dim, score in assessments.items()
        if score < LOW_SCORE_ISSUE_THRESHOLD
    }


def _enforce_low_score_issues(
    *,
    assessments: dict[str, float],
    issues: list[NormalizedBatchIssue],
) -> None:
    """Fail closed when low scores do not report explicit issues."""
    required_dims = _low_score_dimensions(assessments)
    if not required_dims:
        return
    issue_dims = {
        issue.dimension.strip() for issue in issues
    }
    missing = sorted(dim for dim in required_dims if dim not in issue_dims)
    if not missing:
        return
    joined = ", ".join(missing)
    raise ValueError(
        "low-score dimensions must include at least one explicit issue: "
        f"{joined} (threshold {LOW_SCORE_ISSUE_THRESHOLD:.1f})"
    )


def _compute_batch_quality(
    assessments: dict[str, float],
    issues: list[NormalizedBatchIssue],
    dimension_notes: dict[str, BatchDimensionNotePayload],
    high_score_missing_issue_note: float,
) -> BatchQualityPayload:
    """Compute quality metrics for a single batch result."""
    return {
        "dimension_coverage": round(
            len(assessments) / max(len(assessments), 1),
            3,
        ),
        "evidence_density": round(
            sum(len(note.get("evidence", [])) for note in dimension_notes.values())
            / max(len(issues), 1),
            3,
        ),
        "high_score_missing_issue_note": high_score_missing_issue_note,
    }


def normalize_batch_result(
    payload: dict[str, object],
    allowed_dims: set[str],
    *,
    max_batch_issues: int,
    abstraction_sub_axes: tuple[str, ...],
) -> tuple[
    dict[str, float],
    list[BatchIssuePayload],
    dict[str, BatchDimensionNotePayload],
    BatchQualityPayload,
]:
    """Validate and normalize one batch payload."""
    if "assessments" not in payload:
        raise ValueError("payload missing required key: assessments")
    key_error = normalize_legacy_findings_alias(
        payload,
        missing_issues_error="payload missing required key: issues",
    )
    if key_error is not None:
        raise ValueError(key_error)

    raw_assessments = payload.get("assessments")
    if not isinstance(raw_assessments, dict):
        raise ValueError("assessments must be an object")

    raw_dimension_notes = payload.get("dimension_notes", {})
    if not isinstance(raw_dimension_notes, dict):
        raise ValueError("dimension_notes must be an object")

    assessments: dict[str, float] = {}
    dimension_notes: dict[str, BatchDimensionNotePayload] = {}
    high_score_missing_issue_note = 0.0
    for key, value in raw_assessments.items():
        if not isinstance(key, str) or not key:
            continue
        if key not in allowed_dims:
            continue
        if isinstance(value, bool):
            continue
        if not isinstance(value, int | float):
            continue
        score = round(max(0.0, min(100.0, float(value))), 1)

        note_raw = raw_dimension_notes.get(key)
        evidence, impact_scope, fix_scope, confidence, issues_note = (
            _validate_dimension_note(key, note_raw)
        )
        if not isinstance(note_raw, dict):
            raise ValueError(
                f"dimension_notes missing object for assessed dimension: {key}"
            )
        if score > HIGH_SCORE_ISSUES_NOTE_THRESHOLD and not issues_note:
            high_score_missing_issue_note += 1

        normalized_sub_axes: dict[str, float] = {}
        if key == "abstraction_fitness":
            normalized_sub_axes = _normalize_abstraction_sub_axes(
                note_raw, abstraction_sub_axes
            )

        assessments[key] = score
        dimension_notes[key] = {
            "evidence": [str(item).strip() for item in evidence if str(item).strip()],
            "impact_scope": impact_scope.strip(),
            "fix_scope": fix_scope.strip(),
            "confidence": confidence,
            "issues_preventing_higher_score": issues_note,
        }
        if normalized_sub_axes:
            dimension_notes[key]["sub_axes"] = normalized_sub_axes

    issues = _normalize_issues(
        payload.get("issues"),
        dimension_notes,
        max_batch_issues=max_batch_issues,
        allowed_dims=allowed_dims,
        low_score_dimensions=_low_score_dimensions(assessments),
    )
    _enforce_low_score_issues(assessments=assessments, issues=issues)

    quality = _compute_batch_quality(
        assessments,
        issues,
        dimension_notes,
        high_score_missing_issue_note,
    )
    return (
        assessments,
        [issue.to_payload() for issue in issues],
        dimension_notes,
        quality,
    )


def assessment_weight(
    *,
    dimension: str,
    issues: list[BatchIssuePayload],
    dimension_notes: dict[str, BatchDimensionNotePayload],
) -> float:
    """Evidence-weighted assessment score weight with a neutral floor.

    Weighting is evidence-based and score-independent: the raw score does not
    influence how much weight a batch contributes during merge.
    """
    note = dimension_notes.get(dimension, {})
    note_evidence = len(note.get("evidence", [])) if isinstance(note, dict) else 0
    issue_count = sum(
        1
        for issue in issues
        if str(issue.get("dimension", "")).strip() == dimension
    )
    return float(1 + note_evidence + issue_count)


def _issue_pressure_by_dimension(
    issues: list[BatchIssuePayload],
    *,
    dimension_notes: dict[str, BatchDimensionNotePayload],
) -> tuple[dict[str, float], dict[str, int]]:
    """Summarize how strongly issues should pull dimension scores down."""
    return _DIMENSION_SCORER.issue_pressure_by_dimension(
        issues,
        dimension_notes=dimension_notes,
    )


def _accumulate_batch_scores(
    result: BatchResultPayload,
    *,
    score_buckets: dict[str, list[tuple[float, float]]],
    score_raw_by_dim: dict[str, list[float]],
    merged_dimension_notes: dict[str, BatchDimensionNotePayload],
    abstraction_axis_scores: dict[str, list[tuple[float, float]]],
    abstraction_sub_axes: tuple[str, ...],
) -> None:
    """Accumulate assessment scores, dimension notes, and sub-axis data from one batch."""
    result_issues = result.get("issues", [])
    result_notes = result.get("dimension_notes", {})
    for key, score in result.get("assessments", {}).items():
        if isinstance(score, bool):
            continue
        score_value = float(score)
        weight = assessment_weight(
            dimension=key,
            issues=result_issues,
            dimension_notes=result_notes,
        )
        score_buckets.setdefault(key, []).append((score_value, weight))
        score_raw_by_dim.setdefault(key, []).append(score_value)

        note = result_notes.get(key)
        existing = merged_dimension_notes.get(key)
        existing_evidence = (
            len(existing.get("evidence", [])) if isinstance(existing, dict) else -1
        )
        current_evidence = (
            len(note.get("evidence", [])) if isinstance(note, dict) else -1
        )
        if current_evidence > existing_evidence and note is not None:
            merged_dimension_notes[key] = note

        if key == "abstraction_fitness" and isinstance(note, dict):
            sub_axes = note.get("sub_axes")
            if isinstance(sub_axes, dict):
                for axis in abstraction_sub_axes:
                    axis_score = sub_axes.get(axis)
                    if isinstance(axis_score, bool) or not isinstance(
                        axis_score, int | float
                    ):
                        continue
                    abstraction_axis_scores[axis].append(
                        (float(axis_score), weight)
                    )


def _issue_identity_key(issue: BatchIssuePayload) -> str:
    """Build a stable concept key; prefer dimension+identifier when available."""
    dim = str(issue.get("dimension", "")).strip()
    ident = str(issue.get("identifier", "")).strip()
    if ident:
        return f"{dim}::{ident}"
    summary = str(issue.get("summary", "")).strip()
    summary_terms = sorted(normalize_word_set(summary))
    if summary_terms:
        return f"{dim}::summary::{','.join(summary_terms[:8])}"
    return f"{dim}::{summary}"


def _merge_issue_payload(
    existing: BatchIssuePayload, incoming: BatchIssuePayload
) -> None:
    """Merge two concept-equivalent issues into the existing payload."""
    merge_list_fields(existing, incoming, ("related_files", "evidence"))
    # Prefer richer summary/suggestion text when they differ.
    pick_longer_text(existing, incoming, "summary")
    pick_longer_text(existing, incoming, "suggestion")
    track_merged_from(existing, str(incoming.get("identifier", "")).strip())


def _should_merge_issues(
    existing: BatchIssuePayload, incoming: BatchIssuePayload
) -> bool:
    """Check whether two key-matched issues are similar enough to merge."""
    existing_summary = normalize_word_set(str(existing.get("summary", "")))
    incoming_summary = normalize_word_set(str(incoming.get("summary", "")))
    if existing_summary and incoming_summary:
        overlap = len(existing_summary & incoming_summary)
        union = len(existing_summary | incoming_summary)
        if union and overlap / union >= 0.3:
            return True
    # Fall back to related-file overlap
    existing_files = set(cast(list[str], existing.get("related_files", [])))
    incoming_files = set(cast(list[str], incoming.get("related_files", [])))
    if existing_files and incoming_files:
        return bool(existing_files & incoming_files)
    # When no corroborating signal is available, allow merge
    return not existing_summary or not incoming_summary


def _accumulate_batch_quality(
    result: BatchResultPayload,
    *,
    coverage_values: list[float],
    evidence_density_values: list[float],
) -> float:
    """Accumulate quality metrics from one batch. Returns high-score-missing-issues delta."""
    quality: object = result.get("quality", {})
    if not isinstance(quality, dict):
        return 0.0
    coverage = quality.get("dimension_coverage")
    density = quality.get("evidence_density")
    missing_issue_note = quality.get(REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY)
    if not isinstance(missing_issue_note, int | float):
        missing_issue_note = quality.get(
            LEGACY_REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY
        )
    if isinstance(coverage, int | float):
        coverage_values.append(float(coverage))
    if isinstance(density, int | float):
        evidence_density_values.append(float(density))
    return (
        float(missing_issue_note)
        if isinstance(missing_issue_note, int | float)
        else 0.0
    )


def _compute_merged_assessments(
    score_buckets: dict[str, list[tuple[float, float]]],
    score_raw_by_dim: dict[str, list[float]],
    issue_pressure_by_dim: dict[str, float],
    issue_count_by_dim: dict[str, int],
) -> dict[str, float]:
    """Compute pressure-adjusted weighted mean for each dimension."""
    return _DIMENSION_SCORER.merge_scores(
        score_buckets,
        score_raw_by_dim,
        issue_pressure_by_dim,
        issue_count_by_dim,
    )


def _compute_abstraction_components(
    merged_assessments: dict[str, float],
    abstraction_axis_scores: dict[str, list[tuple[float, float]]],
    *,
    abstraction_sub_axes: tuple[str, ...],
    abstraction_component_names: dict[str, str],
) -> dict[str, float] | None:
    """Compute weighted abstraction sub-axis component scores.

    Returns component_scores dict, or None if abstraction_fitness is not assessed.
    """
    abstraction_score = merged_assessments.get("abstraction_fitness")
    if abstraction_score is None:
        return None

    component_scores: dict[str, float] = {}
    for axis in abstraction_sub_axes:
        weighted = abstraction_axis_scores.get(axis, [])
        if not weighted:
            continue
        numerator = sum(score * weight for score, weight in weighted)
        denominator = sum(weight for _, weight in weighted)
        if denominator <= 0:
            continue
        component_scores[abstraction_component_names[axis]] = round(
            max(0.0, min(100.0, numerator / denominator)),
            1,
        )
    return component_scores if component_scores else None


def merge_batch_results(
    batch_results: list[BatchResultPayload],
    *,
    abstraction_sub_axes: tuple[str, ...],
    abstraction_component_names: dict[str, str],
) -> dict[str, object]:
    """Deterministically merge assessments/issues across batch outputs."""
    from .merge import merge_batch_results as _merge_batch_results

    return _merge_batch_results(
        batch_results,
        abstraction_sub_axes=abstraction_sub_axes,
        abstraction_component_names=abstraction_component_names,
    )


def build_batch_prompt(
    *,
    repo_root: Path,
    packet_path: Path,
    batch_index: int,
    batch: dict[str, object],
) -> str:
    """Render one subagent prompt for a holistic investigation batch."""
    return render_batch_prompt(
        repo_root=repo_root,
        packet_path=packet_path,
        batch_index=batch_index,
        batch=batch,
    )


__all__ = [
    "assessment_weight",
    "build_batch_prompt",
    "extract_json_payload",
    "merge_batch_results",
    "normalize_batch_result",
    "parse_batch_selection",
]
