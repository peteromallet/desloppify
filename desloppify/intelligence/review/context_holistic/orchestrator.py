"""Holistic codebase-wide context gathering for cross-cutting review."""

from __future__ import annotations

from pathlib import Path

from desloppify.core.discovery_api import (
    disable_file_cache,
    enable_file_cache,
    is_file_cache_enabled,
    rel,
)
from desloppify.intelligence.review._context.structure import (
    compute_structure_context,
)
from desloppify.intelligence.review.context_signals.ai import gather_ai_debt_signals
from desloppify.intelligence.review.context_signals.auth import gather_auth_context
from desloppify.intelligence.review.context_signals.migration import (
    gather_migration_signals,
)

from .budget import _abstractions_context, _codebase_stats
from .mechanical import gather_mechanical_evidence
from .readers import _read_file_contents
from .selection import (
    _api_surface_context,
    _architecture_context,
    _coupling_context,
    _dependencies_context,
    _error_strategy_context,
    _naming_conventions_context,
    _sibling_behavior_context,
    _testing_context,
    select_holistic_files,
)
from .types import HolisticContext


def build_holistic_context(
    path: Path,
    lang: object,
    state: dict,
    files: list[str] | None = None,
) -> dict[str, object]:
    """Gather codebase-wide data for holistic review."""
    return build_holistic_context_model(path, lang, state, files=files).to_dict()


def build_holistic_context_model(
    path: Path,
    lang,
    state: dict,
    files: list[str] | None = None,
) -> HolisticContext:
    """Gather holistic context and return a typed context contract."""
    selected_files = select_holistic_files(path, lang, files)

    already_cached = is_file_cache_enabled()
    if not already_cached:
        enable_file_cache()
    try:
        return _build_holistic_context_inner(path, selected_files, lang, state)
    finally:
        if not already_cached:
            disable_file_cache()


def _build_holistic_context_inner(
    path: Path, files: list[str], lang, state: dict
) -> HolisticContext:
    """Inner holistic context builder (runs with file cache enabled)."""
    file_contents = _read_file_contents(files)
    allowed_rel_files = {
        rel(filepath)
        for filepath in files
        if isinstance(filepath, str) and filepath
    }

    context = HolisticContext(
        architecture=_architecture_context(lang, file_contents),
        coupling=_coupling_context(file_contents),
        conventions={
            "naming_by_directory": _naming_conventions_context(file_contents),
            "sibling_behavior": _sibling_behavior_context(file_contents, base_path=path),
        },
        errors={
            "strategy_by_directory": _error_strategy_context(file_contents),
        },
        abstractions=_abstractions_context(file_contents),
        dependencies=_dependencies_context(state, allowed_files=allowed_rel_files),
        testing=_testing_context(
            lang,
            state,
            file_contents,
            allowed_files=allowed_rel_files,
        ),
        api_surface=_api_surface_context(lang, file_contents),
        structure=compute_structure_context(file_contents, lang),
    )

    auth_ctx = gather_auth_context(file_contents, rel_fn=rel)
    if auth_ctx:
        context.authorization = auth_ctx

    ai_debt = gather_ai_debt_signals(file_contents, rel_fn=rel)
    if ai_debt.get("file_signals"):
        context.ai_debt_signals = ai_debt

    migration = gather_migration_signals(file_contents, lang, rel_fn=rel)
    if migration:
        context.migration_signals = migration

    context.codebase_stats = _codebase_stats(file_contents)

    # Enrich with aggregated mechanical detector evidence.
    evidence = gather_mechanical_evidence(state, allowed_files=allowed_rel_files)
    if evidence:
        context.scan_evidence = evidence
        _enrich_sections_from_evidence(context, evidence)

    context.normalize_sections(strict=True)
    return context


def _enrich_sections_from_evidence(
    context: HolisticContext, evidence: dict
) -> None:
    """Merge mechanical evidence into existing holistic context sections."""
    if "complexity_hotspots" in evidence:
        context.abstractions["complexity_hotspots"] = evidence["complexity_hotspots"]
    if "error_hotspots" in evidence:
        context.errors["exception_hotspots"] = evidence["error_hotspots"]
    if "mutable_globals" in evidence:
        context.errors["mutable_globals"] = evidence["mutable_globals"]
    if "boundary_violations" in evidence:
        context.coupling["boundary_violations"] = evidence["boundary_violations"]
    if "deferred_import_density" in evidence:
        context.dependencies["deferred_import_density"] = evidence["deferred_import_density"]
    if "duplicate_clusters" in evidence:
        context.conventions["duplicate_clusters"] = evidence["duplicate_clusters"]
    if "naming_drift" in evidence:
        context.conventions["naming_drift"] = evidence["naming_drift"]
    if "flat_dir_findings" in evidence:
        context.structure["flat_dir_findings"] = evidence["flat_dir_findings"]
