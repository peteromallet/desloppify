"""Dart extraction: function parsing and file discovery."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.file_discovery import resolve_path
from desloppify.file_discovery import find_source_files
from desloppify.utils import strip_c_style_comments

DART_FILE_EXCLUSIONS = ["build", ".dart_tool", ".fvm", ".git", "node_modules"]

_FUNC_DECL_RE = re.compile(
    r"(?m)^\s*"
    r"(?:(?:@[\w\.\(\),<>\s]+)\s*)*"
    r"(?:(?:external|static|final|const|factory|late|required|covariant)\s+)*"
    r"(?:[A-Za-z_]\w*(?:<[^>{}]+>)?\??\s+)?"
    r"([A-Za-z_]\w*)\s*\(([^)]*)\)\s*(?:async\s*)?(=>|\{)"
)
_KEYWORDS = {"if", "for", "while", "switch", "catch", "return"}


def find_dart_files(path: Path | str) -> list[str]:
    """Find Dart source files under path."""
    return find_source_files(path, [".dart"], exclusions=DART_FILE_EXCLUSIONS)


def _find_matching_brace(content: str, open_pos: int) -> int | None:
    depth = 0
    in_string: str | None = None
    escape = False
    for i in range(open_pos, len(content)):
        ch = content[i]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == in_string:
                in_string = None
            continue
        if ch in {'"', "'"}:
            in_string = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _find_statement_end(content: str, start_pos: int) -> int | None:
    in_string: str | None = None
    escape = False
    for i in range(start_pos, len(content)):
        ch = content[i]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == in_string:
                in_string = None
            continue
        if ch in {'"', "'"}:
            in_string = ch
            continue
        if ch == ";":
            return i
    return None


def _extract_params(raw_params: str) -> list[str]:
    names: list[str] = []
    for chunk in raw_params.split(","):
        token = chunk.strip().split("=")[0].strip()
        if not token:
            continue
        parts = [part for part in token.split() if part]
        if not parts:
            continue
        name = parts[-1].strip()
        if name.startswith("{") or name.startswith("["):
            continue
        if name.endswith("}") or name.endswith("]"):
            continue
        if name.startswith("@"):
            name = name[1:]
        if re.fullmatch(r"[A-Za-z_]\w*", name):
            names.append(name)
    return names


def _normalize_body(body: str) -> str:
    stripped = strip_c_style_comments(body)
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    return "\n".join(lines)


def extract_dart_functions(filepath: str) -> list[FunctionInfo]:
    """Extract Dart functions/methods from one file."""
    try:
        content = Path(resolve_path(filepath)).read_text(errors="replace")
    except OSError:
        return []

    functions: list[FunctionInfo] = []
    for match in _FUNC_DECL_RE.finditer(content):
        name = match.group(1)
        if name in _KEYWORDS:
            continue
        params = _extract_params(match.group(2))
        body_kind = match.group(3)
        start = match.start()
        start_line = content.count("\n", 0, start) + 1

        if body_kind == "{":
            open_pos = match.end() - 1
            end = _find_matching_brace(content, open_pos)
            if end is None:
                continue
            end_line = content.count("\n", 0, end) + 1
            body = content[start : end + 1]
        else:
            end = _find_statement_end(content, match.end())
            if end is None:
                continue
            end_line = content.count("\n", 0, end) + 1
            body = content[start : end + 1]

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
    """Extract all Dart functions below a directory path."""
    functions: list[FunctionInfo] = []
    for filepath in find_dart_files(path):
        functions.extend(extract_dart_functions(filepath))
    return functions
