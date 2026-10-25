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
    parse_file_symbols as _parse_file_symbols,
)
from desloppify.languages.csharp.detectors.deps_support_projects import (
    find_csproj_files as _find_csproj_files,
    map_file_to_project as _map_file_to_project,
    parse_csproj_references as _parse_csproj_references,
    parse_project_assets_references as _parse_project_assets_references,
)
from desloppify.languages.csharp.detectors.deps_support_render import (
    build_graph_from_edge_map as _build_graph_from_edge_map,
    render_cycles_for_graph as _render_cycles_for_graph,
    render_deps_for_graph as _render_deps_for_graph,
    safe_resolve_graph_path as _safe_resolve_graph_path,
)
from desloppify.languages.csharp.extractors import (
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
    namespace_types: dict[tuple[str | None, str], set[str]] = defaultdict(set)
    namespace_symbols: dict[tuple[str | None, str], set[str]] = defaultdict(set)
    file_to_reference_symbols: dict[str, set[str]] = {}
    file_to_identifiers: dict[str, set[str]] = {}
    entrypoint_files: set[str] = set()
    for filepath in cs_files:
        source = resolve_path(filepath)
        namespace, usings, is_entrypoint = _parse_file_metadata(filepath)
        declared_types, identifiers, extension_methods = _parse_file_symbols(filepath)
        file_to_namespace[source] = namespace
        file_to_usings[source] = usings
        file_to_identifiers[source] = identifiers
        for type_name in declared_types:
            namespace_types[namespace, type_name].add(source)
        reference_symbols = declared_types | extension_methods
        reference_symbols.update(
            name.removesuffix("Attribute") for name in declared_types if name.endswith("Attribute")
        )
        file_to_reference_symbols[source] = reference_symbols
        for symbol in reference_symbols:
            namespace_symbols[namespace, symbol].add(source)
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
        allowed_projects: set[Path] | None = None
        allowed_namespaces: set[str] | None = None
        if proj is not None:
            allowed_projects = {proj} | project_refs.get(proj, set())
            allowed_namespaces = set()
            for ap in allowed_projects:
                allowed_namespaces.update(project_to_namespaces.get(ap, set()))

        # C# types in the current namespace need no using directive. Match
        # declared type names against code identifiers so unused siblings stay
        # unreferenced and unrelated projects sharing a namespace stay isolated.
        namespace = file_to_namespace[source]
        for identifier in file_to_identifiers[source]:
            for target in namespace_symbols.get((namespace, identifier), set()):
                if target == source:
                    continue
                if (
                    allowed_projects is not None
                    and file_to_project.get(target) not in allowed_projects
                ):
                    continue
                graph[source]["imports"].add(target)
                graph[target]["importers"].add(source)

        for using_ns in usings:
            # Static imports and type aliases name a type rather than an entire
            # namespace. Prefer that declaration over the broad namespace match.
            type_namespace, _, type_name = using_ns.rpartition(".")
            type_targets = namespace_types.get((type_namespace or None, type_name))
            targets = type_targets or _expand_namespace_matches(using_ns, namespace_to_files)
            for target in targets:
                if target == source:
                    continue
                if (
                    allowed_projects is not None
                    and file_to_project.get(target) not in allowed_projects
                ):
                    continue
                # An ordinary using only makes names available. It is not a
                # dependency on every file in that namespace (nor evidence that
                # tests exercise them). Keep only referenced type/extension names.
                if not type_targets and not (
                    file_to_reference_symbols[target] & file_to_identifiers[source]
                ):
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
