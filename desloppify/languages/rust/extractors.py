"""Rust extraction: function parsing and file discovery."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.languages._framework.treesitter import (
    PARSE_INIT_ERRORS,
    RUST_SPEC,
    is_available,
)
from desloppify.languages._framework.treesitter.analysis.extractors import (
    ts_extract_functions,
)
from desloppify.languages.rust.support import (
    RUST_FILE_EXCLUSIONS,
    find_rust_files,
    normalize_rust_body,
    read_text_or_none,
)

_FUNC_DECL_RE = re.compile(
    r"(?m)^\s*"
    r"(?:(?:#\[[^\]]+\]\s*)*)"
    r"(?:(?:pub(?:\([^)]*\))?|async|const|unsafe|extern\s+\"[^\"]+\")\s+)*"
    r"fn\s+([A-Za-z_]\w*)"
    r"(?:<[^>{}]+>)?\s*\(([^)]*)\)"
)


def _extract_params(raw_params: str) -> list[str]:
    names: list[str] = []
    for chunk in raw_params.split(","):
        token = chunk.strip()
        if not token:
            continue
        if ":" in token:
            token = token.split(":", 1)[0].strip()
        token = token.lstrip("&").removeprefix("mut ").strip()
        if token == "self":
            names.append(token)
            continue
        if re.fullmatch(r"[A-Za-z_]\w*", token):
            names.append(token)
    return names


def _find_body_start(content: str, position: int) -> int | None:
    depth = 0
    in_string: str | None = None
    i = position
    while i < len(content):
        char = content[i]
        if in_string:
            if char == "\\":
                i += 2
                continue
            if char == in_string:
                in_string = None
            i += 1
            continue
        if char in {'"', "'"}:
            in_string = char
            i += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "{" and depth == 0:
            return i
        i += 1
    return None


def _find_matching_brace(content: str, open_pos: int) -> int | None:
    depth = 0
    in_string: str | None = None
    i = open_pos
    length = len(content)
    while i < length:
        char = content[i]
        if in_string:
            if char == "\\":
                i += 2
                continue
            if char == in_string:
                in_string = None
            i += 1
            continue
        if char in {'"', "'"}:
            in_string = char
            i += 1
            continue
        if char == "/" and i + 1 < length and content[i + 1] == "*":
            i += 2
            while i + 1 < length:
                if content[i] == "*" and content[i + 1] == "/":
                    i += 2
                    break
                i += 1
            continue
        if char == "/" and i + 1 < length and content[i + 1] == "/":
            i += 2
            while i < length and content[i] != "\n":
                i += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def extract_rust_functions(filepath: str) -> list[FunctionInfo]:
    """Extract Rust functions from one file using a regex fallback."""
    content = read_text_or_none(filepath)
    if content is None:
        return []

    functions: list[FunctionInfo] = []
    for match in _FUNC_DECL_RE.finditer(content):
        body_start = _find_body_start(content, match.end())
        if body_start is None:
            continue
        body_end = _find_matching_brace(content, body_start)
        if body_end is None:
            continue

        start = match.start()
        start_line = content.count("\n", 0, start) + 1
        end_line = content.count("\n", 0, body_end) + 1
        body = content[start : body_end + 1]
        normalized = normalize_rust_body(body)
        if len(normalized.splitlines()) < 3:
            continue

        functions.append(
            FunctionInfo(
                name=match.group(1),
                file=resolve_path(filepath),
                line=start_line,
                end_line=end_line,
                loc=max(1, end_line - start_line + 1),
                body=body,
                normalized=normalized,
                body_hash=hashlib.md5(
                    normalized.encode("utf-8"),
                    usedforsecurity=False,
                ).hexdigest()[:12],
                params=_extract_params(match.group(2)),
            )
        )
    return functions


def extract_functions(path: Path) -> list[FunctionInfo]:
    """Extract all Rust functions below a directory path."""
    file_list = find_rust_files(path)
    if not file_list:
        return []

    tree_sitter_functions = _extract_with_tree_sitter(path, file_list)
    if tree_sitter_functions is not None:
        return tree_sitter_functions

    functions: list[FunctionInfo] = []
    for filepath in file_list:
        functions.extend(extract_rust_functions(filepath))
    return functions


def _extract_with_tree_sitter(
    path: Path,
    file_list: list[str],
) -> list[FunctionInfo] | None:
    """Attempt Tree-sitter extraction when the parser runtime is available."""
    if not is_available():
        return None
    try:
        return ts_extract_functions(path, RUST_SPEC, file_list)
    except PARSE_INIT_ERRORS:
        return None


__all__ = [
    "RUST_FILE_EXCLUSIONS",
    "extract_functions",
    "extract_rust_functions",
    "find_rust_files",
]
