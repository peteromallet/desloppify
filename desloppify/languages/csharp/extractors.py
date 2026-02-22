"""C# extraction: function bodies, class structure, and file discovery."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from desloppify.engine.detectors.base import ClassInfo, FunctionInfo
from desloppify.file_discovery import find_source_files, resolve_path
from desloppify.languages.csharp._parse_helpers import (
    extract_csharp_params as _extract_csharp_params,
)
from desloppify.languages.csharp._parse_helpers import (
    find_expression_end as _find_expression_end,
)
from desloppify.languages.csharp._parse_helpers import (
    find_matching_brace as _find_matching_brace,
)
from desloppify.languages.csharp.extractors_classes import CSharpExtractorDeps
from desloppify.languages.csharp.extractors_classes import (
    extract_csharp_classes as _extract_csharp_classes,
)

CSHARP_FILE_EXCLUSIONS = ["bin", "obj", ".vs", ".idea", "packages"]

_METHOD_KEYWORDS = {
    "if",
    "for",
    "foreach",
    "while",
    "switch",
    "catch",
    "using",
    "lock",
    "return",
    "throw",
    "nameof",
    "typeof",
    "default",
    "where",
}

_CLASS_DECL_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:public|private|protected|internal|static|abstract|sealed|partial)\s+)*"
    r"(?:class|record|struct)\s+([A-Za-z_]\w*)\b([^\\{\\n;]*)\{"
)

_METHOD_DECL_RE = re.compile(
    r"(?m)^[ \t]*"
    r"(?:(?:public|private|protected|internal|static|virtual|override|abstract|sealed|partial|"
    r"async|extern|unsafe|new|required)\s+)+"
    r"(?:[\w<>\[\],\.\?]+\s+)+"
    r"([A-Za-z_]\w*)\s*"
    r"\(([^)]*)\)\s*"
    r"(?:where[^{;\n=>]+)?"
    r"(\{|=>)"
)

_FIELD_RE = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|internal|static|readonly|volatile|const|required)\s+)+"
    r"[\w<>\[\],\.\?]+\s+([A-Za-z_]\w*)\s*(?:=|;|\{)"
)

_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE_RE = re.compile(r"//.*?$", re.MULTILINE)


def find_csharp_files(path: Path | str) -> list[str]:
    """Find C# source files below ``path``."""
    return find_source_files(path, [".cs"], exclusions=CSHARP_FILE_EXCLUSIONS)


def _read_file(filepath: str) -> str | None:
    """Read file text, returning None on decode/IO errors."""
    p = Path(resolve_path(filepath))
    try:
        return p.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def normalize_csharp_body(body: str) -> str:
    """Normalize method body for duplicate comparison."""
    no_block_comments = _COMMENT_BLOCK_RE.sub("", body)
    no_comments = _COMMENT_LINE_RE.sub("", no_block_comments)
    out: list[str] = []
    for line in no_comments.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"\b(?:Console\.Write(?:Line)?|logger\.\w+)\s*\(", stripped):
            continue
        out.append(stripped)
    return "\n".join(out)


def extract_csharp_functions(filepath: str) -> list[FunctionInfo]:
    """Extract C# methods as FunctionInfo objects."""
    content = _read_file(filepath)
    if content is None:
        return []

    functions: list[FunctionInfo] = []
    for m in _METHOD_DECL_RE.finditer(content):
        name = m.group(1)
        if name in _METHOD_KEYWORDS:
            continue
        params = _extract_csharp_params(m.group(2))
        body_kind = m.group(3)
        start = m.start()
        start_line = content.count("\n", 0, start) + 1

        if body_kind == "{":
            open_pos = m.end() - 1
            end = _find_matching_brace(content, open_pos)
            if end is None:
                continue
            end_line = content.count("\n", 0, end) + 1
            body = content[start : end + 1]
        else:
            end = _find_expression_end(content, m.end())
            if end is None:
                continue
            end_line = content.count("\n", 0, end) + 1
            body = content[start : end + 1]

        normalized = normalize_csharp_body(body)
        min_normalized_lines = 1 if body_kind == "=>" else 3
        if len(normalized.splitlines()) < min_normalized_lines:
            continue
        loc = max(1, end_line - start_line + 1)
        functions.append(
            FunctionInfo(
                name=name,
                file=filepath,
                line=start_line,
                end_line=end_line,
                loc=loc,
                body=body,
                normalized=normalized,
                body_hash=hashlib.md5(normalized.encode()).hexdigest(),
                params=params,
            )
        )

    return functions


def extract_csharp_classes(path: Path | str) -> list[ClassInfo]:
    """Extract class-level entities from C# source files."""
    deps = CSharpExtractorDeps(
        class_decl_re=_CLASS_DECL_RE,
        method_decl_re=_METHOD_DECL_RE,
        method_keywords=_METHOD_KEYWORDS,
        field_re=_FIELD_RE,
        find_matching_brace_fn=_find_matching_brace,
        find_expression_end_fn=_find_expression_end,
        extract_params_fn=_extract_csharp_params,
    )
    return _extract_csharp_classes(
        path,
        find_files_fn=find_csharp_files,
        read_file_fn=_read_file,
        deps=deps,
    )
