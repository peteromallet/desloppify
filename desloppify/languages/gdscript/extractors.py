"""GDScript extraction: function parsing and file discovery."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.file_discovery import resolve_path
from desloppify.file_discovery import find_source_files

GDSCRIPT_FILE_EXCLUSIONS = [
    ".godot",
    ".import",
    ".mono",
    ".git",
    "node_modules",
]
_FUNC_DECL_RE = re.compile(r"(?m)^(\s*)func\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*:")
_COMMENT_RE = re.compile(r"(?m)#.*$")


def find_gdscript_files(path: Path | str) -> list[str]:
    """Find GDScript files under path."""
    return find_source_files(path, [".gd"], exclusions=GDSCRIPT_FILE_EXCLUSIONS)


def _extract_params(raw_params: str) -> list[str]:
    names: list[str] = []
    for chunk in raw_params.split(","):
        token = chunk.strip().split("=")[0].strip()
        if not token:
            continue
        token = token.split(":")[0].strip()
        if token and re.fullmatch(r"[A-Za-z_]\w*", token):
            names.append(token)
    return names


def _normalize_body(body: str) -> str:
    stripped = _COMMENT_RE.sub("", body)
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    return "\n".join(lines)


def _block_end_line(lines: list[str], start_index: int, base_indent: int) -> int:
    idx = start_index + 1
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            idx += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= base_indent:
            break
        idx += 1
    return max(start_index, idx - 1)


def extract_gdscript_functions(filepath: str) -> list[FunctionInfo]:
    """Extract GDScript functions from one file."""
    try:
        content = Path(resolve_path(filepath)).read_text(errors="replace")
    except OSError:
        return []
    lines = content.splitlines()
    functions: list[FunctionInfo] = []

    for match in _FUNC_DECL_RE.finditer(content):
        indent = len(match.group(1).replace("\t", "    "))
        name = match.group(2)
        params = _extract_params(match.group(3))
        start_line = content.count("\n", 0, match.start()) + 1
        start_index = start_line - 1
        end_index = _block_end_line(lines, start_index, indent)
        end_line = end_index + 1
        body = "\n".join(lines[start_index : end_index + 1])
        normalized = _normalize_body(body)
        body_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
        functions.append(
            FunctionInfo(
                name=name,
                file=resolve_path(filepath),
                line=start_line,
                end_line=end_line,
                loc=max(1, end_line - start_line + 1),
                body=body,
                normalized=normalized,
                body_hash=body_hash,
                params=params,
            )
        )
    return functions


def extract_functions(path: Path) -> list[FunctionInfo]:
    """Extract all GDScript functions below a directory path."""
    functions: list[FunctionInfo] = []
    for filepath in find_gdscript_files(path):
        functions.extend(extract_gdscript_functions(filepath))
    return functions
