"""Holistic codebase-wide context gathering for cross-cutting review."""

from __future__ import annotations

from pathlib import Path

from desloppify.intelligence.review._context.structure import (
    compute_structure_context,
)
from desloppify.intelligence.review.context_signals.ai import gather_ai_debt_signals
from desloppify.intelligence.review.context_signals.auth import gather_auth_context
from desloppify.intelligence.review.context_signals.migration import (
    gather_migration_signals,
)
from desloppify.file_discovery import (
    disable_file_cache,
    enable_file_cache,
    is_file_cache_enabled,
    rel,
)

from .budget import _abstractions_context, _codebase_stats
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
        dependencies=_dependencies_context(state),
        testing=_testing_context(lang, state, file_contents),
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
    return context
