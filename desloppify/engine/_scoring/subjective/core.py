"""Subjective-dimension scoring helpers."""

from __future__ import annotations

from desloppify.base.subjective_dimension_catalog import DISPLAY_NAMES
from desloppify.base.text_utils import is_numeric
from desloppify.engine._scoring.policy.core import SUBJECTIVE_CHECKS
from desloppify.intelligence.review.dimensions.metadata import (
    dimension_display_name as metadata_dimension_display_name,
)
from desloppify.intelligence.review.dimensions.metadata import (
    dimension_weight as metadata_dimension_weight,
)
from desloppify.intelligence.review.dimensions.holistic import DIMENSIONS

def _display_fallback(dim_name: str) -> str:
    words = dim_name.replace("_", " ")
    return words[0].upper() + words[1:] if words else words


def _normalize_dimension_key(dim_name: object) -> str:
    if not isinstance(dim_name, str):
        return ""
    return "_".join(dim_name.strip().lower().replace("-", "_").split())


def _primary_lang_from_issues(issues: dict) -> str | None:
    counts: dict[str, int] = {}
    for issue in issues.values():
        if not isinstance(issue, dict):
            continue
        raw_lang = issue.get("lang")
        if not isinstance(raw_lang, str) or not raw_lang.strip():
            continue
        key = raw_lang.strip().lower()
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _dimension_display_name(dim_name: str, *, lang_name: str | None) -> str:
    return str(metadata_dimension_display_name(dim_name, lang_name=lang_name))


def _dimension_weight(dim_name: str, *, lang_name: str | None) -> float:
    return float(metadata_dimension_weight(dim_name, lang_name=lang_name))


def _compute_dimension_score(
    assessment: dict | None, has_assessment: bool,
) -> tuple[float, float, float]:
    """Compute (score, pass_rate, assessment_score) for a dimension."""
    assessment_score = (
        max(0.0, min(100.0, float(assessment.get("score", 0))))
        if isinstance(assessment, dict)
        else 0.0
    )
    integrity_penalty = (
        assessment.get("integrity_penalty")
        if isinstance(assessment, dict)
        else None
    )
    reset_pending = bool(
        isinstance(assessment, dict)
        and (
            assessment.get("reset_by") == "scan_reset_subjective"
            or assessment.get("source") == "scan_reset_subjective"
            or assessment.get("placeholder") is True
        )
    )
    if reset_pending:
        score = 0.0
        pass_rate = 0.0
    elif integrity_penalty == "target_match_reset":
        score = 0.0
        pass_rate = 0.0
    elif has_assessment:
        score = assessment_score
        pass_rate = score / 100.0
    else:
        score = 0.0
        pass_rate = 0.0
    return score, pass_rate, assessment_score


def _extract_components(assessment: dict) -> tuple[list[str], dict[str, float]]:
    """Extract component names and scores from an assessment dict."""
    components: list[str] = []
    component_scores: dict[str, float] = {}
    raw_components = assessment.get("components")
    if isinstance(raw_components, list):
        components = [
            str(item).strip()
            for item in raw_components
            if isinstance(item, str) and item.strip()
        ]
    raw_component_scores = assessment.get("component_scores")
    if isinstance(raw_component_scores, dict):
        for key, value in raw_component_scores.items():
            if not isinstance(key, str) or not key.strip():
                continue
            if not is_numeric(value):
                continue
            component_scores[key.strip()] = round(
                max(0.0, min(100.0, float(value))),
                1,
            )
    return components, component_scores


def append_subjective_dimensions(
    results: dict,
    issues: dict,
    assessments: dict | None,
    failure_set: frozenset[str],
    allowed_dimensions: set[str] | None = None,
) -> None:
    """Append subjective review dimensions to results dict (mutates results).

    Subjective scoring is evidence-first: open review issues for a dimension
    determine pass-rate, while imported assessment scores are retained as
    metadata for transparency.
    """
    raw_defaults = DIMENSIONS
    allowed = (
        {_normalize_dimension_key(name) for name in allowed_dimensions}
        if allowed_dimensions is not None
        else None
    )

    default_dimensions = []
    for raw_dim in raw_defaults:
        dim = _normalize_dimension_key(raw_dim)
        if not dim:
            continue
        if allowed is not None and dim not in allowed:
            continue
        default_dimensions.append(dim)

    assessed: dict[str, dict] = {}
    for raw_dim, payload in (assessments or {}).items():
        dim = _normalize_dimension_key(raw_dim)
        if not dim:
            continue
        # Real assessments (from review imports) always count regardless of
        # allowed_dimensions — they were deliberately imported and should not
        # be silently discarded.  However, system-generated placeholders
        # (scan_reset_subjective) are not real assessments and should respect
        # the allowed_dimensions scope like defaults.
        is_placeholder = isinstance(payload, dict) and (
            payload.get("placeholder") is True
            or payload.get("source") == "scan_reset_subjective"
            or payload.get("reset_by") == "scan_reset_subjective"
        )
        if is_placeholder and allowed is not None and dim not in allowed:
            continue
        assessed[dim] = payload
    existing_lower = {k.lower() for k in results}
    lang_name = _primary_lang_from_issues(issues)

    all_dims = list(default_dimensions)
    for dim_name in assessed:
        if dim_name not in default_dimensions:
            all_dims.append(dim_name)

    for dim_name in all_dims:
        is_default = dim_name in default_dimensions
        assessment = assessed.get(dim_name)
        has_assessment = isinstance(assessment, dict)
        if not is_default and not assessment:
            continue

        display = _dimension_display_name(dim_name, lang_name=lang_name)
        if display.lower() in existing_lower:
            display = f"{display} (subjective)"

        # Count open review/concern issues for display (work queue), but
        # these do NOT drive the dimension score — only assessment scores do.
        issue_count = sum(
            1
            for issue in issues.values()
            if issue.get("detector") in ("review", "concerns")
            and issue.get("status") in failure_set
            and _normalize_dimension_key(
                issue.get("detail", {}).get("dimension")
            )
            == dim_name
        )

        score, pass_rate, assessment_score = _compute_dimension_score(
            assessment, has_assessment,
        )
        reset_pending = bool(
            isinstance(assessment, dict)
            and (
                assessment.get("reset_by") == "scan_reset_subjective"
                or assessment.get("source") == "scan_reset_subjective"
                or assessment.get("placeholder") is True
            )
        )
        components: list[str] = []
        component_scores: dict[str, float] = {}
        if isinstance(assessment, dict):
            components, component_scores = _extract_components(assessment)

        results[display] = {
            "score": round(float(score), 1),
            "tier": 4,
            "checks": SUBJECTIVE_CHECKS,
            "failing": issue_count,
            "detectors": {
                "subjective_assessment": {
                    "potential": SUBJECTIVE_CHECKS,
                    "pass_rate": round(pass_rate, 4),
                    "failing": issue_count,
                    "weighted_failures": round(SUBJECTIVE_CHECKS * (1 - pass_rate), 4),
                    "assessment_score": round(assessment_score, 1),
                    "placeholder": reset_pending or not has_assessment,
                    "dimension_key": dim_name,
                    "configured_weight": round(
                        _dimension_weight(dim_name, lang_name=lang_name), 6
                    ),
                    "components": components,
                    **(
                        {"component_scores": component_scores}
                        if component_scores
                        else {}
                    ),
                }
            },
        }


__all__ = [
    "DISPLAY_NAMES",
    "append_subjective_dimensions",
]
