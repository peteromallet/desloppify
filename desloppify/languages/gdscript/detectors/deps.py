"""GDScript dependency graph builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from desloppify.engine.detectors.graph import finalize_graph
from desloppify.languages.gdscript.extractors import find_gdscript_files
from desloppify.languages.gdscript.patterns import EXTENDS_RE, LOAD_PATH_RE
from desloppify.file_discovery import resolve_path


def _find_project_root(path: Path) -> Path:
    cursor = path if path.is_dir() else path.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "project.godot").is_file():
            return candidate
    return cursor


def _resolve_res_path(
    spec: str,
    *,
    project_root: Path,
    production_files: set[str],
) -> str | None:
    cleaned = (spec or "").strip()
    if not cleaned.startswith("res://"):
        return None
    candidate = (project_root / cleaned[len("res://") :]).resolve()
    candidate_str = str(candidate)
    if candidate_str in production_files:
        return candidate_str
    return None


def build_dep_graph(
    path: Path,
    roslyn_cmd: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build GDScript graph using preload/load and extends file references."""
    del roslyn_cmd
    files = find_gdscript_files(path)
    abs_files = [str(Path(resolve_path(filepath)).resolve()) for filepath in files]
    graph = {filepath: {"imports": set(), "importers": set()} for filepath in abs_files}
    if not graph:
        return {}

    project_root = _find_project_root(Path(path).resolve())
    production_files = set(graph.keys())

    for filepath in abs_files:
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            # Preserve context for troubleshooting while skipping unreadable files.
            _ = (filepath, exc)
            continue

        for match in LOAD_PATH_RE.finditer(content):
            resolved = _resolve_res_path(
                match.group("path"),
                project_root=project_root,
                production_files=production_files,
            )
            if not resolved or resolved == filepath:
                continue
            graph[filepath]["imports"].add(resolved)
            graph[resolved]["importers"].add(filepath)

        extends_match = EXTENDS_RE.search(content)
        if extends_match:
            resolved = _resolve_res_path(
                extends_match.group("path"),
                project_root=project_root,
                production_files=production_files,
            )
            if resolved and resolved != filepath:
                graph[filepath]["imports"].add(resolved)
                graph[resolved]["importers"].add(filepath)

    return finalize_graph(graph)
