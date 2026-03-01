"""Scope and queue helpers for show command selection."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify import scoring as scoring_mod
from desloppify import state as state_mod
from desloppify.core import registry as registry_mod
from desloppify.engine.work_queue import (
    QueueBuildOptions,
    build_work_queue,
)
from desloppify.core.output_api import colorize


@dataclass(frozen=True)
class ResolvedEntity:
    """Classifies what the user's show pattern refers to."""

    kind: str  # "dimension", "special_view", "file_or_pattern"
    pattern: str  # Original user pattern
    display_name: str  # Human-readable label
    detectors: tuple[str, ...] = ()  # Detector names (for dimension kind)
    is_subjective: bool = False  # Whether this is a subjective dimension


def _resolve_special_view(pattern: str, lowered: str) -> ResolvedEntity | None:
    if lowered not in ("concerns", "subjective", "subjective_review"):
        return None
    return ResolvedEntity(
        kind="special_view",
        pattern=pattern,
        display_name=pattern,
    )


def _resolve_mechanical_dimension(pattern: str, lowered: str) -> ResolvedEntity | None:
    lookup = _build_dimension_lookup()
    detectors = lookup.get(lowered) or lookup.get(pattern.lower())
    if not detectors:
        return None
    dim_display = pattern
    for dim in scoring_mod.DIMENSIONS:
        dim_lowered = dim.name.lower().replace(" ", "_")
        if dim.name.lower() == lowered or dim_lowered == lowered:
            dim_display = dim.name
            break
    return ResolvedEntity(
        kind="dimension",
        pattern=pattern,
        display_name=dim_display,
        detectors=tuple(detectors),
        is_subjective=False,
    )


def _resolve_subjective_dimension(
    pattern: str,
    lowered: str,
    state: dict,
) -> ResolvedEntity | None:
    display_name = scoring_mod.DISPLAY_NAMES.get(lowered)
    if not display_name:
        for key in state.get("dimension_scores") or {}:
            if key.lower().replace(" ", "_") == lowered:
                display_name = key
                break
    if not display_name:
        return None
    dim_data, display_name = _lookup_dimension_score(state, display_name)
    is_subj = "subjective_assessment" in (
        dim_data.get("detectors", {}) if isinstance(dim_data, dict) else {}
    )
    return ResolvedEntity(
        kind="dimension",
        pattern=pattern,
        display_name=display_name,
        detectors=(),
        is_subjective=is_subj,
    )


def resolve_entity(pattern: str, state: dict) -> ResolvedEntity:
    """Classify a user pattern as a dimension, special view, or passthrough.

    Resolution priority:
    1. Special views: "concerns", "subjective", "subjective_review"
    2. Mechanical dimension name (from DIMENSIONS)
    3. Subjective dimension name (from DISPLAY_NAMES / dimension_scores)
    4. Everything else: file_or_pattern passthrough
    """
    lowered = pattern.strip().lower().replace(" ", "_")

    # 1. Special views
    special_view = _resolve_special_view(pattern, lowered)
    if special_view is not None:
        return special_view

    # 2. Mechanical dimension (via DIMENSIONS list)
    mechanical = _resolve_mechanical_dimension(pattern, lowered)
    if mechanical is not None:
        return mechanical

    # 3. Subjective dimension (via DISPLAY_NAMES or dimension_scores)
    subjective = _resolve_subjective_dimension(pattern, lowered, state)
    if subjective is not None:
        return subjective

    # 4. Everything else
    return ResolvedEntity(
        kind="file_or_pattern",
        pattern=pattern,
        display_name=pattern,
    )


def _build_dimension_lookup() -> dict[str, list[str]]:
    """Build a map from dimension name/key (lowered) to detector names."""
    lookup: dict[str, list[str]] = {}
    for dim in scoring_mod.DIMENSIONS:
        detectors = list(dim.detectors) if hasattr(dim, "detectors") else []
        lookup[dim.name.lower()] = detectors
        # Also index by underscore key: "file_health" -> detectors
        key = dim.name.lower().replace(" ", "_")
        if key not in lookup:
            lookup[key] = detectors
    # Also add DISPLAY_NAMES reverse lookup (e.g. "abstraction_fit" -> "Abstraction Fit")
    for key, display in scoring_mod.DISPLAY_NAMES.items():
        normalized_key = key.lower().replace(" ", "_")
        normalized_display = display.lower()
        # Find which dimension this belongs to via get_dimension_for_detector or direct name match
        for dim in scoring_mod.DIMENSIONS:
            dim_lower = dim.name.lower()
            if normalized_display == dim_lower or normalized_key == dim_lower.replace(" ", "_"):
                detectors = list(dim.detectors) if hasattr(dim, "detectors") else []
                if normalized_key not in lookup:
                    lookup[normalized_key] = detectors
                if normalized_display not in lookup:
                    lookup[normalized_display] = detectors
    return lookup


def _lookup_dimension_score(
    state: dict, display_name: str,
) -> tuple[dict, str]:
    """Find dimension_scores entry with case-insensitive fallback.

    Returns (dim_data_dict, resolved_display_name).
    """
    lowered = display_name.lower().replace(" ", "_")
    dim_data = (state.get("dimension_scores") or {}).get(display_name, {})
    if not dim_data:
        for ds_key, ds_val in (state.get("dimension_scores") or {}).items():
            if ds_key.lower().replace(" ", "_") == lowered:
                dim_data = ds_val
                display_name = ds_key
                break
    return dim_data, display_name


def _detector_names_hint() -> str:
    """Return a compact list of detector names for the help message."""
    names = getattr(registry_mod, "DISPLAY_ORDER", [])
    if names:
        return ", ".join(names[:10]) + (", ..." if len(names) > 10 else "")
    return "smells, structural, security, review, ..."


def resolve_show_scope(args) -> tuple[bool, str | None, str, str | None]:
    """Resolve scope/pattern/status for a show invocation."""
    chronic = getattr(args, "chronic", False)
    pattern = args.pattern
    status_filter = "open" if chronic else getattr(args, "status", "open")
    if chronic:
        scope = pattern
        pattern = pattern or "<chronic>"
        return True, pattern, status_filter, scope
    if not pattern:
        print(
            colorize(
                "Pattern required (or use --chronic). Try: desloppify show --help",
                "yellow",
            )
        )
        return False, None, status_filter, ""
    return True, pattern, status_filter, pattern


def load_matches(
    state: dict,
    *,
    scope: str | None,
    status_filter: str,
    chronic: bool,
) -> list[dict]:
    """Load matching findings from the ranked queue."""
    queue = build_work_queue(
        state,
        options=QueueBuildOptions(
            count=None,
            scan_path=state.get("scan_path"),
            scope=scope,
            status=status_filter,
            include_subjective=False,
            chronic=chronic,
            no_tier_fallback=True,
        ),
    )
    return [item for item in queue.get("items", []) if item.get("kind") == "finding"]


def resolve_noise(config: dict, matches: list[dict]):
    """Apply detector/global noise budget to show matches."""
    noise_budget, global_noise_budget, budget_warning = (
        state_mod.resolve_finding_noise_settings(config)
    )
    surfaced_matches, hidden_by_detector = state_mod.apply_finding_noise_budget(
        matches,
        budget=noise_budget,
        global_budget=global_noise_budget,
    )
    return (
        surfaced_matches,
        hidden_by_detector,
        noise_budget,
        global_noise_budget,
        budget_warning,
    )


__all__ = [
    "ResolvedEntity",
    "_detector_names_hint",
    "_lookup_dimension_score",
    "load_matches",
    "resolve_entity",
    "resolve_noise",
    "resolve_show_scope",
]
