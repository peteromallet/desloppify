"""Directory-level structure/coupling context for holistic review."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from desloppify.intelligence.review.context import importer_count
from desloppify.utils import rel, resolve_path


def compute_structure_context(
    file_contents: dict[str, str], lang: Any
) -> dict[str, object]:
    """Compute directory profiles, root-level file analysis, and coupling matrix."""
    graph = lang.dep_graph or {}
    structure: dict[str, object] = {}

    file_info: dict[str, dict] = {}
    for filepath, content in file_contents.items():
        rel_path = rel(filepath)
        loc = len(content.splitlines())
        entry = graph.get(resolve_path(filepath), {})
        fan_in = importer_count(entry)
        imports_raw = entry.get("imports", set())
        fan_out = (
            len(imports_raw)
            if isinstance(imports_raw, set)
            else entry.get("import_count", 0)
        )
        file_info[rel_path] = {"loc": loc, "fan_in": fan_in, "fan_out": fan_out}

    dir_files: dict[str, list[str]] = {}
    for rel_path in file_info:
        parts = Path(rel_path).parts
        dir_key = "." if len(parts) == 1 else str(Path(*parts[:-1])) + "/"
        dir_files.setdefault(dir_key, []).append(rel_path)

    dir_profiles: dict[str, dict] = {}
    for dir_key, files_in_dir in dir_files.items():
        if len(files_in_dir) < 2:
            continue

        total_loc = sum(file_info[file]["loc"] for file in files_in_dir)
        avg_fan_in = sum(file_info[file]["fan_in"] for file in files_in_dir) / len(
            files_in_dir
        )
        avg_fan_out = sum(file_info[file]["fan_out"] for file in files_in_dir) / len(
            files_in_dir
        )

        imports_from: Counter = Counter()
        imported_by: Counter = Counter()
        for file in files_in_dir:
            entry = graph.get(resolve_path(file), {})
            for imp in entry.get("imports", set()):
                imp_rel = rel(imp)
                imp_parts = Path(imp_rel).parts
                imp_dir = (
                    str(Path(*imp_parts[:-1])) + "/" if len(imp_parts) > 1 else "."
                )
                if imp_dir != dir_key:
                    imports_from[imp_dir] += 1
            for imp in entry.get("importers", set()):
                imp_rel = rel(imp)
                imp_parts = Path(imp_rel).parts
                imp_dir = (
                    str(Path(*imp_parts[:-1])) + "/" if len(imp_parts) > 1 else "."
                )
                if imp_dir != dir_key:
                    imported_by[imp_dir] += 1

        zone_counts: Counter = Counter()
        if lang.zone_map is not None:
            for file in files_in_dir:
                zone_counts[lang.zone_map.get(file).value] += 1

        dir_profiles[dir_key] = {
            "file_count": len(files_in_dir),
            "files": [Path(file).name for file in sorted(files_in_dir)],
            "total_loc": total_loc,
            "avg_fan_in": round(avg_fan_in, 1),
            "avg_fan_out": round(avg_fan_out, 1),
        }
        if zone_counts:
            dir_profiles[dir_key]["zones"] = dict(zone_counts)
        if imports_from:
            dir_profiles[dir_key]["imports_from_dirs"] = dict(
                imports_from.most_common(10)
            )
        if imported_by:
            dir_profiles[dir_key]["imported_by_dirs"] = dict(
                imported_by.most_common(10)
            )

    structure["directory_profiles"] = dir_profiles

    root_files = []
    for rel_path in dir_files.get(".", []):
        info = file_info[rel_path]
        role = "core" if info["fan_in"] >= 5 else "peripheral"
        root_files.append(
            {
                "file": rel_path,
                "loc": info["loc"],
                "fan_in": info["fan_in"],
                "fan_out": info["fan_out"],
                "role": role,
            }
        )
    if root_files:
        root_files.sort(key=lambda item: -item["fan_in"])
        structure["root_files"] = root_files

    edge_counts: Counter = Counter()
    for dir_key, profile in dir_profiles.items():
        for target, count in profile.get("imports_from_dirs", {}).items():
            edge_counts[f"{dir_key} → {target}"] += count
    if edge_counts:
        structure["coupling_matrix"] = dict(edge_counts.most_common(20))

    return structure


__all__ = ["compute_structure_context"]
