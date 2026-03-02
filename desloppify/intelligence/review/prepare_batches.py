"""Holistic investigation batch builders for review preparation."""

from __future__ import annotations

from pathlib import Path

from desloppify.intelligence.review._context.models import HolisticContext

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
    "desloppify/README.md",
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
            ctx.coupling.get("boundary_violations", []),
            ctx.dependencies.get("deferred_import_density", []),
        ],
        max_files=max_files,
    )
    return {
        "name": "Architecture & Coupling",
        "dimensions": ["cross_module_architecture", "high_level_elegance"],
        "files_to_read": files,
        "why": "god modules, import-time side effects, boundary violations, deferred import pressure",
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

    exception_files = [
        {"file": item.get("file", "")}
        for item in ctx.errors.get("exception_hotspots", [])
        if isinstance(item, dict)
    ]
    dupe_files = [
        {"file": item.get("files", [""])[0]}
        for item in ctx.conventions.get("duplicate_clusters", [])
        if isinstance(item, dict) and item.get("files")
    ]
    naming_drift_files: list[dict[str, str]] = []
    for entry in ctx.conventions.get("naming_drift", []):
        if isinstance(entry, dict):
            directory = entry.get("directory", "")
            for filepath in _representative_files_for_directory(ctx, directory):
                naming_drift_files.append({"file": filepath})

    files = _collect_unique_files(
        [outlier_files, mixed_dir_files, exception_files, dupe_files, naming_drift_files],
        max_files=max_files,
    )
    return {
        "name": "Conventions & Errors",
        "dimensions": ["convention_outlier", "error_consistency", "mid_level_elegance"],
        "files_to_read": files,
        "why": "naming drift, behavioral outliers, mixed error strategies, exception hotspots, duplicate clusters",
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

    delegation_files = [
        {"file": item.get("file", "")}
        for item in ctx.abstractions.get("delegation_heavy_classes", [])
        if isinstance(item, dict)
    ]
    facade_files = [
        {"file": item.get("file", "")}
        for item in ctx.abstractions.get("facade_modules", [])
        if isinstance(item, dict)
    ]
    type_violation_files = [
        {"file": item.get("file", "")}
        for item in ctx.abstractions.get("typed_dict_violations", [])
        if isinstance(item, dict)
    ]

    complexity_files = [
        {"file": item.get("file", "")}
        for item in ctx.abstractions.get("complexity_hotspots", [])
        if isinstance(item, dict)
    ]

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
            delegation_files,
            facade_files,
            type_violation_files,
            complexity_files,
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
        "why": "abstraction hotspots (wrappers/interfaces/param bags/delegation-heavy classes/facade modules/TypedDict violations), dep cycles",
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
    """Batch 5: Authorization - auth gaps, service role usage, RLS coverage."""
    auth_ctx = ctx.authorization
    auth_files: list[dict] = []
    for rpath, info in auth_ctx.get("route_auth_coverage", {}).items():
        if info.get("without_auth", 0) > 0:
            auth_files.append({"file": rpath})
    for rpath in auth_ctx.get("service_role_usage", []):
        auth_files.append({"file": rpath})
    # Include SQL/migration files that define tables without RLS
    rls_coverage = auth_ctx.get("rls_coverage", {})
    rls_files = rls_coverage.get("files", {})
    if isinstance(rls_files, dict):
        for _table, file_paths in rls_files.items():
            if isinstance(file_paths, list):
                for fpath in file_paths:
                    auth_files.append({"file": fpath})
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
    # Add flat_dir_findings directory representatives
    for entry in structure.get("flat_dir_findings", []):
        if isinstance(entry, dict):
            directory = entry.get("directory", "")
            for filepath in _representative_files_for_directory(ctx, directory):
                struct_files.append({"file": filepath})
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


def _batch_state_design(ctx: HolisticContext, *, max_files: int | None = None) -> dict:
    """Batch 8: State & Design Integrity - mutable globals, signal density hotspots."""
    evidence = ctx.scan_evidence
    mutable_files = [
        item for item in evidence.get("mutable_globals", [])
        if isinstance(item, dict)
    ]
    complexity_files = [
        item for item in evidence.get("complexity_hotspots", [])[:10]
        if isinstance(item, dict)
    ]
    error_files = [
        item for item in evidence.get("error_hotspots", [])[:10]
        if isinstance(item, dict)
    ]
    density_files = [
        {"file": item["file"]}
        for item in evidence.get("signal_density", [])[:10]
        if isinstance(item, dict) and item.get("file")
    ]
    files = _collect_unique_files(
        [mutable_files, complexity_files, error_files, density_files],
        max_files=max_files,
    )
    return {
        "name": "State & Design Integrity",
        "dimensions": ["initialization_coupling", "design_coherence"],
        "files_to_read": files,
        "why": "mutable global state, concentrated quality signals, initialization coupling patterns",
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
        _batch_state_design(ctx, max_files=max_files_per_batch),
        _batch_governance_contracts(
            ctx,
            repo_root=repo_root,
            max_files=max_files_per_batch,
        ),
    ]
    return [batch for batch in batches if batch["files_to_read"]]


def filter_batches_to_dimensions(
    batches: list[dict],
    dimensions: list[str],
    *,
    fallback_max_files: int | None = 80,
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
    max_files = fallback_max_files if isinstance(fallback_max_files, int) else None
    if isinstance(max_files, int) and max_files <= 0:
        max_files = None
    fallback_files = _collect_files_from_batches(filtered or batches, max_files=max_files)
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


def batch_concerns(
    concerns: list,
    *,
    max_files: int | None = None,
    active_dimensions: list[str] | None = None,
) -> dict | None:
    """Build investigation batch from mechanical concern signals.

    *concerns* should be a list of Concern dataclass instances from
    ``desloppify.engine.concerns``.
    """
    if not concerns:
        return None
    default_dims = ["design_coherence", "initialization_coupling"]
    selected_dims = [
        dim for dim in (active_dimensions or [])
        if isinstance(dim, str) and dim
    ]
    selected_set = set(selected_dims)
    overlap_dims = [dim for dim in default_dims if dim in selected_set]
    concern_dims = overlap_dims or list(default_dims)
    mapped_to_active_dims = bool(selected_dims) and not overlap_dims
    if mapped_to_active_dims:
        # Prevent concern signals from being silently dropped by scoped runs.
        concern_dims = list(selected_dims)

    types = sorted({c.type for c in concerns if c.type})
    why_parts = ["mechanical detectors identified structural patterns needing judgment"]
    if types:
        why_parts.append(f"concern types: {', '.join(types)}")
    if mapped_to_active_dims:
        why_parts.append(
            "mapped to active dimensions because design_coherence/initialization_coupling are not selected"
        )
    files: list[str] = []
    seen: set[str] = set()
    concern_signals: list[dict[str, object]] = []
    for concern in concerns:
        candidate = _normalize_file_path(getattr(concern, "file", ""))
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        files.append(candidate)

        evidence_raw = getattr(concern, "evidence", ())
        evidence = [
            str(entry).strip()
            for entry in evidence_raw
            if isinstance(entry, str) and entry.strip()
        ][:4]
        summary = str(getattr(concern, "summary", "")).strip()
        question = str(getattr(concern, "question", "")).strip()
        concern_type = str(getattr(concern, "type", "")).strip()
        concern_signals.append(
            {
                "type": concern_type or "design_concern",
                "file": candidate,
                "summary": summary or "Mechanical concern requires subjective judgment",
                "question": question or "Is this pattern intentional or debt?",
                "evidence": evidence,
            }
        )

    total_candidate_files = len(files)
    if (
        max_files is not None
        and isinstance(max_files, int)
        and max_files > 0
        and total_candidate_files > max_files
    ):
        files = files[:max_files]
        why_parts.append(
            f"truncated to {max_files} files from {total_candidate_files} candidates"
        )

    return {
        "name": "Design coherence — Mechanical Concern Signals",
        "dimensions": concern_dims,
        "files_to_read": files,
        "why": "; ".join(why_parts),
        "total_candidate_files": total_candidate_files,
        "concern_signals": concern_signals[:12],
        "concern_signal_count": len(concern_signals),
        "mapped_to_active_dimensions": mapped_to_active_dims,
    }


__all__ = ["batch_concerns", "build_investigation_batches", "filter_batches_to_dimensions"]
