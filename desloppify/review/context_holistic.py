"""Holistic codebase-wide context gathering for cross-cutting review."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .. import utils as _utils_mod
from ..utils import rel, resolve_path, read_file_text, enable_file_cache, disable_file_cache
from .context import (
    _file_excerpt,
    _importer_count,
    _FUNC_NAME_RE,
    _ERROR_PATTERNS,
    _extract_imported_names,
    _gather_ai_debt_signals,
    _gather_auth_context,
    _gather_migration_signals,
)


def _abs(filepath: str) -> str:
    """Resolve filepath to absolute using resolve_path."""
    return resolve_path(filepath)


def build_holistic_context(path: Path, lang, state: dict,
                           files: list[str] | None = None) -> dict:
    """Gather codebase-wide data for holistic review.

    Returns a dict with structured data per dimension.
    """
    if files is None:
        files = lang.file_finder(path) if lang.file_finder else []

    already_cached = _utils_mod._cache_enabled
    if not already_cached:
        enable_file_cache()
    try:
        return _build_holistic_context_inner(files, lang, state)
    finally:
        if not already_cached:
            disable_file_cache()


def _build_holistic_context_inner(files: list[str], lang, state: dict) -> dict:
    """Inner holistic context builder (runs with file cache enabled)."""
    ctx: dict = {}

    # Pre-read file contents
    file_contents: dict[str, str] = {}
    for filepath in files:
        content = read_file_text(_abs(filepath))
        if content is not None:
            file_contents[filepath] = content

    # 1. Architecture: god modules, dep chains
    arch: dict = {}
    if lang._dep_graph:
        graph = lang._dep_graph
        importer_counts = {}
        for f, entry in graph.items():
            ic = _importer_count(entry)
            if ic > 0:
                importer_counts[rel(f)] = ic
        top_imported = sorted(importer_counts.items(), key=lambda x: -x[1])[:10]
        arch["god_modules"] = [
            {"file": f, "importers": c,
             "excerpt": _file_excerpt(f) or ""}
            for f, c in top_imported if c >= 5
        ]
        arch["top_imported"] = dict(top_imported)
    ctx["architecture"] = arch

    # 2. Coupling: import-time side effects detection
    coupling: dict = {}
    module_level_io = []
    for filepath, content in file_contents.items():
        lines = content.splitlines()
        for i, line in enumerate(lines[:50]):
            stripped = line.strip()
            if stripped.startswith(("def ", "class ", "async def ", "if ", "#", "@", "import ", "from ")):
                continue
            if re.search(r"\b(?:open|connect|requests?\.|urllib|subprocess|os\.system)\b", stripped):
                module_level_io.append({"file": rel(filepath), "line": i + 1, "code": stripped[:100]})
    if module_level_io:
        coupling["module_level_io"] = module_level_io[:20]
    ctx["coupling"] = coupling

    # 3. Conventions: naming style per directory
    conventions: dict = {}
    dir_styles: dict[str, Counter] = {}
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        counter = dir_styles.setdefault(dir_name, Counter())
        for name in _FUNC_NAME_RE.findall(content):
            if "_" in name and name.islower():
                counter["snake_case"] += 1
            elif name[0].islower() and any(c.isupper() for c in name):
                counter["camelCase"] += 1
            elif name[0].isupper():
                counter["PascalCase"] += 1
    conventions["naming_by_directory"] = {
        d: dict(c.most_common(3)) for d, c in dir_styles.items() if sum(c.values()) >= 3
    }

    # 3b. Sibling behavior: imports shared across files in same directory
    dir_imports: dict[str, dict[str, set[str]]] = {}
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        rpath = rel(filepath)
        names = _extract_imported_names(content)
        dir_imports.setdefault(dir_name, {})[rpath] = names

    sibling_behavior: dict = {}
    for dir_name, file_names_map in dir_imports.items():
        total = len(file_names_map)
        if total < 3:
            continue
        name_counts: Counter = Counter()
        for names in file_names_map.values():
            for n in names:
                name_counts[n] += 1
        threshold = total * 0.6
        shared = {n: cnt for n, cnt in name_counts.items() if cnt >= threshold}
        if not shared:
            continue
        outliers = []
        for rpath, names in file_names_map.items():
            missing = [n for n in shared if n not in names]
            if missing:
                outliers.append({"file": rpath, "missing": sorted(missing)})
        if outliers:
            sibling_behavior[dir_name] = {
                "shared_patterns": {n: {"count": cnt, "total": total}
                                    for n, cnt in sorted(shared.items(),
                                                         key=lambda x: -x[1])},
                "outliers": sorted(outliers, key=lambda x: len(x["missing"]),
                                   reverse=True),
            }
    conventions["sibling_behavior"] = sibling_behavior
    ctx["conventions"] = conventions

    # 4. Error handling: strategy distribution per directory
    errors: dict = {}
    dir_errors: dict[str, Counter] = {}
    for filepath, content in file_contents.items():
        parts = Path(filepath).parts
        if len(parts) < 2:
            continue
        dir_name = parts[-2] + "/"
        counter = dir_errors.setdefault(dir_name, Counter())
        for pattern_name, pattern in _ERROR_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                counter[pattern_name] += len(matches)
    errors["strategy_by_directory"] = {
        d: dict(c.most_common(5)) for d, c in dir_errors.items() if sum(c.values()) >= 2
    }
    ctx["errors"] = errors

    # 5. Abstractions: util/helper file inventory
    abstractions: dict = {}
    util_files = []
    for filepath in file_contents:
        rpath = rel(filepath)
        basename = Path(rpath).stem.lower()
        if basename in ("utils", "helpers", "util", "helper", "common", "misc"):
            loc = len(file_contents[filepath].splitlines())
            util_files.append({"file": rpath, "loc": loc,
                               "excerpt": _file_excerpt(filepath) or ""})
    abstractions["util_files"] = sorted(util_files, key=lambda x: -x["loc"])[:20]
    ctx["abstractions"] = abstractions

    # 6. Dependencies: cycles from existing findings
    deps: dict = {}
    cycle_findings = [f for f in state.get("findings", {}).values()
                      if f.get("detector") == "cycles" and f["status"] == "open"]
    if cycle_findings:
        deps["existing_cycles"] = len(cycle_findings)
        deps["cycle_summaries"] = [f["summary"][:120] for f in cycle_findings[:10]]
    ctx["dependencies"] = deps

    # 7. Testing: coverage gaps
    testing: dict = {}
    if lang._dep_graph:
        tc_findings = {f["file"] for f in state.get("findings", {}).values()
                       if f.get("detector") == "test_coverage" and f["status"] == "open"}
        if tc_findings:
            graph = lang._dep_graph
            critical_untested = []
            for filepath in tc_findings:
                entry = graph.get(resolve_path(filepath), {})
                ic = _importer_count(entry)
                if ic >= 3:
                    critical_untested.append({"file": filepath, "importers": ic})
            testing["critical_untested"] = sorted(critical_untested, key=lambda x: -x["importers"])[:10]
    testing["total_files"] = len(file_contents)
    ctx["testing"] = testing

    # 8. API surface: export patterns
    api: dict = {}
    api_surface_fn = getattr(lang, "review_api_surface_fn", None)
    if callable(api_surface_fn):
        computed = api_surface_fn(file_contents)
        if isinstance(computed, dict):
            api = computed
    ctx["api_surface"] = api

    # 9. Authorization context
    auth_ctx = _gather_auth_context(file_contents)
    if auth_ctx:
        ctx["authorization"] = auth_ctx

    # 10. AI debt signals
    ai_debt = _gather_ai_debt_signals(file_contents)
    if ai_debt.get("file_signals"):
        ctx["ai_debt_signals"] = ai_debt

    # 11. Migration signals
    migration = _gather_migration_signals(file_contents, lang)
    if migration:
        ctx["migration_signals"] = migration

    # 12. Structure: directory profiles, root-level analysis, coupling matrix
    ctx["structure"] = _compute_structure_context(file_contents, lang)

    # Codebase stats
    total_loc = sum(len(c.splitlines()) for c in file_contents.values())
    ctx["codebase_stats"] = {
        "total_files": len(file_contents),
        "total_loc": total_loc,
    }

    return ctx


def _compute_structure_context(file_contents: dict[str, str], lang) -> dict:
    """Compute directory profiles, root-level file analysis, and coupling matrix.

    Returns a dict with keys: directory_profiles, root_files, coupling_matrix, tree.
    """
    graph = lang._dep_graph or {}
    structure: dict = {}

    # Build per-file LOC + fan-in/fan-out
    file_info: dict[str, dict] = {}
    for filepath, content in file_contents.items():
        rpath = rel(filepath)
        loc = len(content.splitlines())
        entry = graph.get(resolve_path(filepath), {})
        fan_in = _importer_count(entry)
        imports_raw = entry.get("imports", set())
        fan_out = len(imports_raw) if isinstance(imports_raw, set) else entry.get("import_count", 0)
        file_info[rpath] = {"loc": loc, "fan_in": fan_in, "fan_out": fan_out}

    # Classify files by directory
    dir_files: dict[str, list[str]] = {}
    for rpath in file_info:
        parts = Path(rpath).parts
        if len(parts) == 1:
            dir_key = "."
        else:
            dir_key = str(Path(*parts[:-1])) + "/"
        dir_files.setdefault(dir_key, []).append(rpath)

    # Directory profiles
    dir_profiles: dict[str, dict] = {}
    for dir_key, files_in_dir in dir_files.items():
        if len(files_in_dir) < 2:
            continue
        total_loc = sum(file_info[f]["loc"] for f in files_in_dir)
        avg_fan_in = sum(file_info[f]["fan_in"] for f in files_in_dir) / len(files_in_dir)
        avg_fan_out = sum(file_info[f]["fan_out"] for f in files_in_dir) / len(files_in_dir)

        # Cross-directory import edges
        imports_from: Counter = Counter()
        imported_by: Counter = Counter()
        for f in files_in_dir:
            abs_f = resolve_path(f)
            entry = graph.get(abs_f, {})
            for imp in entry.get("imports", set()):
                imp_rel = rel(imp)
                imp_parts = Path(imp_rel).parts
                imp_dir = str(Path(*imp_parts[:-1])) + "/" if len(imp_parts) > 1 else "."
                if imp_dir != dir_key:
                    imports_from[imp_dir] += 1
            for imp in entry.get("importers", set()):
                imp_rel = rel(imp)
                imp_parts = Path(imp_rel).parts
                imp_dir = str(Path(*imp_parts[:-1])) + "/" if len(imp_parts) > 1 else "."
                if imp_dir != dir_key:
                    imported_by[imp_dir] += 1

        # Zone distribution within directory
        zone_counts: Counter = Counter()
        if lang._zone_map is not None:
            for f in files_in_dir:
                zone_counts[lang._zone_map.get(f).value] += 1

        dir_profiles[dir_key] = {
            "file_count": len(files_in_dir),
            "files": [Path(f).name for f in sorted(files_in_dir)],
            "total_loc": total_loc,
            "avg_fan_in": round(avg_fan_in, 1),
            "avg_fan_out": round(avg_fan_out, 1),
        }
        if zone_counts:
            dir_profiles[dir_key]["zones"] = dict(zone_counts)
        if imports_from:
            dir_profiles[dir_key]["imports_from_dirs"] = dict(imports_from.most_common(10))
        if imported_by:
            dir_profiles[dir_key]["imported_by_dirs"] = dict(imported_by.most_common(10))

    structure["directory_profiles"] = dir_profiles

    # Root-level file analysis (files not in subdirectories)
    root_files = []
    for rpath in dir_files.get(".", []):
        info = file_info[rpath]
        role = "core" if info["fan_in"] >= 5 else "peripheral"
        root_files.append({
            "file": rpath,
            "loc": info["loc"],
            "fan_in": info["fan_in"],
            "fan_out": info["fan_out"],
            "role": role,
        })
    if root_files:
        root_files.sort(key=lambda x: -x["fan_in"])
        structure["root_files"] = root_files

    # Directory coupling matrix — top 20 cross-directory edges
    edge_counts: Counter = Counter()
    for dir_key, profile in dir_profiles.items():
        for target, count in profile.get("imports_from_dirs", {}).items():
            edge_counts[f"{dir_key} \u2192 {target}"] += count
    if edge_counts:
        structure["coupling_matrix"] = dict(edge_counts.most_common(20))

    return structure
