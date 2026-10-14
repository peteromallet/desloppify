"""C/C++ dependency graph builders."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.engine.detectors.graph import finalize_graph
from desloppify.languages._framework.treesitter.imports.resolvers_backend import (
    resolve_cxx_include,
)
from desloppify.languages.cxx.extractors import find_cxx_files

_TRANSLATION_UNIT_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx"})

_INCLUDE_RE = re.compile(r'(?m)^\s*#include\s*([<"])([^>"]+)[>"]')


def _normalize_graph_path(path: Path | str) -> str:
    return str(Path(path).resolve())


def _init_graph(files: list[str]) -> dict[str, dict[str, Any]]:
    return {filepath: {"imports": set(), "importers": set()} for filepath in files}


def _production_file_index(files: list[str]) -> dict[str, str]:
    return {
        os.path.normcase(_normalize_graph_path(filepath)): _normalize_graph_path(filepath)
        for filepath in files
    }


def _coerce_source_files(path: Path) -> list[str]:
    return [_normalize_graph_path(resolve_path(filepath)) for filepath in find_cxx_files(path)]


def _match_production_file(candidate: Path | str, file_index: dict[str, str]) -> str | None:
    normalized = os.path.normcase(_normalize_graph_path(candidate))
    return file_index.get(normalized)


def _read_include_specs(filepath: str) -> list[tuple[str, bool]]:
    try:
        content = Path(filepath).read_text(errors="replace")
    except OSError:
        return []
    return [
        (match.group(2).strip(), match.group(1) == '"')
        for match in _INCLUDE_RE.finditer(content)
    ]


def _parse_command_tokens(entry: dict[str, Any]) -> list[str]:
    arguments = entry.get("arguments")
    if isinstance(arguments, list):
        return [str(token) for token in arguments]

    command = entry.get("command")
    if isinstance(command, str) and command.strip():
        return shlex.split(command, posix=os.name != "nt")
    return []


def _extract_include_dirs(tokens: list[str], directory: Path) -> list[Path]:
    include_dirs: list[Path] = []
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        value: str | None = None
        if token in {"-I", "/I", "-isystem"}:
            if idx + 1 < len(tokens):
                value = tokens[idx + 1]
                idx += 1
        elif token.startswith("-I") and token != "-I":
            value = token[2:]
        elif token.startswith("/I") and token != "/I":
            value = token[2:]
        elif token.startswith("-isystem") and token != "-isystem":
            value = token[len("-isystem") :]

        if value:
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = directory / candidate
            include_dirs.append(candidate.resolve())
        idx += 1
    return include_dirs


def _resolve_with_compile_commands(
    include_spec: str,
    *,
    is_quoted: bool,
    source_file: Path,
    scan_root: Path,
    include_dirs: list[Path],
    file_index: dict[str, str],
) -> str | None:
    candidates = [include_dir / include_spec for include_dir in include_dirs]
    if is_quoted:
        candidates.insert(0, source_file.parent / include_spec)
    else:
        candidates.append(source_file.parent / include_spec)
    for candidate in candidates:
        resolved = _match_production_file(candidate, file_index)
        if resolved is not None:
            return resolved

    fallback = resolve_cxx_include(include_spec, str(source_file), str(scan_root))
    if fallback is None:
        return None
    return _match_production_file(fallback, file_index)


def _resolve_compile_command_source(entry: dict[str, Any], scan_root: Path) -> str | None:
    file_value = entry.get("file")
    if not isinstance(file_value, str) or not file_value.strip():
        return None

    directory_value = entry.get("directory")
    directory = (
        Path(directory_value).resolve()
        if isinstance(directory_value, str) and directory_value.strip()
        else scan_root
    )
    source_file = Path(file_value)
    if not source_file.is_absolute():
        source_file = directory / source_file
    return _normalize_graph_path(source_file)


def _build_from_compile_commands(
    path: Path,
    files: list[str],
) -> dict[str, dict[str, Any]]:
    graph = _init_graph(files)
    file_index = _production_file_index(files)
    compile_commands_path = path / "compile_commands.json"
    try:
        payload = json.loads(compile_commands_path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return finalize_graph(graph)
    if not isinstance(payload, list):
        return finalize_graph(graph)

    for entry in payload:
        if not isinstance(entry, dict):
            continue
        source = _resolve_compile_command_source(entry, path)
        if source is None or source not in graph:
            continue
        directory_value = entry.get("directory")
        directory = (
            Path(directory_value).resolve()
            if isinstance(directory_value, str) and directory_value.strip()
            else path
        )
        tokens = _parse_command_tokens(entry)
        if not tokens:
            continue
        # Translation units named by a compilation database are build roots, not include-imported files.
        if Path(source).suffix.lower() in _TRANSLATION_UNIT_SUFFIXES:
            graph[source]["is_entry_point"] = True
        include_dirs = _extract_include_dirs(tokens, directory)
        source_file = Path(source)
        for include_spec, is_quoted in _read_include_specs(source):
            resolved = _resolve_with_compile_commands(
                include_spec,
                is_quoted=is_quoted,
                source_file=source_file,
                scan_root=path,
                include_dirs=include_dirs,
                file_index=file_index,
            )
            if resolved is None or resolved == source:
                continue
            graph[source]["imports"].add(resolved)
            graph[resolved]["importers"].add(source)

    return finalize_graph(graph)


def _build_from_local_includes(path: Path, files: list[str]) -> dict[str, dict[str, Any]]:
    graph = _init_graph(files)
    file_index = _production_file_index(files)
    scan_root = _normalize_graph_path(path)
    for source in files:
        source_file = Path(source)
        for include_spec, _is_quoted in _read_include_specs(source):
            resolved = resolve_cxx_include(include_spec, str(source_file), scan_root)
            if resolved is None:
                continue
            target = _match_production_file(resolved, file_index)
            if target is None or target == source:
                continue
            graph[source]["imports"].add(target)
            graph[target]["importers"].add(source)
    return finalize_graph(graph)


def build_dep_graph(path: Path) -> dict[str, dict[str, Any]]:
    """Build a C/C++ dependency graph from compile commands or local includes."""
    scan_root = Path(path).resolve()
    files = _coerce_source_files(scan_root)
    if not files:
        return {}
    if (scan_root / "compile_commands.json").is_file():
        return _build_from_compile_commands(scan_root, files)
    return _build_from_local_includes(scan_root, files)
