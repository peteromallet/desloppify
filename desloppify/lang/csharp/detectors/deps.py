"""C# dependency graph builder + coupling display commands."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections import defaultdict
from pathlib import Path

from ....csharp_deps_cli import cmd_cycles as _cmd_cycles_impl
from ....csharp_deps_cli import cmd_deps as _cmd_deps_impl
from ....csharp_deps_fallback import build_fallback_dep_graph
from ....detectors.graph import finalize_graph
from ....utils import resolve_path

_DEFAULT_ROSLYN_TIMEOUT_SECONDS = 20
_DEFAULT_ROSLYN_MAX_OUTPUT_BYTES = 5 * 1024 * 1024
_DEFAULT_ROSLYN_MAX_EDGES = 200000


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
    return build_fallback_dep_graph(path)


def resolve_roslyn_cmd_from_args(args) -> str | None:
    """Resolve roslyn command from language runtime context."""
    lang_cfg = getattr(args, "_lang_config", None)
    if lang_cfg is not None and hasattr(lang_cfg, "runtime_option"):
        runtime_value = lang_cfg.runtime_option("roslyn_cmd", "")
        if isinstance(runtime_value, str) and runtime_value.strip():
            return runtime_value.strip()
    return None


def cmd_deps(args) -> None:
    """Show dependency info for a specific C# file or top coupled files."""
    _cmd_deps_impl(
        args,
        build_dep_graph=build_dep_graph,
        resolve_roslyn_cmd=resolve_roslyn_cmd_from_args,
    )


def cmd_cycles(args) -> None:
    """Show import cycles in C# source files."""
    _cmd_cycles_impl(
        args,
        build_dep_graph=build_dep_graph,
        resolve_roslyn_cmd=resolve_roslyn_cmd_from_args,
    )
