"""C/C++ file discovery and function extraction scaffolds."""

from __future__ import annotations

import hashlib
import re
from os import PathLike
from pathlib import Path

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.base.discovery.source import SourceDiscoveryOptions, find_source_files
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.languages.cxx._parse_helpers import find_matching_brace

CXX_SOURCE_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx")
CXX_HEADER_EXTENSIONS = (
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".ipp",
    ".inl",
    ".tpp",
    ".txx",
    ".tcc",
)
CXX_EXTENSIONS = [*CXX_SOURCE_EXTENSIONS, *CXX_HEADER_EXTENSIONS]
CXX_FILE_EXCLUSIONS = [
    "build",
    "cmake-build-debug",
    "cmake-build-release",
    ".git",
    "node_modules",
]

_FUNC_DECL_RE = re.compile(
    r"(?:(?:^)|(?<=[;}\n]))\s*"
    r"(?:(?:inline|static|constexpr|virtual|explicit|friend|extern|typename)\s+)*"
    r"(?>(?:[A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)*(?:<[^;{}()]+>)?[\s*&:]+)+)"
    r"([A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)*)\s*"
    r"\(([^()]*)\)\s*"
    r"(?:const\s*)?"
    r"(?:noexcept(?:\([^)]*\))?\s*)?"
    r"(?:->\s*[^;{]+)?"
    r"\{",
    re.MULTILINE,
)
_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE_RE = re.compile(r"//.*?$", re.MULTILINE)


def find_cxx_files(path: Path | str) -> list[str]:
    """Find C/C++ source files under a path."""
    return find_source_files(
        path,
        CXX_EXTENSIONS,
        SourceDiscoveryOptions(exclusions=tuple(CXX_FILE_EXCLUSIONS)),
    )


def _split_params(param_str: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in param_str:
        if ch in ("<", "(", "[", "{"):
            depth += 1
        elif ch in (">", ")", "]", "}"):
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _extract_params(param_str: str) -> list[str]:
    params: list[str] = []
    for raw in _split_params(param_str):
        token = raw.strip().split("=")[0].strip()
        if not token:
            continue
        parts = [
            part for part in token.replace("&", " ").replace("*", " ").split() if part
        ]
        if not parts:
            continue
        name = parts[-1]
        if re.fullmatch(r"[A-Za-z_]\w*", name):
            params.append(name)
    return params


def normalize_cxx_body(body: str) -> str:
    """Normalize a C/C++ function body for duplicate detection."""
    no_block_comments = _COMMENT_BLOCK_RE.sub("", body)
    no_comments = _COMMENT_LINE_RE.sub("", no_block_comments)
    lines = [line.strip() for line in no_comments.splitlines() if line.strip()]
    return "\n".join(lines)


def extract_cxx_functions(filepath: str) -> list[FunctionInfo]:
    """Extract C/C++ free and qualified function definitions from one file."""
    try:
        resolved = resolve_path(filepath)
        content = Path(resolved).read_text(errors="replace")
    except OSError:
        return []

    functions: list[FunctionInfo] = []
    for match in _FUNC_DECL_RE.finditer(content):
        name = match.group(1).split("::")[-1]
        start = match.start()
        start_line = content.count("\n", 0, start) + 1
        open_pos = match.end() - 1
        end = find_matching_brace(content, open_pos)
        if end is None:
            continue

        end_line = content.count("\n", 0, end) + 1
        body = content[start : end + 1]
        normalized = normalize_cxx_body(body)
        functions.append(
            FunctionInfo(
                name=name,
                file=resolved,
                line=start_line,
                end_line=end_line,
                loc=max(1, end_line - start_line + 1),
                body=body,
                normalized=normalized,
                body_hash=hashlib.md5(
                    normalized.encode("utf-8"),
                    usedforsecurity=False,
                ).hexdigest(),
                params=_extract_params(match.group(2)),
            )
        )

    return functions


def extract_all_cxx_functions(
    path_or_files: Path | str | PathLike[str] | list[str],
) -> list[FunctionInfo]:
    """Extract C/C++ functions from either a scan root or an explicit file list."""
    if isinstance(path_or_files, (Path, str, PathLike)):
        file_list = find_cxx_files(Path(path_or_files))
    else:
        file_list = list(path_or_files)

    functions: list[FunctionInfo] = []
    for filepath in file_list:
        functions.extend(extract_cxx_functions(filepath))
    return functions
