"""GDScript dependency graph builder."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.engine.detectors.graph import finalize_graph
from desloppify.languages.gdscript.extractors import find_gdscript_files
from desloppify.languages.gdscript.patterns import (
    AUTOLOAD_PATH_RE,
    AUTOLOAD_SECTION_RE,
    CLASS_NAME_RE,
    COMMENT_RE,
    EXTENDS_RE,
    LOAD_PATH_RE,
    RES_PATH_ATTR_RE,
    RES_SCRIPT_LITERAL_RE,
    SCENE_EXT_RESOURCE_RE,
    STRING_RE,
)

# Scenes and resources that can attach a script to a node.
_SCENE_EXTENSIONS = (".tscn", ".tres", ".scn", ".res")

# Directories never worth walking when hunting for scenes or a project file.
_SCENE_SCAN_SKIP_DIRS = {".godot", ".git", ".import", ".mono", "node_modules"}
_PROJECT_SCAN_SKIP_DIRS = _SCENE_SCAN_SKIP_DIRS | {".claude", "node_modules"}


def _find_project_root(path: Path) -> Path:
    """Locate the directory holding ``project.godot``.

    Looks upward first, then downward: a Godot project is often one folder
    inside a larger repository (engine plugins, build tooling and CI beside
    it), and the scan root is that repository. Without the downward search
    every ``res://`` path fails to resolve and the graph comes out empty.
    """
    cursor = path if path.is_dir() else path.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "project.godot").is_file():
            return candidate

    shallowest: Path | None = None
    shallowest_depth = -1
    for current_root, dirnames, filenames in os.walk(cursor, onerror=lambda _e: None):
        dirnames[:] = [d for d in dirnames if d not in _PROJECT_SCAN_SKIP_DIRS]
        if "project.godot" not in filenames:
            continue
        found = Path(current_root)
        depth = len(found.relative_to(cursor).parts)
        if shallowest is None or depth < shallowest_depth:
            shallowest, shallowest_depth = found, depth
        dirnames[:] = []
    return shallowest or cursor


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


def _read_text(filepath: str | Path) -> str | None:
    try:
        return Path(filepath).read_text(errors="replace")
    except OSError:
        return None


def _strip_noise(content: str) -> str:
    """Remove comments and string literals before identifier matching."""
    return COMMENT_RE.sub("", STRING_RE.sub(" ", content))


def _iter_scene_files(project_root: Path):
    """Yield scene/resource files below *project_root*."""
    for current_root, dirnames, filenames in os.walk(
        project_root, onerror=lambda _e: None
    ):
        dirnames[:] = [d for d in dirnames if d not in _SCENE_SCAN_SKIP_DIRS]
        for filename in filenames:
            if filename.endswith(_SCENE_EXTENSIONS):
                yield Path(current_root) / filename


def _scene_script_paths(project_root: Path) -> set[str]:
    """Collect every ``res://`` script path attached by a scene or resource."""
    found: set[str] = set()
    for scene_file in _iter_scene_files(project_root):
        content = _read_text(scene_file)
        if content is None:
            continue
        for header in SCENE_EXT_RESOURCE_RE.finditer(content):
            path_match = RES_PATH_ATTR_RE.search(header.group("attrs"))
            if path_match:
                found.add(path_match.group("path"))
    return found


def _autoload_script_paths(project_root: Path) -> set[str]:
    """Collect script paths registered as autoload singletons."""
    content = _read_text(project_root / "project.godot")
    if content is None:
        return set()
    found: set[str] = set()
    for section in AUTOLOAD_SECTION_RE.finditer(content):
        for match in AUTOLOAD_PATH_RE.finditer(section.group("body")):
            found.add(match.group("path"))
    return found


def _literal_script_paths(gdscript_files: list[str]) -> set[str]:
    """Collect ``res://`` script paths held as plain string literals.

    A registry or catalog commonly stores a script path in a data table and
    ``load()``s it later, which no preload/extends pattern can see.
    """
    found: set[str] = set()
    for filepath in gdscript_files:
        content = _read_text(filepath)
        if content is None:
            continue
        for match in RES_SCRIPT_LITERAL_RE.finditer(COMMENT_RE.sub("", content)):
            found.add(match.group("path"))
    return found


def find_gdscript_dynamic_imports(path: Path, extensions: list[str]) -> set[str]:
    """Return script paths reached without an explicit ``preload``/``extends``.

    Godot attaches most scripts through a scene's ``[ext_resource]`` block, a
    ``project.godot`` autoload entry, or a path string held in a registry table.
    None of those appear as an import in GDScript source, so without this every
    scene script, singleton and registered model looks orphaned.
    """
    del extensions
    project_root = _find_project_root(Path(path).resolve())
    targets = (
        _scene_script_paths(project_root)
        | _autoload_script_paths(project_root)
        | _literal_script_paths(find_gdscript_files(path))
    )
    # The orphan matcher compares against extension-less repo-relative paths.
    return {target[len("res://") : -len(".gd")] for target in targets}


def build_dep_graph(
    path: Path,
    roslyn_cmd: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a GDScript graph from preload/extends paths and class_name usage."""
    del roslyn_cmd
    files = find_gdscript_files(path)
    abs_files = [str(Path(resolve_path(filepath)).resolve()) for filepath in files]
    graph = {
        filepath: {"imports": set(), "importers": set(), "deferred_imports": set()}
        for filepath in abs_files
    }
    if not graph:
        return {}

    project_root = _find_project_root(Path(path).resolve())
    production_files = set(graph.keys())

    contents: dict[str, str] = {}
    declared_classes: dict[str, str] = {}
    for filepath in abs_files:
        content = _read_text(filepath)
        if content is None:
            continue
        contents[filepath] = content
        class_match = CLASS_NAME_RE.search(content)
        if class_match:
            # A duplicate class_name is a Godot error; first declaration wins.
            declared_classes.setdefault(class_match.group("name"), filepath)

    def _add_edge(importer: str, imported: str, *, deferred: bool = False) -> None:
        if imported == importer:
            return
        graph[importer]["imports"].add(imported)
        graph[imported]["importers"].add(importer)
        if deferred:
            graph[importer]["deferred_imports"].add(imported)

    for filepath, content in contents.items():
        for match in LOAD_PATH_RE.finditer(content):
            resolved = _resolve_res_path(
                match.group("path"),
                project_root=project_root,
                production_files=production_files,
            )
            if resolved:
                _add_edge(filepath, resolved)

        extends_match = EXTENDS_RE.search(content)
        if extends_match:
            resolved = _resolve_res_path(
                extends_match.group("path"),
                project_root=project_root,
                production_files=production_files,
            )
            if resolved:
                _add_edge(filepath, resolved)

    if declared_classes:
        class_usage_re = re.compile(
            r"\b(?:" + "|".join(map(re.escape, sorted(declared_classes))) + r")\b"
        )
        for filepath, content in contents.items():
            for name in set(class_usage_re.findall(_strip_noise(content))):
                declaring_file = declared_classes.get(name)
                if declaring_file:
                    # A class_name reference cannot form a load-time cycle:
                    # Godot resolves the registry globally and lazily, so two
                    # scripts naming each other (a plug and its port, say) is
                    # ordinary. Only preload/extends can cycle at parse time.
                    _add_edge(filepath, declaring_file, deferred=True)

    return finalize_graph(graph)
