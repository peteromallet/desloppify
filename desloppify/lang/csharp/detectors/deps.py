"""C# dependency graph builder + coupling display commands."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from ....detectors.graph import detect_cycles, finalize_graph, get_coupling_score
from ....utils import PROJECT_ROOT, c, print_table, rel, resolve_path
from ..extractors import CSHARP_FILE_EXCLUSIONS, find_csharp_files

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
_DEFAULT_ROSLYN_TIMEOUT_SECONDS = 20
_DEFAULT_ROSLYN_MAX_OUTPUT_BYTES = 5 * 1024 * 1024
_DEFAULT_ROSLYN_MAX_EDGES = 200000


def _is_excluded_path(path: Path) -> bool:
    """True when path is under a known excluded directory."""
    return any(part in _PROJECT_EXCLUSIONS for part in path.parts)


def _find_csproj_files(path: Path) -> list[Path]:
    """Find .csproj files under path, excluding build artifact directories."""
    found: list[Path] = []
    for p in path.rglob("*.csproj"):
        if _is_excluded_path(p):
            continue
        found.append(p.resolve())
    return sorted(found)


def _parse_csproj_references(csproj_file: Path) -> tuple[set[Path], str | None]:
    """Parse ProjectReference includes and optional RootNamespace."""
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
                refs.add((csproj_file.parent / include_path).resolve())
        elif tag == "RootNamespace":
            if elem.text and elem.text.strip():
                root_ns = elem.text.strip()
    return refs, root_ns


def _resolve_project_ref_path(raw_ref: str, base_dirs: tuple[Path, ...]) -> Path | None:
    """Resolve a .csproj path against a list of base directories."""
    ref = (raw_ref or "").strip().strip('"').replace("\\", "/")
    if not ref:
        return None
    if not ref.lower().endswith(".csproj"):
        return None
    ref_path = Path(ref)
    if ref_path.is_absolute():
        try:
            return ref_path.resolve()
        except OSError:
            return None
    fallback: Path | None = None
    for base_dir in base_dirs:
        try:
            candidate = (base_dir / ref_path).resolve()
        except OSError:
            continue
        if candidate.exists():
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback


def _parse_project_assets_references(csproj_file: Path) -> set[Path]:
    """Parse project refs from obj/project.assets.json, if available."""
    assets_file = csproj_file.parent / "obj" / "project.assets.json"
    if not assets_file.exists():
        return set()
    try:
        payload = json.loads(assets_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()

    refs: set[Path] = set()
    base_dirs = (csproj_file.parent, assets_file.parent)

    libraries = payload.get("libraries")
    if isinstance(libraries, dict):
        for lib_meta in libraries.values():
            if not isinstance(lib_meta, dict):
                continue
            if str(lib_meta.get("type", "")).lower() != "project":
                continue
            for key in ("path", "msbuildProject"):
                raw_ref = lib_meta.get(key)
                if not isinstance(raw_ref, str):
                    continue
                resolved = _resolve_project_ref_path(raw_ref, base_dirs)
                if resolved is not None:
                    refs.add(resolved)

    dep_groups = payload.get("projectFileDependencyGroups")
    if isinstance(dep_groups, dict):
        for deps in dep_groups.values():
            if not isinstance(deps, list):
                continue
            for dep in deps:
                if not isinstance(dep, str):
                    continue
                # Entries can include version qualifiers: "Foo.Bar >= 1.2.3".
                dep_token = dep.split(maxsplit=1)[0]
                resolved = _resolve_project_ref_path(dep_token, base_dirs)
                if resolved is not None:
                    refs.add(resolved)

    refs.discard(csproj_file.resolve())
    return refs


def _map_file_to_project(cs_files: list[str], projects: list[Path]) -> dict[str, Path]:
    """Assign each source file to the nearest containing .csproj directory."""
    project_dirs = sorted((p.parent for p in projects), key=lambda d: len(d.parts), reverse=True)
    mapping: dict[str, Path] = {}
    for filepath in cs_files:
        abs_file = Path(resolve_path(filepath))
        for proj_dir in project_dirs:
            try:
                abs_file.relative_to(proj_dir)
            except ValueError:
                continue
            # Choose the .csproj file in that directory.
            match = next((p for p in projects if p.parent == proj_dir), None)
            if match is not None:
                mapping[str(abs_file)] = match
                break
    return mapping


def _is_entrypoint_file(filepath: Path, content: str) -> bool:
    """Best-effort bootstrap detection for app delegates and platform entry files."""
    rel_path = rel(str(filepath)).replace("\\", "/")
    if filepath.name in _ENTRY_FILE_HINTS:
        return True
    is_platform_path = any(hint in rel_path for hint in _ENTRY_PATH_HINTS)
    if is_platform_path and (_PLATFORM_BASE_RE.search(content) or _PLATFORM_REGISTER_RE.search(content)):
        return True
    if _MAIN_METHOD_RE.search(content):
        return True
    if _MAUI_APP_FACTORY_RE.search(content):
        return True
    if _PLATFORM_BASE_RE.search(content):
        return True
    if _PLATFORM_REGISTER_RE.search(content):
        return True
    return False


def _parse_file_metadata(filepath: str) -> tuple[str | None, set[str], bool]:
    """Return (namespace, using_namespaces, is_entrypoint) for one C# file."""
    abs_path = Path(resolve_path(filepath))
    try:
        content = abs_path.read_text()
    except (OSError, UnicodeDecodeError):
        return None, set(), False

    namespace = None
    ns_match = _NAMESPACE_RE.search(content)
    if ns_match:
        namespace = ns_match.group(1)

    usings: set[str] = set()
    usings.update(_USING_RE.findall(content))
    usings.update(_USING_ALIAS_RE.findall(content))
    usings.update(_USING_STATIC_RE.findall(content))
    return namespace, usings, _is_entrypoint_file(abs_path, content)


def _expand_namespace_matches(using_ns: str, namespace_to_files: dict[str, set[str]]) -> set[str]:
    """Resolve one using namespace to candidate target files."""
    out: set[str] = set()
    for ns, files in namespace_to_files.items():
        if ns == using_ns or ns.startswith(using_ns + ".") or using_ns.startswith(ns + "."):
            out.update(files)
    return out


def _safe_resolve_graph_path(raw_path: str) -> str:
    try:
        return resolve_path(raw_path)
    except OSError:
        return raw_path


def _build_graph_from_edge_map(edge_map: dict[str, set[str]]) -> dict[str, dict]:
    graph: dict[str, dict] = defaultdict(lambda: {"imports": set(), "importers": set()})
    for source, imports in edge_map.items():
        graph[source]
        for target in imports:
            if target == source:
                continue
            graph[source]["imports"].add(target)
            graph[target]["importers"].add(source)
    return finalize_graph(dict(graph))


def _resolve_env_int(name: str, default: int, *, min_value: int = 1) -> int:
    """Read an integer env var with lower-bound clamping."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(min_value, parsed)


def _parse_roslyn_graph_payload(payload: dict) -> dict[str, dict] | None:
    """Parse Roslyn JSON payload into the shared graph format."""
    edge_map: dict[str, set[str]] = defaultdict(set)
    max_edges = _resolve_env_int("DESLOPPIFY_CSHARP_ROSLYN_MAX_EDGES", _DEFAULT_ROSLYN_MAX_EDGES)
    edge_count = 0

    files = payload.get("files")
    if isinstance(files, list):
        for entry in files:
            if not isinstance(entry, dict):
                continue
            source = entry.get("file")
            if not isinstance(source, str) or not source.strip():
                continue
            source_resolved = _safe_resolve_graph_path(source)
            edge_map[source_resolved]
            imports = entry.get("imports", [])
            if not isinstance(imports, list):
                imports = []
            for target in imports:
                if not isinstance(target, str) or not target.strip():
                    continue
                edge_map[source_resolved].add(_safe_resolve_graph_path(target))
                edge_count += 1
                if edge_count > max_edges:
                    return None
        if edge_map:
            return _build_graph_from_edge_map(edge_map)
        return None

    edges = payload.get("edges")
    if isinstance(edges, list):
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = edge.get("source") or edge.get("from")
            target = edge.get("target") or edge.get("to")
            if not isinstance(source, str) or not source.strip():
                continue
            if not isinstance(target, str) or not target.strip():
                continue
            edge_map[_safe_resolve_graph_path(source)].add(_safe_resolve_graph_path(target))
            edge_count += 1
            if edge_count > max_edges:
                return None
        if edge_map:
            return _build_graph_from_edge_map(edge_map)

    return None


def _build_roslyn_command(roslyn_cmd: str, path: Path) -> list[str] | None:
    """Convert command template to argv safely without shell execution."""
    split_posix = os.name != "nt"
    try:
        if "{path}" in roslyn_cmd:
            expanded = roslyn_cmd.replace("{path}", str(path))
            argv = shlex.split(expanded, posix=split_posix)
        else:
            argv = shlex.split(roslyn_cmd, posix=split_posix)
            argv.append(str(path))
    except ValueError:
        return None
    return argv or None


def _build_dep_graph_roslyn(path: Path, roslyn_cmd: str | None = None) -> dict[str, dict] | None:
    """Try optional Roslyn-backed graph command, return None on fallback."""
    resolved_roslyn_cmd = (roslyn_cmd or "").strip()
    if not resolved_roslyn_cmd:
        resolved_roslyn_cmd = os.environ.get("DESLOPPIFY_CSHARP_ROSLYN_CMD", "").strip()
    roslyn_cmd = resolved_roslyn_cmd
    if not roslyn_cmd:
        return None

    cmd = _build_roslyn_command(roslyn_cmd, path)
    if not cmd:
        return None
    timeout_seconds = _resolve_env_int(
        "DESLOPPIFY_CSHARP_ROSLYN_TIMEOUT_SECONDS",
        _DEFAULT_ROSLYN_TIMEOUT_SECONDS,
    )
    max_output_bytes = _resolve_env_int(
        "DESLOPPIFY_CSHARP_ROSLYN_MAX_OUTPUT_BYTES",
        _DEFAULT_ROSLYN_MAX_OUTPUT_BYTES,
    )
    try:
        proc = subprocess.run(
            cmd,
            shell=False,
            check=False,
            capture_output=True,
            text=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    stdout_bytes = proc.stdout or b""
    if len(stdout_bytes) > max_output_bytes:
        return None
    payload_text = stdout_bytes.decode("utf-8", errors="replace").strip()
    if not payload_text:
        return None
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_roslyn_graph_payload(payload)


def build_dep_graph(path: Path, roslyn_cmd: str | None = None) -> dict[str, dict]:
    """Build a C# dependency graph compatible with shared graph detectors."""
    roslyn_graph = _build_dep_graph_roslyn(path, roslyn_cmd=roslyn_cmd)
    if roslyn_graph is not None:
        return roslyn_graph

    graph: dict[str, dict] = defaultdict(lambda: {"imports": set(), "importers": set()})

    cs_files = find_csharp_files(path)
    if not cs_files:
        return finalize_graph({})

    projects = _find_csproj_files(path)
    project_refs: dict[Path, set[Path]] = {}
    project_root_ns: dict[Path, str | None] = {}
    for p in projects:
        refs, root_ns = _parse_csproj_references(p)
        project_refs[p] = refs | _parse_project_assets_references(p)
        project_root_ns[p] = root_ns

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

    # Add project root namespaces as fallback namespace owners.
    for source, proj in file_to_project.items():
        ns = project_root_ns.get(proj)
        if ns and source not in namespace_to_files[ns]:
            namespace_to_files[ns].add(source)

    project_to_namespaces: dict[Path, set[str]] = defaultdict(set)
    for source, ns in file_to_namespace.items():
        if not ns:
            continue
        proj = file_to_project.get(source)
        if proj is not None:
            project_to_namespaces[proj].add(ns)

    for source, usings in file_to_usings.items():
        proj = file_to_project.get(source)
        allowed_namespaces: set[str] | None = None
        if proj is not None:
            allowed_projects = {proj} | project_refs.get(proj, set())
            allowed_namespaces = set()
            for ap in allowed_projects:
                allowed_namespaces.update(project_to_namespaces.get(ap, set()))

        for using_ns in usings:
            for target in _expand_namespace_matches(using_ns, namespace_to_files):
                if target == source:
                    continue
                target_ns = file_to_namespace.get(target)
                if allowed_namespaces is not None and target_ns and target_ns not in allowed_namespaces:
                    continue
                graph[source]["imports"].add(target)
                graph[target]["importers"].add(source)

    # Mark app bootstrap files as referenced roots to avoid orphan false positives.
    for source in entrypoint_files:
        graph[source]["importers"].add("__entrypoint__")

    return finalize_graph(dict(graph))


def resolve_roslyn_cmd_from_args(args) -> str | None:
    """Resolve roslyn command from language runtime context."""
    lang_cfg = getattr(args, "_lang_config", None)
    if lang_cfg is not None and hasattr(lang_cfg, "runtime_option"):
        runtime_value = lang_cfg.runtime_option("roslyn_cmd", "")
        if isinstance(runtime_value, str) and runtime_value.strip():
            return runtime_value.strip()
    return None


def cmd_deps(args):
    """Show dependency info for a specific C# file or top coupled files."""
    graph = build_dep_graph(Path(args.path), roslyn_cmd=resolve_roslyn_cmd_from_args(args))

    if getattr(args, "file", None):
        coupling = get_coupling_score(args.file, graph)
        if getattr(args, "json", False):
            import json
            print(json.dumps({"file": rel(args.file), **coupling}, indent=2))
            return
        print(c(f"\nDependency info: {rel(args.file)}\n", "bold"))
        print(f"  Fan-in (importers):  {coupling['fan_in']}")
        print(f"  Fan-out (imports):   {coupling['fan_out']}")
        print(f"  Instability:         {coupling['instability']}")
        return

    by_importers = sorted(
        graph.items(), key=lambda kv: (-kv[1].get("importer_count", 0), rel(kv[0]))
    )
    if getattr(args, "json", False):
        import json
        top = by_importers[: getattr(args, "top", 20)]
        print(
            json.dumps(
                {
                    "files": len(graph),
                    "entries": [
                        {
                            "file": rel(filepath),
                            "importers": entry.get("importer_count", 0),
                            "imports": entry.get("import_count", 0),
                        }
                        for filepath, entry in top
                    ],
                },
                indent=2,
            )
        )
        return

    print(c(f"\nC# dependency graph: {len(graph)} files\n", "bold"))
    rows = []
    for filepath, entry in by_importers[: getattr(args, "top", 20)]:
        rows.append(
            [
                rel(filepath),
                str(entry.get("importer_count", 0)),
                str(entry.get("import_count", 0)),
            ]
        )
    if rows:
        print_table(["File", "Importers", "Imports"], rows, [70, 9, 7])


def cmd_cycles(args):
    """Show import cycles in C# source files."""
    graph = build_dep_graph(Path(args.path), roslyn_cmd=resolve_roslyn_cmd_from_args(args))
    cycles, _ = detect_cycles(graph)

    if getattr(args, "json", False):
        import json
        print(
            json.dumps(
                {
                    "count": len(cycles),
                    "cycles": [
                        {"length": cy["length"], "files": [rel(f) for f in cy["files"]]}
                        for cy in cycles
                    ],
                },
                indent=2,
            )
        )
        return

    if not cycles:
        print(c("No import cycles found.", "green"))
        return

    print(c(f"\nImport cycles: {len(cycles)}\n", "bold"))
    for cy in cycles[: getattr(args, "top", 20)]:
        files = [rel(f) for f in cy["files"]]
        print(f"  [{cy['length']} files] {' -> '.join(files[:6])}" +
              (f" -> +{len(files) - 6}" if len(files) > 6 else ""))
