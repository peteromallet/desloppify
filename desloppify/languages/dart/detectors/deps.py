"""Dart dependency graph builder."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from desloppify.engine.detectors.graph import finalize_graph
from desloppify.languages.dart.extractors import find_dart_files
from desloppify.languages.dart.pubspec import read_package_name
from desloppify.utils import PROJECT_ROOT, resolve_path

_DART_DIRECTIVE_RE = re.compile(
    r"""(?m)^\s*(?:import|export|part)\s+['"]([^'"]+)['"]"""
)


def _find_project_root(path: Path) -> Path:
    """Walk up to nearest pubspec root; fall back to provided path."""
    cursor = path if path.is_dir() else path.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "pubspec.yaml").is_file():
            return candidate
    return cursor


def _resolve_import(
    spec: str,
    *,
    source_file: Path,
    project_root: Path,
    package_name: str | None,
    production_files: set[str],
) -> str | None:
    cleaned = spec.strip()
    if not cleaned or cleaned.startswith("dart:"):
        return None

    candidates: list[Path] = []
    if cleaned.startswith("package:"):
        package_ref = cleaned[len("package:") :]
        if "/" not in package_ref:
            return None
        package, rel_path = package_ref.split("/", 1)
        if package_name and package == package_name:
            candidates.append((project_root / "lib" / rel_path).resolve())
    elif cleaned.startswith("./") or cleaned.startswith("../"):
        candidates.append((source_file.parent / cleaned).resolve())
    elif cleaned.startswith("/"):
        candidates.append((project_root / cleaned.lstrip("/")).resolve())
    else:
        candidates.append((project_root / "lib" / cleaned).resolve())

    for candidate in candidates:
        probe_paths: list[Path] = [candidate]
        if not candidate.suffix:
            probe_paths.append(candidate.with_suffix(".dart"))
        for probe in probe_paths:
            probe_str = str(probe)
            if probe_str in production_files:
                return probe_str
            try:
                rel_probe = str(probe.relative_to(PROJECT_ROOT))
            except ValueError:
                rel_probe = None
            if rel_probe and rel_probe in production_files:
                return rel_probe
    return None


def build_dep_graph(
    path: Path,
    roslyn_cmd: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build Dart dependency graph from import/export/part directives."""
    del roslyn_cmd
    files = find_dart_files(path)
    abs_files = [str(Path(resolve_path(filepath)).resolve()) for filepath in files]
    graph = {filepath: {"imports": set(), "importers": set()} for filepath in abs_files}
    if not graph:
        return {}

    project_root = _find_project_root(Path(path).resolve())
    package_name = read_package_name(project_root)
    production_files = set(graph.keys())

    for filepath in abs_files:
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            # Preserve context for troubleshooting while skipping unreadable files.
            _ = (filepath, exc)
            continue
        source_file = Path(filepath)
        for match in _DART_DIRECTIVE_RE.finditer(content):
            resolved = _resolve_import(
                match.group(1),
                source_file=source_file,
                project_root=project_root,
                package_name=package_name,
                production_files=production_files,
            )
            if not resolved or resolved == filepath:
                continue
            graph[filepath]["imports"].add(resolved)
            graph[resolved]["importers"].add(filepath)

    return finalize_graph(graph)
