"""Holistic investigation batch builders for review preparation."""

from __future__ import annotations

from pathlib import Path

from desloppify.intelligence.review.context_internal.models import HolisticContext

_EXTENSIONLESS_FILENAMES = {
    "makefile",
    "dockerfile",
    "readme",
    "license",
    "build",
    "workspace",
}

_GOVERNANCE_REFERENCE_FILES: tuple[str, ...] = (
    "README.md",
    "DEVELOPMENT_PHILOSOPHY.md",
    "desloppify/STRUCTURE.md",
    "pyproject.toml",
)


def _normalize_file_path(value: object) -> str | None:
    """Normalize/validate candidate file paths for batch payloads."""
    if not isinstance(value, str):
        return None
    text = value.strip().strip(",'\"")
    if not text or text in {".", ".."}:
        return None
    if text.endswith("/"):
        return None

    basename = Path(text).name
    if not basename:
        return None
    if "." not in basename and basename.lower() not in _EXTENSIONLESS_FILENAMES:
        return None
    return text


def _collect_unique_files(
    sources: list[list[dict]],
    key: str = "file",
    *,
    max_files: int | None = None,
) -> list[str]:
    """Collect unique file paths from multiple source lists."""
    seen: set[str] = set()
    out: list[str] = []
    for src in sources:
        for item in src:
            f = _normalize_file_path(item.get(key, ""))
            if f and f not in seen:
                seen.add(f)
                out.append(f)
                if max_files is not None and len(out) >= max_files:
                    return out
    return out


def _existing_repo_files(
    repo_root: Path | None,
    candidates: tuple[str, ...],
) -> list[str]:
    """Return repository-relative paths for candidate files that exist."""
    if repo_root is None:
        return []
    out: list[str] = []
    for candidate in candidates:
        if (repo_root / candidate).is_file():
            out.append(candidate)
    return out


def _collect_files_from_batches(
    batches: list[dict], *, max_files: int | None = None
) -> list[str]:
    """Collect unique file paths across batch payloads (preserving order)."""
    seen: set[str] = set()
    out: list[str] = []
    for batch in batches:
        for filepath in batch.get("files_to_read", []):
            normalized = _normalize_file_path(filepath)
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
            if max_files is not None and len(out) >= max_files:
                return out
    return out


def _representative_files_for_directory(
    ctx: HolisticContext,
    directory: str,
    *,
    max_files: int = 3,
) -> list[str]:
    """Map a directory-level signal to representative file paths."""
    if not isinstance(directory, str) or not directory.strip():
        return []

    dir_key = directory.strip()
    if dir_key in {".", "./"}:
        normalized_dir = "."
    else:
        normalized_dir = f"{dir_key.rstrip('/')}/"

    profiles = ctx.structure.get("directory_profiles", {})
    profile = profiles.get(normalized_dir)
    if not isinstance(profile, dict):
        return []

    out: list[str] = []
    for filename in profile.get("files", []):
        if not isinstance(filename, str) or not filename:
            continue
        filepath = (
            filename
            if normalized_dir == "."
            else f"{normalized_dir.rstrip('/')}/{filename}"
        )
        normalized = _normalize_file_path(filepath)
        if not normalized or normalized in out:
            continue
        out.append(normalized)
        if len(out) >= max_files:
            break
    return out


def _batch_arch_coupling(ctx: HolisticContext, *, max_files: int | None = None) -> dict:
    """Batch 1: Architecture & Coupling - god modules, import-time side effects."""
    files = _collect_unique_files(
        [
            ctx.architecture.get("god_modules", []),
            ctx.coupling.get("module_level_io", []),
        ],
        max_files=max_files,
    )
    return {
        "name": "Architecture & Coupling",
        "dimensions": ["cross_module_architecture", "high_level_elegance"],
        "files_to_read": files,
        "why": "god modules, import-time side effects",
    }


def _batch_conventions_errors(
    ctx: HolisticContext, *, max_files: int | None = None
) -> dict:
    """Batch 2: Conventions & Errors - sibling behavior outliers, mixed strategies."""
    sibling = ctx.conventions.get("sibling_behavior", {})
    outlier_files = [
        {"file": o["file"]} for di in sibling.values() for o in di.get("outliers", [])
    ]
    error_dirs = ctx.errors.get("strategy_by_directory", {})
    mixed_dir_files: list[dict[str, str]] = []
    for directory, strategies in error_dirs.items():
        if not isinstance(strategies, dict) or len(strategies) < 3:
            continue
        for filepath in _representative_files_for_directory(ctx, directory):
            mixed_dir_files.append({"file": filepath})

    files = _collect_unique_files(
        [outlier_files, mixed_dir_files],
        max_files=max_files,
    )
    return {
        "name": "Conventions & Errors",
        "dimensions": ["convention_outlier", "error_consistency", "mid_level_elegance"],
        "files_to_read": files,
        "why": "naming drift, behavioral outliers, mixed error strategies",
    }


def _batch_abstractions_deps(
    ctx: HolisticContext, *, max_files: int | None = None
) -> dict:
    """Batch 3: Abstractions & Dependencies - abstraction hotspots, dep cycles."""
    util_files = ctx.abstractions.get("util_files", [])
    wrapper_files = [
        {"file": item.get("file", "")}
        for item in ctx.abstractions.get("pass_through_wrappers", [])
        if isinstance(item, dict)
    ]
    indirection_files = [
        {"file": item.get("file", "")}
        for item in ctx.abstractions.get("indirection_hotspots", [])
        if isinstance(item, dict)
    ]
    param_bag_files = [
        {"file": item.get("file", "")}
        for item in ctx.abstractions.get("wide_param_bags", [])
        if isinstance(item, dict)
    ]
    interface_files: list[dict[str, str]] = []
    for item in ctx.abstractions.get("one_impl_interfaces", []):
        if not isinstance(item, dict):
            continue
        for group in ("declared_in", "implemented_in"):
            for filepath in item.get(group, []):
                interface_files.append({"file": filepath})

    cycle_files: list[dict] = []
    for summary in ctx.dependencies.get("cycle_summaries", []):
        for token in summary.split():
            if "/" in token and "." in token:
                cycle_files.append({"file": token.strip(",'\"")})
    files = _collect_unique_files(
        [
            util_files,
            wrapper_files,
            indirection_files,
            param_bag_files,
            interface_files,
            cycle_files,
        ],
        max_files=max_files,
    )
    return {
        "name": "Abstractions & Dependencies",
        "dimensions": [
            "abstraction_fitness",
            "dependency_health",
            "mid_level_elegance",
            "low_level_elegance",
        ],
        "files_to_read": files,
        "why": "abstraction hotspots (wrappers/interfaces/param bags), dep cycles",
    }


def _batch_testing_api(ctx: HolisticContext, *, max_files: int | None = None) -> dict:
    """Batch 4: Testing & API - critical untested paths, sync/async mix."""
    critical = ctx.testing.get("critical_untested", [])
    sync_async = [{"file": f} for f in ctx.api_surface.get("sync_async_mix", [])]
    files = _collect_unique_files([critical, sync_async], max_files=max_files)
    return {
        "name": "Testing & API",
        "dimensions": ["test_strategy", "api_surface_coherence", "mid_level_elegance"],
        "files_to_read": files,
        "why": "critical untested paths, API inconsistency",
    }


def _batch_authorization(ctx: HolisticContext, *, max_files: int | None = None) -> dict:
    """Batch 5: Authorization - auth gaps, service role usage."""
    auth_ctx = ctx.authorization
    auth_files: list[dict] = []
    for rpath, info in auth_ctx.get("route_auth_coverage", {}).items():
        if info.get("without_auth", 0) > 0:
            auth_files.append({"file": rpath})
    for rpath in auth_ctx.get("service_role_usage", []):
        auth_files.append({"file": rpath})
    files = _collect_unique_files([auth_files], max_files=max_files)
    return {
        "name": "Authorization",
        "dimensions": ["authorization_consistency", "mid_level_elegance"],
        "files_to_read": files,
        "why": "auth gaps, service role usage, RLS coverage",
    }


def _batch_ai_debt_migrations(
    ctx: HolisticContext, *, max_files: int | None = None
) -> dict:
    """Batch 6: AI Debt & Migrations - deprecated markers, migration TODOs."""
    ai_debt = ctx.ai_debt_signals
    migration = ctx.migration_signals
    debt_files: list[dict] = []
    for rpath in ai_debt.get("file_signals", {}):
        debt_files.append({"file": rpath})
    dep_files = migration.get("deprecated_markers", {}).get("files")
    if isinstance(dep_files, dict):
        for entry in dep_files:
            debt_files.append({"file": entry})
    for entry in migration.get("migration_todos", []):
        debt_files.append({"file": entry.get("file", "")})
    files = _collect_unique_files([debt_files], max_files=max_files)
    return {
        "name": "AI Debt & Migrations",
        "dimensions": [
            "ai_generated_debt",
            "incomplete_migration",
            "low_level_elegance",
        ],
        "files_to_read": files,
        "why": "AI-generated patterns, deprecated markers, migration TODOs",
    }


def _batch_package_organization(
    ctx: HolisticContext, *, max_files: int | None = None
) -> dict:
    """Batch 7: Package Organization - file placement, directory boundaries."""
    structure = ctx.structure
    struct_files: list[dict] = []
    for rf in structure.get("root_files", []):
        if rf.get("role") == "peripheral":
            struct_files.append({"file": rf["file"]})
    dir_profiles = structure.get("directory_profiles", {})
    largest_dirs = sorted(
        dir_profiles.items(), key=lambda x: -x[1].get("file_count", 0)
    )[:3]
    for dir_key, profile in largest_dirs:
        for fname in profile.get("files", [])[:3]:
            dir_path = dir_key.rstrip("/")
            rpath = f"{dir_path}/{fname}" if dir_path != "." else fname
            struct_files.append({"file": rpath})
    coupling_matrix = structure.get("coupling_matrix", {})
    seen_edges: set[str] = set()
    for edge in coupling_matrix:
        if " → " in edge:
            a, b = edge.split(" → ", 1)
            reverse = f"{b} → {a}"
            if reverse in coupling_matrix and edge not in seen_edges:
                seen_edges.add(edge)
                seen_edges.add(reverse)
                for d in (a, b):
                    for fname in dir_profiles.get(d, {}).get("files", [])[:2]:
                        dir_path = d.rstrip("/")
                        rpath = f"{dir_path}/{fname}" if dir_path != "." else fname
                        struct_files.append({"file": rpath})
    files = _collect_unique_files([struct_files], max_files=max_files)
    return {
        "name": "Package Organization",
        "dimensions": ["package_organization", "high_level_elegance"],
        "files_to_read": files,
        "why": "file placement, directory boundaries, architectural layering",
    }


def _batch_governance_contracts(
    ctx: HolisticContext,
    *,
    repo_root: Path | None,
    max_files: int | None = None,
) -> dict:
    """Batch 8: Governance & Contracts - docs/policy promises vs runtime posture."""
    docs = _existing_repo_files(repo_root, _GOVERNANCE_REFERENCE_FILES)
    if not docs:
        return {
            "name": "Governance & Contracts",
            "dimensions": [
                "cross_module_architecture",
                "high_level_elegance",
                "test_strategy",
                "package_organization",
            ],
            "files_to_read": [],
            "why": "architecture contracts, compatibility policy, docs-vs-runtime scope, and quality-gate coverage",
        }
    top_imported = [
        {"file": filepath}
        for filepath in list(ctx.architecture.get("top_imported", {}).keys())[:5]
        if isinstance(filepath, str)
    ]
    anchor_files = _collect_unique_files(
        [
            top_imported,
            ctx.architecture.get("god_modules", []),
            ctx.coupling.get("module_level_io", []),
        ],
        max_files=5,
    )
    seen = set(docs)
    files = list(docs)
    for filepath in anchor_files:
        if filepath in seen:
            continue
        seen.add(filepath)
        files.append(filepath)
    if max_files is not None:
        files = files[:max_files]
    return {
        "name": "Governance & Contracts",
        "dimensions": [
            "cross_module_architecture",
            "high_level_elegance",
            "test_strategy",
            "package_organization",
        ],
        "files_to_read": files,
        "why": "architecture contracts, compatibility policy, docs-vs-runtime scope, and quality-gate coverage",
    }


def _ensure_holistic_context(holistic_ctx: HolisticContext | dict) -> HolisticContext:
    if isinstance(holistic_ctx, HolisticContext):
        return holistic_ctx
    return HolisticContext.from_raw(holistic_ctx)


def build_investigation_batches(
    holistic_ctx: HolisticContext | dict,
    lang: object,
    *,
    repo_root: Path | None = None,
    max_files_per_batch: int | None = None,
) -> list[dict]:
    """Derive parallelizable investigation batches from holistic context."""
    ctx = _ensure_holistic_context(holistic_ctx)
    del lang  # Reserved for future language-specific batch shaping.
    batches = [
        _batch_arch_coupling(ctx, max_files=max_files_per_batch),
        _batch_conventions_errors(ctx, max_files=max_files_per_batch),
        _batch_abstractions_deps(ctx, max_files=max_files_per_batch),
        _batch_testing_api(ctx, max_files=max_files_per_batch),
        _batch_authorization(ctx, max_files=max_files_per_batch),
        _batch_ai_debt_migrations(ctx, max_files=max_files_per_batch),
        _batch_package_organization(ctx, max_files=max_files_per_batch),
        _batch_governance_contracts(
            ctx,
            repo_root=repo_root,
            max_files=max_files_per_batch,
        ),
    ]
    return [batch for batch in batches if batch["files_to_read"]]


def filter_batches_to_dimensions(
    batches: list[dict], dimensions: list[str]
) -> list[dict]:
    """Keep only dimensions explicitly active for this holistic review run.

    If selected dimensions are not represented by any batch mapping, append a
    fallback batch over representative files so scoped runs still get guidance.
    """
    selected = [d for d in dimensions if isinstance(d, str) and d]
    if not selected:
        return []
    selected_set = set(selected)
    filtered: list[dict] = []
    covered: set[str] = set()
    for batch in batches:
        batch_dims = [dim for dim in batch.get("dimensions", []) if dim in selected_set]
        if not batch_dims:
            continue
        filtered.append({**batch, "dimensions": batch_dims})
        covered.update(batch_dims)

    missing = [dim for dim in selected if dim not in covered]
    if not missing:
        return filtered

    # Keep fallback batches tractable; giant sweeps are expensive and often
    # unnecessary when dimensions are already explicitly scoped.
    fallback_files = _collect_files_from_batches(
        filtered or batches,
        max_files=80,
    )
    if not fallback_files:
        return filtered

    filtered.append(
        {
            "name": "Cross-cutting Sweep",
            "dimensions": missing,
            "files_to_read": fallback_files,
            "why": "selected dimensions had no direct batch mapping; review representative cross-cutting files",
        }
    )
    return filtered


__all__ = ["build_investigation_batches", "filter_batches_to_dimensions"]
