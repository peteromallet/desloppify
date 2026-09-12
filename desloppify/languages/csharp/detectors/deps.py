"""C# dependency graph builder + coupling display commands."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import subprocess  # nosec B404
from collections import defaultdict
from pathlib import Path

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.engine.detectors.graph import finalize_graph
from desloppify.languages.csharp.detectors.deps_support_metadata import (
    expand_namespace_matches as _expand_namespace_matches,
    parse_file_metadata as _parse_file_metadata,
)
from desloppify.languages.csharp.detectors.deps_support_projects import (
    find_csproj_files as _find_csproj_files,
    map_file_to_project as _map_file_to_project,
    parse_csproj_references as _parse_csproj_references,
    parse_project_assets_references as _parse_project_assets_references,
)
from desloppify.languages.csharp.detectors.deps_support_razor import (
    build_component_index as _build_component_index,
    build_extension_method_index as _build_extension_method_index,
    build_type_index as _build_type_index,
    build_view_index as _build_view_index,
    code_behind_for as _code_behind_for,
    collect_ambient_usings as _collect_ambient_usings,
    find_razor_files as _find_razor_files,
    inherited_usings as _inherited_usings,
    normalize_view_ref as _normalize_view_ref,
    parse_razor_metadata as _parse_razor_metadata,
)
from desloppify.languages.csharp.detectors.deps_support_render import (
    build_graph_from_edge_map as _build_graph_from_edge_map,
    render_cycles_for_graph as _render_cycles_for_graph,
    render_deps_for_graph as _render_deps_for_graph,
    safe_resolve_graph_path as _safe_resolve_graph_path,
)
from desloppify.languages.csharp.extractors import (
    CSHARP_FILE_EXCLUSIONS,
    find_csharp_files,
)

logger = logging.getLogger(__name__)

_DEFAULT_ROSLYN_TIMEOUT_SECONDS = 20
_MIB_BYTES = 1 << 20
_DEFAULT_ROSLYN_MAX_OUTPUT_BYTES = 5 * _MIB_BYTES
_DEFAULT_ROSLYN_MAX_EDGES = 200000


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
    max_edges = _resolve_env_int(
        "DESLOPPIFY_CSHARP_ROSLYN_MAX_EDGES", _DEFAULT_ROSLYN_MAX_EDGES
    )
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
            edge_map[_safe_resolve_graph_path(source)].add(
                _safe_resolve_graph_path(target)
            )
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


def _build_dep_graph_roslyn(
    path: Path, roslyn_cmd: str | None = None
) -> dict[str, dict] | None:
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
        # Roslyn command runs via fixed argv without shell expansion.
        proc = subprocess.run(
            cmd,
            shell=False,
            check=False,
            capture_output=True,
            text=False,
            timeout=timeout_seconds,
        )  # nosec B603
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


def _link_razor_views(
    path: Path,
    *,
    graph: dict[str, dict],
    cs_files: list[str],
    razor_files: list[str],
    file_to_namespace: dict[str, str | None],
    projects: list[Path],
    file_to_project: dict[str, Path],
    entrypoint_files: set[str],
) -> None:
    """Add graph edges contributed by Razor/Blazor views.

    Views are not scored as C# source, but they reference C# that nothing else
    references. Without these edges a code-behind partial or a component used
    only from markup looks orphaned.

    Edges resolve by type name rather than by whole namespace. A view's
    ``@using`` says which namespaces are in scope, not which files it depends
    on, so linking the whole namespace would mark every file in it as live and
    hide genuinely dead code.
    """
    if not razor_files:
        return

    file_to_project.update(_map_file_to_project(razor_files, projects))
    ambient = _collect_ambient_usings(razor_files)
    component_index = _build_component_index(razor_files)
    view_index = _build_view_index(razor_files)
    type_index = _build_type_index(cs_files)
    extension_index = _build_extension_method_index(cs_files)

    def _link(source: str, target_path: str) -> None:
        """Record a view's dependency on one file."""
        target = resolve_path(target_path)
        if target == source:
            return
        graph[source]["imports"].add(target)
        graph[target]["importers"].add(source)

    def _link_by_name(
        source: str, names: set[str], index: dict[str, set[str]], in_scope: set[str]
    ) -> None:
        """Link a view to files declaring the named symbols, within scope."""
        for name in names:
            for target in index.get(name, ()):
                target_ns = file_to_namespace.get(target)
                if target_ns and in_scope and target_ns not in in_scope:
                    continue
                _link(source, target)

    for filepath in razor_files:
        source = resolve_path(filepath)
        graph[source]  # ensure entry exists
        view = _parse_razor_metadata(filepath)
        in_scope = view.usings | _inherited_usings(filepath, ambient)
        if view.namespace:
            in_scope.add(view.namespace)

        # Link the C# files declaring the types this view actually names, and
        # the extension methods it calls, which name no type at the call site.
        _link_by_name(source, view.identifiers, type_index, in_scope)
        _link_by_name(source, view.invoked_members, extension_index, in_scope)
        # Tag helpers and view components are reached by naming convention, so
        # their type name never appears literally in the markup.
        _link_by_name(source, view.convention_types, type_index, set())

        # Partials and layouts are named as strings rather than types.
        for view_ref in view.view_refs:
            referenced = view_index.get(_normalize_view_ref(view_ref))
            if referenced:
                _link(source, referenced)

        # A view is the only consumer of its own code-behind partial.
        code_behind = _code_behind_for(filepath)
        if code_behind:
            _link(source, code_behind)

        for component_name in view.component_refs:
            defining_view = component_index.get(component_name)
            if defining_view:
                _link(source, defining_view)

        # A routable page is reachable by URL, so it is a root like Program.cs.
        if view.is_routable:
            entrypoint_files.add(source)


def build_dep_graph(path: Path, roslyn_cmd: str | None = None) -> dict[str, dict]:
    """Build a C# dependency graph compatible with shared graph detectors."""
    roslyn_graph = _build_dep_graph_roslyn(path, roslyn_cmd=roslyn_cmd)
    if roslyn_graph is not None:
        return roslyn_graph

    graph: dict[str, dict] = defaultdict(lambda: {"imports": set(), "importers": set()})

    cs_files = find_csharp_files(path)
    # A Razor class library can be almost entirely views, so the absence of C#
    # sources is not the absence of a graph.
    razor_files = _find_razor_files(path, tuple(CSHARP_FILE_EXCLUSIONS))
    if not cs_files and not razor_files:
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

    def _allowed_namespaces_for(source: str) -> set[str] | None:
        """Namespaces a file may reference, limited to its project's references."""
        proj = file_to_project.get(source)
        if proj is None:
            return None
        allowed_projects = {proj} | project_refs.get(proj, set())
        allowed: set[str] = set()
        for ap in allowed_projects:
            allowed.update(project_to_namespaces.get(ap, set()))
        return allowed

    def _link_usings(source: str, usings: set[str]) -> None:
        """Add graph edges from one file to every file its usings resolve to."""
        allowed_namespaces = _allowed_namespaces_for(source)
        for using_ns in usings:
            for target in _expand_namespace_matches(using_ns, namespace_to_files):
                if target == source:
                    continue
                target_ns = file_to_namespace.get(target)
                if (
                    allowed_namespaces is not None
                    and target_ns
                    and target_ns not in allowed_namespaces
                ):
                    continue
                graph[source]["imports"].add(target)
                graph[target]["importers"].add(source)

    for source, usings in file_to_usings.items():
        _link_usings(source, usings)

    _link_razor_views(
        path,
        graph=graph,
        cs_files=cs_files,
        razor_files=razor_files,
        file_to_namespace=file_to_namespace,
        projects=projects,
        file_to_project=file_to_project,
        entrypoint_files=entrypoint_files,
    )

    # Mark app bootstrap files as referenced roots to avoid orphan false positives.
    for source in entrypoint_files:
        graph[source]["importers"].add("__entrypoint__")

    return finalize_graph(dict(graph))


def resolve_roslyn_cmd_from_args(args) -> str | None:
    """Resolve roslyn command from detector runtime options."""
    runtime_options = getattr(args, "lang_runtime_options", None)
    if isinstance(runtime_options, dict):
        runtime_value = runtime_options.get("roslyn_cmd", "")
        if isinstance(runtime_value, str) and runtime_value.strip():
            return runtime_value.strip()
    return None


def cmd_deps(args: argparse.Namespace) -> None:
    """Show dependency info for a specific C# file or top coupled files."""
    graph = build_dep_graph(Path(args.path), roslyn_cmd=resolve_roslyn_cmd_from_args(args))
    _render_deps_for_graph(args, graph=graph)


def cmd_cycles(args: argparse.Namespace) -> None:
    """Show import cycles in C# source files."""
    graph = build_dep_graph(Path(args.path), roslyn_cmd=resolve_roslyn_cmd_from_args(args))
    _render_cycles_for_graph(args, graph=graph)
