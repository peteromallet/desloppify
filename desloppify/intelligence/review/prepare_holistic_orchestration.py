"""Orchestration helpers for holistic review payload preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.intelligence.review._context.models import HolisticContext
from desloppify.intelligence.review._prepare.helpers import HOLISTIC_WORKFLOW

from .prepare_holistic_batches import HolisticBatchAssemblyDependencies
from .prepare_holistic_payload_parts import (
    _attach_issue_history_context,
    _build_selected_prompts,
)
from .prepare_holistic_scope import (
    collect_allowed_review_files,
    file_in_allowed_scope,
)


def _resolve_review_files(
    path: Path,
    lang: object,
    options: object,
) -> tuple[list[str], set[str]]:
    """Resolve scoped review files and the allowed-review-file set."""
    discovered_files = (
        options.files
        if options.files is not None
        else (lang.file_finder(path) if lang.file_finder else [])
    )
    allowed = collect_allowed_review_files(discovered_files, lang, base_path=path)
    scoped_files = [
        filepath
        for filepath in discovered_files
        if file_in_allowed_scope(filepath, allowed)
    ]
    return scoped_files, allowed


def _build_review_contexts(
    path: Path,
    lang: object,
    state: dict,
    review_files: list[str],
    *,
    is_file_cache_enabled_fn,
    enable_file_cache_fn,
    disable_file_cache_fn,
    build_holistic_context_fn,
    build_review_context_fn,
) -> tuple[HolisticContext, object]:
    """Build holistic and review contexts, managing the file cache lifecycle."""
    already_cached = is_file_cache_enabled_fn()
    if not already_cached:
        enable_file_cache_fn()
    try:
        context = HolisticContext.from_raw(
            build_holistic_context_fn(path, lang, state, files=review_files)
        )
        review_ctx = build_review_context_fn(path, lang, state, files=review_files)
    finally:
        if not already_cached:
            disable_file_cache_fn()
    return context, review_ctx


@dataclass
class _DimensionContext:
    """Resolved dimension configuration for holistic review."""

    dims: list[str]
    holistic_prompts: dict[str, Any]
    per_file_prompts: dict[str, Any]
    system_prompt: str
    lang_guide: str
    invalid_requested: list[str]
    invalid_default: list[str]


@dataclass(frozen=True)
class HolisticPrepareDependencies:
    """Injected collaborators used by holistic payload orchestration."""

    is_file_cache_enabled_fn: object
    enable_file_cache_fn: object
    disable_file_cache_fn: object
    build_holistic_context_fn: object
    build_review_context_fn: object
    load_dimensions_for_lang_fn: object
    resolve_dimensions_fn: object
    get_lang_guidance_fn: object
    assemble_holistic_batches_fn: object
    holistic_batch_deps: HolisticBatchAssemblyDependencies
    serialize_context_fn: object


def _resolve_dimension_context(
    lang_name: str,
    options: object,
    *,
    load_dimensions_for_lang_fn,
    resolve_dimensions_fn,
    get_lang_guidance_fn,
) -> _DimensionContext:
    """Load, resolve, and validate dimensions for the review."""
    default_dims, holistic_prompts, system_prompt = load_dimensions_for_lang_fn(lang_name)
    _, per_file_prompts, _ = load_dimensions_for_lang_fn(lang_name)
    dims = resolve_dimensions_fn(
        cli_dimensions=options.dimensions,
        default_dimensions=default_dims,
    )
    lang_guide = get_lang_guidance_fn(lang_name)
    valid_dims = set(holistic_prompts) | set(per_file_prompts)
    invalid_requested = [
        dim for dim in (options.dimensions or []) if dim not in valid_dims
    ]
    invalid_default = [dim for dim in default_dims if dim not in valid_dims]
    return _DimensionContext(
        dims=dims,
        holistic_prompts=holistic_prompts,
        per_file_prompts=per_file_prompts,
        system_prompt=system_prompt,
        lang_guide=lang_guide,
        invalid_requested=invalid_requested,
        invalid_default=invalid_default,
    )


def prepare_holistic_review_payload(
    path: Path,
    lang: object,
    state: dict,
    options,
    *,
    deps: HolisticPrepareDependencies,
) -> dict[str, object]:
    """Prepare holistic review payload with injected dependencies for patchability."""
    scoped_files, allowed_review_files = _resolve_review_files(path, lang, options)

    context, review_ctx = _build_review_contexts(
        path,
        lang,
        state,
        scoped_files,
        is_file_cache_enabled_fn=deps.is_file_cache_enabled_fn,
        enable_file_cache_fn=deps.enable_file_cache_fn,
        disable_file_cache_fn=deps.disable_file_cache_fn,
        build_holistic_context_fn=deps.build_holistic_context_fn,
        build_review_context_fn=deps.build_review_context_fn,
    )

    dim_ctx = _resolve_dimension_context(
        lang.name,
        options,
        load_dimensions_for_lang_fn=deps.load_dimensions_for_lang_fn,
        resolve_dimensions_fn=deps.resolve_dimensions_fn,
        get_lang_guidance_fn=deps.get_lang_guidance_fn,
    )

    include_full_sweep = bool(options.include_full_sweep)
    if options.dimensions:
        include_full_sweep = False
    batches = deps.assemble_holistic_batches_fn(
        context,
        lang=lang,
        repo_root=path,
        state=state,
        dims=dim_ctx.dims,
        all_files=scoped_files,
        allowed_review_files=allowed_review_files,
        include_full_sweep=include_full_sweep,
        max_files_per_batch=options.max_files_per_batch,
        deps=deps.holistic_batch_deps,
    )

    selected_prompts = _build_selected_prompts(
        dim_ctx.dims,
        dim_ctx.holistic_prompts,
        dim_ctx.per_file_prompts,
    )

    payload: dict[str, Any] = {
        "command": "review",
        "mode": "holistic",
        "language": lang.name,
        "dimensions": dim_ctx.dims,
        "dimension_prompts": selected_prompts,
        "lang_guidance": dim_ctx.lang_guide,
        "holistic_context": context.to_dict(),
        "review_context": deps.serialize_context_fn(review_ctx),
        "system_prompt": dim_ctx.system_prompt,
        "total_files": context.codebase_stats.get("total_files", 0),
        "workflow": HOLISTIC_WORKFLOW,
        "invalid_dimensions": {
            "requested": dim_ctx.invalid_requested,
            "default": dim_ctx.invalid_default,
        },
    }

    batches = _attach_issue_history_context(
        payload,
        batches,
        state,
        options,
        allowed_review_files,
    )

    # Attach accumulated dimension contexts to each batch
    dim_contexts = state.get("dimension_contexts", {})
    if isinstance(dim_contexts, dict) and dim_contexts:
        payload["dimension_contexts"] = dim_contexts
        for batch_item in batches:
            if not isinstance(batch_item, dict):
                continue
            batch_dims = batch_item.get("dimensions", [])
            if isinstance(batch_dims, list):
                compact_contexts = _compact_batch_dimension_contexts(
                    dimensions=batch_dims,
                    all_contexts=dim_contexts,
                )
                if compact_contexts:
                    batch_item["dimension_contexts"] = compact_contexts

    payload["investigation_batches"] = batches
    return payload


def _compact_batch_dimension_contexts(
    *,
    dimensions: list[str],
    all_contexts: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, object]]]]:
    """Attach a prompt-facing slice of dimension contexts for each batch.

    Batch prompts only need insight headers and settled/positive flags. Keeping
    this payload compact avoids duplicating full insight descriptions across all
    batches while preserving packet-level full context in payload["dimension_contexts"].
    """
    compact: dict[str, dict[str, list[dict[str, object]]]] = {}
    for dimension in dimensions:
        raw_context = all_contexts.get(dimension)
        if not isinstance(raw_context, dict):
            continue
        raw_insights = raw_context.get("insights")
        if not isinstance(raw_insights, list):
            continue
        insights: list[dict[str, object]] = []
        for item in raw_insights:
            if not isinstance(item, dict):
                continue
            header = str(item.get("header", "")).strip()
            if not header:
                continue
            insight: dict[str, object] = {"header": header}
            if bool(item.get("settled", False)):
                insight["settled"] = True
            if bool(item.get("positive", False)):
                insight["positive"] = True
            insights.append(insight)
        if insights:
            compact[dimension] = {"insights": insights}
    return compact


__all__ = ["HolisticPrepareDependencies", "prepare_holistic_review_payload"]
