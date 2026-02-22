"""Subjective-dimension scoring helpers."""

from __future__ import annotations

import importlib

from desloppify.core._internal.text_utils import is_numeric
from desloppify.engine._scoring.policy.core import SUBJECTIVE_CHECKS

DISPLAY_NAMES: dict[str, str] = {
    # Holistic dimensions
    "cross_module_architecture": "Cross-Module Arch",
    "initialization_coupling": "Init Coupling",
    "convention_outlier": "Convention Drift",
    "error_consistency": "Error Consistency",
    "abstraction_fitness": "Abstraction Fit",
    "dependency_health": "Dep Health",
    "test_strategy": "Test Strategy",
    "api_surface_coherence": "API Coherence",
    "authorization_consistency": "Auth Consistency",
    "ai_generated_debt": "AI Generated Debt",
    "incomplete_migration": "Stale Migration",
    "package_organization": "Structure Nav",
    "high_level_elegance": "High Elegance",
    "mid_level_elegance": "Mid Elegance",
    "low_level_elegance": "Low Elegance",
    # Design coherence (concerns bridge)
    "design_coherence": "Design Coherence",
    # Per-file review dimensions
    "naming_quality": "Naming Quality",
    "logic_clarity": "Logic Clarity",
    "type_safety": "Type Safety",
    "contract_coherence": "Contracts",
}

def _display_fallback(dim_name: str) -> str:
    return dim_name.replace("_", " ").title()


def _normalize_dimension_key(dim_name: object) -> str:
    if not isinstance(dim_name, str):
        return ""
    return "_".join(dim_name.strip().lower().replace("-", "_").split())


def _primary_lang_from_findings(findings: dict) -> str | None:
    counts: dict[str, int] = {}
    for finding in findings.values():
        if not isinstance(finding, dict):
            continue
        raw_lang = finding.get("lang")
        if not isinstance(raw_lang, str) or not raw_lang.strip():
            continue
        key = raw_lang.strip().lower()
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _dimension_display_name(dim_name: str, *, lang_name: str | None) -> str:
    try:
        # deferred: avoid circular import with desloppify.scoring
        # (scoring -> _scoring/results/core -> _scoring/subjective/core -> review -> state -> scoring)
        metadata_mod = importlib.import_module(
            "desloppify.intelligence.review.dimensions.metadata"
        )
        return str(metadata_mod.dimension_display_name(dim_name, lang_name=lang_name))
    except (ImportError, AttributeError, RuntimeError, ValueError, TypeError):
        return DISPLAY_NAMES.get(dim_name, _display_fallback(dim_name))


def _dimension_weight(dim_name: str, *, lang_name: str | None) -> float:
    try:
        # deferred: avoid circular import with desloppify.scoring (see _dimension_display_name)
        metadata_mod = importlib.import_module(
            "desloppify.intelligence.review.dimensions.metadata"
        )
        return float(metadata_mod.dimension_weight(dim_name, lang_name=lang_name))
    except (ImportError, AttributeError, RuntimeError, ValueError, TypeError):
        return 1.0


def append_subjective_dimensions(
    results: dict,
    findings: dict,
    assessments: dict | None,
    failure_set: frozenset[str],
    allowed_dimensions: set[str] | None = None,
) -> None:
    """Append subjective review dimensions to results dict (mutates results).

    Subjective scoring is evidence-first: open review findings for a dimension
    determine pass-rate, while imported assessment scores are retained as
    metadata for transparency.
    """
    # deferred: avoid circular import with desloppify.scoring (see _dimension_display_name)
    review_mod = importlib.import_module("desloppify.intelligence.review")
    raw_defaults = review_mod.DIMENSIONS
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
        if allowed is not None and dim not in allowed:
            continue
        assessed[dim] = payload
    existing_lower = {k.lower() for k in results}
    lang_name = _primary_lang_from_findings(findings)

    all_dims = list(default_dimensions)
    for dim_name in assessed:
        if dim_name not in default_dimensions:
            all_dims.append(dim_name)

    for dim_name in all_dims:
        is_default = dim_name in default_dimensions
        assessment = assessed.get(dim_name)
        if not is_default and not assessment:
            continue

        display = _dimension_display_name(dim_name, lang_name=lang_name)
        if display.lower() in existing_lower:
            display = f"{display} (subjective)"

        # Count open review/concern findings for display (work queue), but
        # these do NOT drive the dimension score — only assessment scores do.
        issue_count = sum(
            1
            for finding in findings.values()
            if finding.get("detector") in ("review", "concerns")
            and finding.get("status") in failure_set
            and _normalize_dimension_key(
                finding.get("detail", {}).get("dimension")
            )
            == dim_name
        )

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
        elif isinstance(assessment, dict):
            # Assessment score drives the dimension score directly.
            # Resolving review findings does NOT change this score —
            # only a fresh review import updates it.
            score = assessment_score
            pass_rate = score / 100.0
        else:
            # No assessment yet — clean default (no evidence = no penalty).
            score = 100.0
            pass_rate = 1.0
        components: list[str] = []
        component_scores: dict[str, float] = {}
        if isinstance(assessment, dict):
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

        results[display] = {
            "score": round(float(score), 1),
            "tier": 4,
            "checks": SUBJECTIVE_CHECKS,
            "issues": issue_count,
            "detectors": {
                "subjective_assessment": {
                    "potential": SUBJECTIVE_CHECKS,
                    "pass_rate": round(pass_rate, 4),
                    "issues": issue_count,
                    "weighted_failures": round(SUBJECTIVE_CHECKS * (1 - pass_rate), 4),
                    "assessment_score": round(assessment_score, 1),
                    "placeholder": reset_pending,
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
