"""Canonical subjective-dimension catalog shared across layers."""

from __future__ import annotations

DISPLAY_NAMES: dict[str, str] = {
    # Holistic dimensions
    "cross_module_architecture": "Cross-module arch",
    "initialization_coupling": "Init coupling",
    "convention_outlier": "Convention drift",
    "error_consistency": "Error consistency",
    "abstraction_fitness": "Abstraction fit",
    "dependency_health": "Dep health",
    "test_strategy": "Test strategy",
    "api_surface_coherence": "API coherence",
    "authorization_consistency": "Auth consistency",
    "ai_generated_debt": "AI generated debt",
    "incomplete_migration": "Stale migration",
    "package_organization": "Structure nav",
    "high_level_elegance": "High elegance",
    "mid_level_elegance": "Mid elegance",
    "low_level_elegance": "Low elegance",
    # Design coherence (concerns bridge)
    "design_coherence": "Design coherence",
    # Per-file review dimensions
    "naming_quality": "Naming quality",
    "logic_clarity": "Logic clarity",
    "type_safety": "Type safety",
    "contract_coherence": "Contracts",
}

_SUBJECTIVE_WEIGHTS_BY_DISPLAY: dict[str, float] = {
    "high elegance": 22.0,
    "mid elegance": 22.0,
    "low elegance": 12.0,
    "contracts": 12.0,
    "type safety": 12.0,
    "abstraction fit": 8.0,
    "logic clarity": 6.0,
    "structure nav": 5.0,
    "error consistency": 3.0,
    "naming quality": 2.0,
    "ai generated debt": 1.0,
    "design coherence": 10.0,
}

RESET_ON_SCAN_DIMENSIONS: frozenset[str] = frozenset(
    {
        "naming_quality",
        "error_consistency",
        "abstraction_fitness",
        "logic_clarity",
        "ai_generated_debt",
        "type_safety",
        "contract_coherence",
        "package_organization",
        "high_level_elegance",
        "mid_level_elegance",
        "low_level_elegance",
    }
)


def _normalize_display_name_for_weight_lookup(display_name: str) -> str:
    return " ".join(display_name.strip().lower().split())


def build_weight_by_dimension() -> dict[str, float]:
    out: dict[str, float] = {}
    for dimension_key, display_name in DISPLAY_NAMES.items():
        weight = _SUBJECTIVE_WEIGHTS_BY_DISPLAY.get(
            _normalize_display_name_for_weight_lookup(display_name)
        )
        if weight is not None:
            out[dimension_key] = weight
    return out


WEIGHT_BY_DIMENSION: dict[str, float] = build_weight_by_dimension()

__all__ = [
    "DISPLAY_NAMES",
    "RESET_ON_SCAN_DIMENSIONS",
    "WEIGHT_BY_DIMENSION",
    "build_weight_by_dimension",
]
