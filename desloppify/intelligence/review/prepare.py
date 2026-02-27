"""Review preparation: prepare_review, prepare_holistic_review, batches."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.core.discovery_api import (
    disable_file_cache,
    enable_file_cache,
    is_file_cache_enabled,
    read_file_text,
    rel,
)
from desloppify.intelligence.review._context.models import HolisticContext
from desloppify.intelligence.review._prepare.helpers import (
    HOLISTIC_WORKFLOW,
    append_full_sweep_batch,
)
from desloppify.intelligence.review._prepare.issue_history import (
    ReviewHistoryOptions,
    build_batch_issue_focus,
    build_issue_history_context,
)
from desloppify.intelligence.review.context import (
    abs_path,
    build_review_context,
    dep_graph_lookup,
    importer_count,
    serialize_context,
)
from desloppify.intelligence.review.context_holistic import build_holistic_context
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.intelligence.review.dimensions.lang import get_lang_guidance
from desloppify.intelligence.review.dimensions.selection import resolve_dimensions
from desloppify.intelligence.review.prepare_batches import (
    batch_concerns as _batch_concerns,
)
from desloppify.intelligence.review.prepare_batches import (
    build_investigation_batches as _build_investigation_batches,
)
from desloppify.intelligence.review.prepare_batches import (
    filter_batches_to_dimensions as _filter_batches_to_dimensions,
)
from desloppify.intelligence.review.selection import (
    ReviewSelectionOptions,
    count_fresh,
    count_stale,
    get_file_findings,
    select_files_for_review,
)

logger = logging.getLogger(__name__)

_NON_PRODUCTION_ZONES = frozenset({"test", "config", "generated", "vendor"})


@dataclass
class ReviewPrepareOptions:
    """Configuration bundle for per-file review preparation."""

    max_files: int | None = None
    max_age_days: int = 30
    force_refresh: bool = True
    dimensions: list[str] | None = None
    config_dimensions: list[str] | None = None
    files: list[str] | None = None


@dataclass
class HolisticReviewPrepareOptions:
    """Configuration bundle for holistic review preparation."""

    dimensions: list[str] | None = None
    files: list[str] | None = None
    include_full_sweep: bool = True
    max_files_per_batch: int | None = None
    include_issue_history: bool = False
    issue_history_max_issues: int = 30
    issue_history_max_batch_items: int = 20

def _rel_list(s) -> list[str]:
    """Normalize a set or list of paths to sorted relative paths (max 10)."""
    if isinstance(s, set):
        return sorted(rel(x) for x in s)[:10]
    return [rel(x) for x in list(s)[:10]]


def _normalize_max_files(value: Any) -> int | None:
    """Normalize max_files input: None/<=0 means unlimited."""
    if value in (None, ""):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _collect_allowed_review_files(
    files: list[str],
    lang: object,
    *,
    base_path: Path | None = None,
) -> set[str]:
    """Return relative production-file paths allowed for holistic review batches."""
    allowed: set[str] = set()
    zone_map = getattr(lang, "zone_map", None)
    resolved_base = base_path.resolve() if isinstance(base_path, Path) else None
    for filepath in files:
        if not isinstance(filepath, str):
            continue
        normalized = filepath.strip().replace("\\", "/")
        if not normalized:
            continue
        if zone_map is not None:
            try:
                zone = zone_map.get(filepath)
                zone_value = getattr(zone, "value", str(zone))
            except (AttributeError, KeyError, TypeError, ValueError):
                zone_value = "production"
            if zone_value in _NON_PRODUCTION_ZONES:
                continue
        allowed.add(normalized)
        allowed.add(rel(filepath))
        if resolved_base is not None:
            try:
                allowed.add(Path(filepath).resolve().relative_to(resolved_base).as_posix())
            except ValueError:
                pass
    return allowed


def _file_in_allowed_scope(filepath: object, allowed_files: set[str]) -> bool:
    """True when *filepath* resolves to a currently in-scope review file."""
    if not isinstance(filepath, str):
        return False
    normalized = filepath.strip().replace("\\", "/")
    if not normalized:
        return False
    if normalized in allowed_files:
        return True
    return rel(filepath) in allowed_files


def _filter_issue_focus_to_scope(
    issue_focus: object,
    allowed_files: set[str],
) -> dict[str, object] | None:
    """Drop out-of-scope related_files from historical issue focus payload."""
    if not isinstance(issue_focus, dict):
        return None
    issues_raw = issue_focus.get("issues", [])
    issues: list[dict[str, object]] = []
    if isinstance(issues_raw, list):
        for raw_issue in issues_raw:
            if not isinstance(raw_issue, dict):
                continue
            issue = dict(raw_issue)
            related_raw = issue.get("related_files", [])
            if isinstance(related_raw, list):
                issue["related_files"] = [
                    path
                    for path in related_raw
                    if _file_in_allowed_scope(path, allowed_files)
                ]
            issues.append(issue)
    scoped = dict(issue_focus)
    scoped["issues"] = issues
    scoped["selected_count"] = len(issues)
    return scoped


def _filter_batches_to_file_scope(
    batches: list[dict[str, Any]],
    *,
    allowed_files: set[str],
) -> list[dict[str, Any]]:
    """Strip out-of-scope files/signals from review batches."""
    if not allowed_files:
        return []

    scoped_batches: list[dict[str, Any]] = []
    for raw_batch in batches:
        if not isinstance(raw_batch, dict):
            continue
        batch = dict(raw_batch)
        files_to_read = batch.get("files_to_read", [])
        if isinstance(files_to_read, list):
            batch["files_to_read"] = [
                filepath
                for filepath in files_to_read
                if _file_in_allowed_scope(filepath, allowed_files)
            ]
        else:
            batch["files_to_read"] = []

        concern_signals = batch.get("concern_signals", [])
        if isinstance(concern_signals, list):
            batch["concern_signals"] = [
                signal
                for signal in concern_signals
                if isinstance(signal, dict)
                and _file_in_allowed_scope(signal.get("file", ""), allowed_files)
            ]
            if "concern_signal_count" in batch:
                batch["concern_signal_count"] = len(batch["concern_signals"])

        issue_focus = _filter_issue_focus_to_scope(
            batch.get("historical_issue_focus"),
            allowed_files,
        )
        if issue_focus is not None:
            batch["historical_issue_focus"] = issue_focus

        has_seed_files = bool(batch["files_to_read"])
        has_signals = bool(batch.get("concern_signals"))
        if has_seed_files or has_signals:
            scoped_batches.append(batch)
    return scoped_batches


def prepare_review(
    path: Path,
    lang: object,
    state: dict,
    options: ReviewPrepareOptions | None = None,
) -> dict[str, object]:
    """Prepare review data for agent consumption. Returns structured dict.

    If *files* is provided, skip file_finder (avoids redundant filesystem walks
    when the caller already has the file list, e.g. from _setup_lang).
    """
    resolved_options = options or ReviewPrepareOptions()
    resolved_options.max_files = _normalize_max_files(resolved_options.max_files)
    all_files = (
        resolved_options.files
        if resolved_options.files is not None
        else (lang.file_finder(path) if lang.file_finder else [])
    )

    # Enable file cache for entire prepare operation — context building,
    # file selection, and content extraction all read the same files.
    already_cached = is_file_cache_enabled()
    if not already_cached:
        enable_file_cache()
    try:
        context = build_review_context(path, lang, state, files=all_files)
        selected = select_files_for_review(
            lang,
            path,
            state,
            options=ReviewSelectionOptions(
                max_files=resolved_options.max_files,
                max_age_days=resolved_options.max_age_days,
                force_refresh=resolved_options.force_refresh,
                files=all_files,
            ),
        )
        file_requests = _build_file_requests(selected, lang, state)
    finally:
        if not already_cached:
            disable_file_cache()

    default_dims, dimension_prompts, system_prompt = load_dimensions_for_lang(lang.name)
    dims = resolve_dimensions(
        cli_dimensions=resolved_options.dimensions,
        config_dimensions=resolved_options.config_dimensions,
        default_dimensions=default_dims,
    )
    lang_guide = get_lang_guidance(lang.name)
    valid_dims = set(dimension_prompts)
    invalid_requested = [
        dim for dim in (resolved_options.dimensions or []) if dim not in valid_dims
    ]
    invalid_config = [
        dim
        for dim in (resolved_options.config_dimensions or [])
        if dim not in valid_dims
    ]

    return {
        "command": "review",
        "language": lang.name,
        "dimensions": dims,
        "dimension_prompts": {
            d: dimension_prompts[d] for d in dims if d in dimension_prompts
        },
        "lang_guidance": lang_guide,
        "context": serialize_context(context),
        "system_prompt": system_prompt,
        "files": file_requests,
        "total_candidates": len(file_requests),
        "cache_status": {
            "fresh": count_fresh(state, resolved_options.max_age_days),
            "stale": count_stale(state, resolved_options.max_age_days),
            "new": len(file_requests),
        },
        "invalid_dimensions": {
            "requested": invalid_requested,
            "config": invalid_config,
        },
    }


def _build_file_requests(files: list[str], lang, state: dict) -> list[dict]:
    """Build per-file review request dicts."""
    file_requests = []
    for filepath in files:
        content = read_file_text(abs_path(filepath))
        if content is None:
            continue

        rpath = rel(filepath)
        zone = "production"
        if lang.zone_map is not None:
            zone = lang.zone_map.get(filepath).value

        neighbors: dict
        if lang.dep_graph:
            entry = dep_graph_lookup(lang.dep_graph, filepath)
            imports_raw = entry.get("imports", set())
            importers_raw = entry.get("importers", set())
            importer_count_value = importer_count(entry)
            neighbors = {
                "imports": _rel_list(imports_raw),
                "importers": _rel_list(importers_raw),
                "importer_count": importer_count_value,
            }
        else:
            neighbors = {}

        file_requests.append(
            {
                "file": rpath,
                "content": content,
                "zone": zone,
                "loc": len(content.splitlines()),
                "neighbors": neighbors,
                "existing_findings": get_file_findings(state, filepath),
            }
        )
    return file_requests


def prepare_holistic_review(
    path: Path,
    lang: object,
    state: dict,
    options: HolisticReviewPrepareOptions | None = None,
) -> dict[str, object]:
    """Prepare holistic review data for agent consumption. Returns structured dict."""
    resolved_options = options or HolisticReviewPrepareOptions()
    all_files = (
        resolved_options.files
        if resolved_options.files is not None
        else (lang.file_finder(path) if lang.file_finder else [])
    )
    allowed_review_files = _collect_allowed_review_files(
        all_files,
        lang,
        base_path=path,
    )

    already_cached = is_file_cache_enabled()
    if not already_cached:
        enable_file_cache()
    try:
        context = HolisticContext.from_raw(
            build_holistic_context(path, lang, state, files=all_files)
        )
        # Also include per-file review context for reference
        review_ctx = build_review_context(path, lang, state, files=all_files)
    finally:
        if not already_cached:
            disable_file_cache()

    default_dims, holistic_prompts, system_prompt = load_dimensions_for_lang(lang.name)
    _, per_file_prompts, _ = load_dimensions_for_lang(lang.name)
    dims = resolve_dimensions(
        cli_dimensions=resolved_options.dimensions,
        default_dimensions=default_dims,
    )
    lang_guide = get_lang_guidance(lang.name)
    valid_dims = set(holistic_prompts) | set(per_file_prompts)
    invalid_requested = [
        dim for dim in (resolved_options.dimensions or []) if dim not in valid_dims
    ]
    invalid_default = [dim for dim in default_dims if dim not in valid_dims]
    batches = _build_investigation_batches(
        context,
        lang,
        repo_root=path,
        max_files_per_batch=resolved_options.max_files_per_batch,
    )

    # Append design-coherence batch from mechanical concern signals.
    try:
        from desloppify.engine.concerns import generate_concerns

        concerns = generate_concerns(state, lang_name=lang.name)
        concerns = [
            concern
            for concern in concerns
            if _file_in_allowed_scope(getattr(concern, "file", ""), allowed_review_files)
        ]
        concerns_batch = _batch_concerns(
            concerns,
            max_files=resolved_options.max_files_per_batch,
            active_dimensions=dims,
        )
        if concerns_batch:
            batches.append(concerns_batch)
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("Concern generation failed (best-effort): %s", exc)

    batches = _filter_batches_to_dimensions(
        batches,
        dims,
        fallback_max_files=resolved_options.max_files_per_batch,
    )
    include_full_sweep = bool(resolved_options.include_full_sweep)
    # Explicitly scoped dimension runs should stay scoped by default.
    if resolved_options.dimensions:
        include_full_sweep = False
    if include_full_sweep:
        append_full_sweep_batch(
            batches=batches,
            dims=dims,
            all_files=all_files,
            lang=lang,
            max_files=resolved_options.max_files_per_batch,
        )
    batches = _filter_batches_to_file_scope(
        batches,
        allowed_files=allowed_review_files,
    )

    # Holistic mode can receive per-file-oriented dimensions via CLI suggestions.
    # Attach whichever prompt definition exists so reviewers always get guidance.
    selected_prompts: dict[str, dict[str, object]] = {}
    for dim in dims:
        prompt = holistic_prompts.get(dim)
        if prompt is None:
            prompt = per_file_prompts.get(dim)
        if prompt is None:
            continue
        selected_prompts[dim] = prompt

    payload = {
        "command": "review",
        "mode": "holistic",
        "language": lang.name,
        "dimensions": dims,
        "dimension_prompts": selected_prompts,
        "lang_guidance": lang_guide,
        "holistic_context": context.to_dict(),
        "review_context": serialize_context(review_ctx),
        "system_prompt": system_prompt,
        "total_files": context.codebase_stats.get("total_files", 0),
        "workflow": HOLISTIC_WORKFLOW,
        "investigation_batches": batches,
        "invalid_dimensions": {
            "requested": invalid_requested,
            "default": invalid_default,
        },
    }
    if resolved_options.include_issue_history:
        history_payload = build_issue_history_context(
            state,
            options=ReviewHistoryOptions(
                max_issues=resolved_options.issue_history_max_issues,
            ),
        )
        payload["historical_review_issues"] = history_payload
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            batch_dims = batch.get("dimensions", [])
            batch["historical_issue_focus"] = build_batch_issue_focus(
                history_payload,
                dimensions=batch_dims,
                max_items=resolved_options.issue_history_max_batch_items,
            )
        batches = _filter_batches_to_file_scope(
            batches,
            allowed_files=allowed_review_files,
        )
        payload["investigation_batches"] = batches
    return payload
