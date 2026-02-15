"""Review preparation: prepare_review, prepare_holistic_review, batches."""

from __future__ import annotations

from pathlib import Path

from .. import utils as _utils_mod
from ..utils import rel, enable_file_cache, disable_file_cache, read_file_text
from .context import (
    build_review_context, _serialize_context,
    _abs, _dep_graph_lookup, _importer_count,
)
from .context_holistic import build_holistic_context
from .selection import (
    select_files_for_review, _get_file_findings, _count_fresh, _count_stale,
)
from .dimensions import (
    DEFAULT_DIMENSIONS, DIMENSION_PROMPTS,
    HOLISTIC_DIMENSIONS, HOLISTIC_DIMENSION_PROMPTS,
    REVIEW_SYSTEM_PROMPT, HOLISTIC_REVIEW_SYSTEM_PROMPT,
    LANG_GUIDANCE,
)


def _rel_list(s) -> list[str]:
    """Normalize a set or list of paths to sorted relative paths (max 10)."""
    if isinstance(s, set):
        return sorted(rel(x) for x in s)[:10]
    return [rel(x) for x in list(s)[:10]]


def prepare_review(path: Path, lang, state: dict, *,
                   max_files: int = 50, max_age_days: int = 30,
                   force_refresh: bool = False,
                   dimensions: list[str] | None = None,
                   config_dimensions: list[str] | None = None,
                   files: list[str] | None = None) -> dict:
    """Prepare review data for agent consumption. Returns structured dict.

    If *files* is provided, skip file_finder (avoids redundant filesystem walks
    when the caller already has the file list, e.g. from _setup_lang).
    """
    all_files = files if files is not None else (
        lang.file_finder(path) if lang.file_finder else []
    )

    # Enable file cache for entire prepare operation — context building,
    # file selection, and content extraction all read the same files.
    already_cached = _utils_mod._cache_enabled
    if not already_cached:
        enable_file_cache()
    try:
        context = build_review_context(path, lang, state, files=all_files)
        selected = select_files_for_review(lang, path, state,
                                           max_files=max_files,
                                           max_age_days=max_age_days,
                                           force_refresh=force_refresh,
                                           files=all_files)
        file_requests = _build_file_requests(selected, lang, state)
    finally:
        if not already_cached:
            disable_file_cache()

    dims = dimensions or config_dimensions or DEFAULT_DIMENSIONS
    lang_guide = LANG_GUIDANCE.get(lang.name, {})

    return {
        "command": "review",
        "language": lang.name,
        "dimensions": dims,
        "dimension_prompts": {d: DIMENSION_PROMPTS[d] for d in dims if d in DIMENSION_PROMPTS},
        "lang_guidance": lang_guide,
        "context": _serialize_context(context),
        "system_prompt": REVIEW_SYSTEM_PROMPT,
        "files": file_requests,
        "total_candidates": len(file_requests),
        "cache_status": {
            "fresh": _count_fresh(state, max_age_days),
            "stale": _count_stale(state, max_age_days),
            "new": len(file_requests),
        },
    }


def _build_file_requests(files: list[str], lang, state: dict) -> list[dict]:
    """Build per-file review request dicts."""
    file_requests = []
    for filepath in files:
        content = read_file_text(_abs(filepath))
        if content is None:
            continue

        rpath = rel(filepath)
        zone = "production"
        if lang._zone_map is not None:
            zone = lang._zone_map.get(filepath).value

        # Get import neighbors for context
        neighbors: dict = {}
        if lang._dep_graph:
            entry = _dep_graph_lookup(lang._dep_graph, filepath)
            imports_raw = entry.get("imports", set())
            importers_raw = entry.get("importers", set())
            neighbors = {
                "imports": _rel_list(imports_raw),
                "importers": _rel_list(importers_raw),
                "importer_count": _importer_count(entry),
            }

        file_requests.append({
            "file": rpath,
            "content": content,
            "zone": zone,
            "loc": len(content.splitlines()),
            "neighbors": neighbors,
            "existing_findings": _get_file_findings(state, filepath),
        })
    return file_requests


# ── Holistic review preparation ──────────────────────────────────

_HOLISTIC_WORKFLOW = [
    "Read .desloppify/query.json for context, excerpts, and investigation batches",
    "For each batch: read the listed files, evaluate the batch's dimensions (batches are independent — parallelize)",
    "Cross-reference findings with the sibling_behavior and convention data",
    "For simple issues (missing import, wrong name): fix directly in code, then note as resolved",
    "For cross-cutting issues: write to findings.json (format described in system_prompt)",
    "Import: desloppify review --import findings.json --holistic",
    "Run `desloppify issues` to see the work queue, then fix each finding and resolve",
]


def prepare_holistic_review(path: Path, lang, state: dict, *,
                            dimensions: list[str] | None = None,
                            files: list[str] | None = None) -> dict:
    """Prepare holistic review data for agent consumption. Returns structured dict."""
    all_files = files if files is not None else (
        lang.file_finder(path) if lang.file_finder else []
    )

    already_cached = _utils_mod._cache_enabled
    if not already_cached:
        enable_file_cache()
    try:
        context = build_holistic_context(path, lang, state, files=all_files)
        # Also include per-file review context for reference
        review_ctx = build_review_context(path, lang, state, files=all_files)
    finally:
        if not already_cached:
            disable_file_cache()

    dims = dimensions or HOLISTIC_DIMENSIONS
    lang_guide = LANG_GUIDANCE.get(lang.name, {})
    batches = _build_investigation_batches(context, lang)

    return {
        "command": "review",
        "mode": "holistic",
        "language": lang.name,
        "dimensions": dims,
        "dimension_prompts": {d: HOLISTIC_DIMENSION_PROMPTS[d]
                              for d in dims if d in HOLISTIC_DIMENSION_PROMPTS},
        "lang_guidance": lang_guide,
        "holistic_context": context,
        "review_context": _serialize_context(review_ctx),
        "system_prompt": HOLISTIC_REVIEW_SYSTEM_PROMPT,
        "total_files": context.get("codebase_stats", {}).get("total_files", 0),
        "workflow": _HOLISTIC_WORKFLOW,
        "investigation_batches": batches,
    }


def _collect_unique_files(sources: list[list[dict]], key: str = "file") -> list[str]:
    """Collect unique file paths from multiple source lists (max 15)."""
    seen: set[str] = set()
    out: list[str] = []
    for src in sources:
        for item in src:
            f = item.get(key, "")
            if f and f not in seen:
                seen.add(f)
                out.append(f)
    return out[:15]


def _batch_arch_coupling(ctx: dict) -> dict:
    """Batch 1: Architecture & Coupling — god modules, import-time side effects."""
    arch = ctx.get("architecture", {})
    coupling = ctx.get("coupling", {})
    files = _collect_unique_files([arch.get("god_modules", []),
                                   coupling.get("module_level_io", [])])
    return {"name": "Architecture & Coupling",
            "dimensions": ["cross_module_architecture"],
            "files_to_read": files,
            "why": "god modules, import-time side effects"}


def _batch_conventions_errors(ctx: dict) -> dict:
    """Batch 2: Conventions & Errors — sibling behavior outliers, mixed strategies."""
    sibling = ctx.get("conventions", {}).get("sibling_behavior", {})
    outlier_files = [{"file": o["file"]}
                     for di in sibling.values() for o in di.get("outliers", [])]
    error_dirs = ctx.get("errors", {}).get("strategy_by_directory", {})
    mixed = [{"file": d} for d, s in error_dirs.items() if len(s) >= 3]
    files = _collect_unique_files([outlier_files, mixed])
    return {"name": "Conventions & Errors",
            "dimensions": ["error_consistency"],
            "files_to_read": files,
            "why": "naming drift, behavioral outliers, mixed error strategies"}


def _batch_abstractions_deps(ctx: dict) -> dict:
    """Batch 3: Abstractions & Dependencies — util files, dep cycles."""
    util_files = ctx.get("abstractions", {}).get("util_files", [])
    cycle_files: list[dict] = []
    for summary in ctx.get("dependencies", {}).get("cycle_summaries", []):
        for token in summary.split():
            if "/" in token and "." in token:
                cycle_files.append({"file": token.strip(",'\"")})
    files = _collect_unique_files([util_files, cycle_files])
    return {"name": "Abstractions & Dependencies",
            "dimensions": ["abstraction_fitness", "dependency_health"],
            "files_to_read": files,
            "why": "util dumping grounds, dep cycles"}


def _batch_testing_api(ctx: dict) -> dict:
    """Batch 4: Testing & API — critical untested paths, sync/async mix."""
    critical = ctx.get("testing", {}).get("critical_untested", [])
    sync_async = [{"file": f} for f in ctx.get("api_surface", {}).get("sync_async_mix", [])]
    files = _collect_unique_files([critical, sync_async])
    return {"name": "Testing & API",
            "dimensions": ["test_strategy", "api_surface_coherence"],
            "files_to_read": files,
            "why": "critical untested paths, API inconsistency"}


def _batch_authorization(ctx: dict) -> dict:
    """Batch 5: Authorization — auth gaps, service role usage."""
    auth_ctx = ctx.get("authorization", {})
    auth_files: list[dict] = []
    for rpath, info in auth_ctx.get("route_auth_coverage", {}).items():
        if info.get("without_auth", 0) > 0:
            auth_files.append({"file": rpath})
    for rpath in auth_ctx.get("service_role_usage", []):
        auth_files.append({"file": rpath})
    files = _collect_unique_files([auth_files])
    return {"name": "Authorization",
            "dimensions": ["authorization_consistency"],
            "files_to_read": files,
            "why": "auth gaps, service role usage, RLS coverage"}


def _batch_ai_debt_migrations(ctx: dict) -> dict:
    """Batch 6: AI Debt & Migrations — deprecated markers, migration TODOs."""
    ai_debt = ctx.get("ai_debt_signals", {})
    migration = ctx.get("migration_signals", {})
    debt_files: list[dict] = []
    for rpath in ai_debt.get("file_signals", {}):
        debt_files.append({"file": rpath})
    dep_files = migration.get("deprecated_markers", {}).get("files")
    if isinstance(dep_files, dict):
        for entry in dep_files:
            debt_files.append({"file": entry})
    for entry in migration.get("migration_todos", []):
        debt_files.append({"file": entry.get("file", "")})
    files = _collect_unique_files([debt_files])
    return {"name": "AI Debt & Migrations",
            "dimensions": ["ai_generated_debt", "incomplete_migration"],
            "files_to_read": files,
            "why": "AI-generated patterns, deprecated markers, migration TODOs"}


def _batch_package_organization(ctx: dict) -> dict:
    """Batch 7: Package Organization — file placement, directory boundaries."""
    structure = ctx.get("structure", {})
    struct_files: list[dict] = []
    for rf in structure.get("root_files", []):
        if rf.get("role") == "peripheral":
            struct_files.append({"file": rf["file"]})
    dir_profiles = structure.get("directory_profiles", {})
    largest_dirs = sorted(dir_profiles.items(), key=lambda x: -x[1].get("file_count", 0))[:3]
    for dir_key, profile in largest_dirs:
        for fname in profile.get("files", [])[:3]:
            dir_path = dir_key.rstrip("/")
            rpath = f"{dir_path}/{fname}" if dir_path != "." else fname
            struct_files.append({"file": rpath})
    coupling_matrix = structure.get("coupling_matrix", {})
    seen_edges: set[str] = set()
    for edge in coupling_matrix:
        if " \u2192 " in edge:
            a, b = edge.split(" \u2192 ", 1)
            reverse = f"{b} \u2192 {a}"
            if reverse in coupling_matrix and edge not in seen_edges:
                seen_edges.add(edge)
                seen_edges.add(reverse)
                for d in (a, b):
                    for fname in dir_profiles.get(d, {}).get("files", [])[:2]:
                        dir_path = d.rstrip("/")
                        rpath = f"{dir_path}/{fname}" if dir_path != "." else fname
                        struct_files.append({"file": rpath})
    files = _collect_unique_files([struct_files])
    return {"name": "Package Organization",
            "dimensions": ["package_organization"],
            "files_to_read": files,
            "why": "file placement, directory boundaries, architectural layering"}


def _build_investigation_batches(holistic_ctx: dict, lang) -> list[dict]:
    """Derive up to 7 independent, parallelizable investigation batches from context.

    Each batch groups related dimensions and the files an agent should read.
    Max 15 files per batch, deduplicated. Batches 5-7 only appear when
    their respective context data is non-empty.
    """
    batches = [
        _batch_arch_coupling(holistic_ctx),
        _batch_conventions_errors(holistic_ctx),
        _batch_abstractions_deps(holistic_ctx),
        _batch_testing_api(holistic_ctx),
        _batch_authorization(holistic_ctx),
        _batch_ai_debt_migrations(holistic_ctx),
        _batch_package_organization(holistic_ctx),
    ]
    return [b for b in batches if b["files_to_read"]]
