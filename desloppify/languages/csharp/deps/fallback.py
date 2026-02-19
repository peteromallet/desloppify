"""Fallback (heuristic) C# dependency graph construction."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from desloppify.engine.detectors.graph import finalize_graph
from desloppify.languages.csharp.detectors import deps as _deps_detector_mod
from desloppify.languages.csharp.extractors import (
    CSHARP_FILE_EXCLUSIONS,
    find_csharp_files,
)
from desloppify.utils import rel, resolve_path

_USING_RE = re.compile(r"(?m)^\s*(?:global\s+)?using\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;")
_USING_ALIAS_RE = re.compile(
    r"(?m)^\s*(?:global\s+)?using\s+[A-Za-z_]\w*\s*=\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"
)
_USING_STATIC_RE = re.compile(
    r"(?m)^\s*(?:global\s+)?using\s+static\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"
)
_NAMESPACE_RE = re.compile(
    r"(?m)^\s*namespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*(?:;|\{)"
)
_MAIN_METHOD_RE = re.compile(r"(?m)\bstatic\s+(?:async\s+)?(?:void|int)\s+Main\s*\(")
_MAUI_APP_FACTORY_RE = re.compile(r"(?m)\bCreateMauiApp\s*\(")
_PLATFORM_BASE_RE = re.compile(
    r"(?m)^\s*(?:public\s+)?(?:partial\s+)?class\s+\w+\s*:\s*"
    r".*\b(?:MauiUIApplicationDelegate|UIApplicationDelegate|UISceneDelegate|MauiWinUIApplication)\b"
)
_PLATFORM_REGISTER_RE = re.compile(r'(?m)\[Register\("AppDelegate"\)\]')

_ENTRY_FILE_HINTS = {
    "Program.cs",
    "Startup.cs",
    "Main.cs",
    "MauiProgram.cs",
    "MainActivity.cs",
    "AppDelegate.cs",
    "SceneDelegate.cs",
    "WinUIApplication.cs",
    "App.xaml.cs",
}
_ENTRY_PATH_HINTS = (
    "/Platforms/Android/",
    "/Platforms/iOS/",
    "/Platforms/MacCatalyst/",
    "/Platforms/Windows/",
)
_PROJECT_EXCLUSIONS = set(CSHARP_FILE_EXCLUSIONS) | {".git"}


def _is_excluded_path(path: Path) -> bool:
    return any(part in _PROJECT_EXCLUSIONS for part in path.parts)


def _find_csproj_files(path: Path) -> list[Path]:
    found: list[Path] = []
    for candidate in path.rglob("*.csproj"):
        if not _is_excluded_path(candidate):
            found.append(candidate.resolve(strict=False))
    return sorted(found)


def _parse_csproj_references(csproj_file: Path) -> tuple[set[Path], str | None]:
    refs: set[Path] = set()
    root_ns: str | None = None
    try:
        root = ET.parse(csproj_file).getroot()
    except (ET.ParseError, OSError):
        return refs, root_ns

    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1]
        if tag == "ProjectReference":
            include = elem.attrib.get("Include")
            if include:
                include_path = include.replace("\\", "/")
                refs.add((csproj_file.parent / include_path).resolve(strict=False))
        elif tag == "RootNamespace" and elem.text and elem.text.strip():
            root_ns = elem.text.strip()
    return refs, root_ns


def _resolve_project_ref_path(raw_ref: str, base_dirs: tuple[Path, ...]) -> Path | None:
    ref = (raw_ref or "").strip().strip('"').replace("\\", "/")
    if not ref or not ref.lower().endswith(".csproj"):
        return None
    ref_path = Path(ref)
    if ref_path.is_absolute():
        return ref_path.resolve(strict=False)
    fallback: Path | None = None
    for base_dir in base_dirs:
        candidate = (base_dir / ref_path).resolve(strict=False)
        if candidate.exists():
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback


def _parse_project_assets_references(csproj_file: Path) -> set[Path]:
    return _deps_detector_mod._parse_project_assets_references(csproj_file)


def _map_file_to_project(cs_files: list[str], projects: list[Path]) -> dict[str, Path]:
    project_dirs = sorted((p.parent for p in projects), key=lambda d: len(d.parts), reverse=True)
    project_by_dir = {project.parent: project for project in projects}
    mapping: dict[str, Path] = {}
    for filepath in cs_files:
        abs_file = Path(resolve_path(filepath))
        for proj_dir in project_dirs:
            if not abs_file.is_relative_to(proj_dir):
                continue
            project = project_by_dir.get(proj_dir)
            if project is None:
                continue
            mapping[str(abs_file)] = project
            break
    return mapping


def _is_entrypoint_file(filepath: Path, content: str) -> bool:
    rel_path = rel(str(filepath)).replace("\\", "/")
    if filepath.name in _ENTRY_FILE_HINTS:
        return True
    if any(hint in rel_path for hint in _ENTRY_PATH_HINTS):
        if _PLATFORM_BASE_RE.search(content) or _PLATFORM_REGISTER_RE.search(content):
            return True
    if _MAIN_METHOD_RE.search(content) or _MAUI_APP_FACTORY_RE.search(content):
        return True
    if _PLATFORM_BASE_RE.search(content) or _PLATFORM_REGISTER_RE.search(content):
        return True
    return False


def _parse_file_metadata(filepath: str) -> tuple[str | None, set[str], bool]:
    return _deps_detector_mod._parse_file_metadata(filepath)


def _expand_namespace_matches(using_ns: str, namespace_to_files: dict[str, set[str]]) -> set[str]:
    out: set[str] = set()
    for namespace, files in namespace_to_files.items():
        if namespace == using_ns or namespace.startswith(using_ns + ".") or using_ns.startswith(namespace + "."):
            out.update(files)
    return out


def build_fallback_dep_graph(path: Path) -> dict[str, dict]:
    """Build dependency graph by combining namespace imports and project references."""
    graph: dict[str, dict] = defaultdict(lambda: {"imports": set(), "importers": set()})

    cs_files = find_csharp_files(path)
    if not cs_files:
        return finalize_graph({})

    projects = _find_csproj_files(path)
    project_refs: dict[Path, set[Path]] = {}
    project_root_ns: dict[Path, str | None] = {}
    for project in projects:
        refs, root_ns = _parse_csproj_references(project)
        project_refs[project] = refs | _parse_project_assets_references(project)
        project_root_ns[project] = root_ns

    file_to_project = _map_file_to_project(cs_files, projects)

    namespace_to_files: dict[str, set[str]] = defaultdict(set)
    file_to_namespace: dict[str, str | None] = {}
    file_to_usings: dict[str, set[str]] = {}
    entrypoint_files: set[str] = set()

    for filepath in cs_files:
        source = resolve_path(filepath)
        namespace, usings, is_entrypoint = _parse_file_metadata(filepath)
        file_to_namespace[source] = namespace
        file_to_usings[source] = usings
        graph[source]
        if namespace:
            namespace_to_files[namespace].add(source)
        if is_entrypoint:
            entrypoint_files.add(source)

    for source, project in file_to_project.items():
        root_ns = project_root_ns.get(project)
        if root_ns and source not in namespace_to_files[root_ns]:
            namespace_to_files[root_ns].add(source)

    project_to_namespaces: dict[Path, set[str]] = defaultdict(set)
    for source, namespace in file_to_namespace.items():
        if not namespace:
            continue
        project = file_to_project.get(source)
        if project is not None:
            project_to_namespaces[project].add(namespace)

    for source, usings in file_to_usings.items():
        project = file_to_project.get(source)
        allowed_namespaces: set[str] | None = None
        if project is not None:
            allowed_projects = {project} | project_refs.get(project, set())
            allowed_namespaces = set()
            for allowed_project in allowed_projects:
                allowed_namespaces.update(project_to_namespaces.get(allowed_project, set()))

        for using_ns in usings:
            for target in _expand_namespace_matches(using_ns, namespace_to_files):
                if target == source:
                    continue
                target_ns = file_to_namespace.get(target)
                if allowed_namespaces is not None and target_ns and target_ns not in allowed_namespaces:
                    continue
                graph[source]["imports"].add(target)
                graph[target]["importers"].add(source)

    for source in entrypoint_files:
        graph[source]["importers"].add("__entrypoint__")

    return finalize_graph(dict(graph))
