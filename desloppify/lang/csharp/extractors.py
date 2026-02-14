"""C# extraction: function bodies, class structure, and file discovery."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ... import utils
from ...detectors.base import ClassInfo, FunctionInfo
from ...utils import find_source_files

CSHARP_FILE_EXCLUSIONS = ["bin", "obj", ".vs", ".idea", "packages"]

_METHOD_KEYWORDS = {
    "if", "for", "foreach", "while", "switch", "catch", "using", "lock",
    "return", "throw", "nameof", "typeof", "default", "where",
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
    p = Path(utils.resolve_path(filepath))
    try:
        return p.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _find_matching_brace(content: str, open_pos: int) -> int | None:
    """Return index of matching '}' for a '{' at ``open_pos``."""
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
        if ch in ("'", '"'):
            in_string = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _find_expression_end(content: str, start_pos: int) -> int | None:
    """Find terminating semicolon for an expression-bodied method."""
    round_depth = 0
    curly_depth = 0
    square_depth = 0
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
        if ch in ("'", '"'):
            in_string = ch
            continue
        if ch == "(":
            round_depth += 1
        elif ch == ")":
            round_depth = max(0, round_depth - 1)
        elif ch == "{":
            curly_depth += 1
        elif ch == "}":
            curly_depth = max(0, curly_depth - 1)
        elif ch == "[":
            square_depth += 1
        elif ch == "]":
            square_depth = max(0, square_depth - 1)
        elif ch == ";" and round_depth == 0 and curly_depth == 0 and square_depth == 0:
            return i
    return None


def _split_params(param_str: str) -> list[str]:
    """Split parameter list by comma while respecting nested generic/function syntax."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in param_str:
        if ch in ("<", "(", "[", "{"):
            depth += 1
            current.append(ch)
        elif ch in (">", ")", "]", "}"):
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _extract_csharp_params(param_str: str) -> list[str]:
    """Extract parameter names from a C# method signature fragment."""
    names: list[str] = []
    for raw in _split_params(param_str):
        token = raw.strip()
        if not token:
            continue
        token = re.sub(r"^(?:this|params|ref|out|in|required)\s+", "", token)
        token = token.split("=")[0].strip()
        parts = [p for p in token.split() if p]
        if not parts:
            continue
        name = parts[-1].strip()
        if name.startswith("@"):
            name = name[1:]
        if re.match(r"^[A-Za-z_]\w*$", name):
            names.append(name)
    return names


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
            body = content[start:end + 1]
        else:
            end = _find_expression_end(content, m.end())
            if end is None:
                continue
            end_line = content.count("\n", 0, end) + 1
            body = content[start:end + 1]

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


def _extract_methods_from_block(
    block: str, filepath: str, line_offset: int,
) -> list[FunctionInfo]:
    """Extract methods from a class block."""
    methods: list[FunctionInfo] = []
    for m in _METHOD_DECL_RE.finditer(block):
        name = m.group(1)
        if name in _METHOD_KEYWORDS:
            continue
        start_line = line_offset + block.count("\n", 0, m.start())
        if m.group(3) == "{":
            open_pos = m.end() - 1
            end = _find_matching_brace(block, open_pos)
            if end is None:
                continue
            end_line = line_offset + block.count("\n", 0, end)
        else:
            end = _find_expression_end(block, m.end())
            if end is None:
                continue
            end_line = line_offset + block.count("\n", 0, end)
        methods.append(
            FunctionInfo(
                name=name,
                file=filepath,
                line=max(1, start_line),
                end_line=max(1, end_line),
                loc=max(1, end_line - start_line + 1),
                body="",
                params=_extract_csharp_params(m.group(2)),
            )
        )
    return methods


def _extract_attributes_from_block(block: str) -> list[str]:
    """Extract class field/property names from a class block."""
    attrs: set[str] = set()
    for line in block.splitlines():
        stripped = line.strip()
        if "(" in stripped:
            continue
        m = _FIELD_RE.match(line)
        if m:
            attrs.add(m.group(1))
    return sorted(attrs)


def _parse_base_classes(inherit: str) -> list[str]:
    """Parse base classes / interfaces from a class declaration suffix."""
    if ":" not in inherit:
        return []
    right = inherit.split(":", 1)[1]
    right = right.split("where", 1)[0]
    bases = []
    for raw in right.split(","):
        token = raw.strip()
        if not token:
            continue
        token = token.split("<", 1)[0].strip()
        token = token.split(".")[-1]
        if re.match(r"^[A-Za-z_]\w*$", token):
            bases.append(token)
    return bases


def _extract_classes_from_file(filepath: str, content: str) -> list[ClassInfo]:
    """Extract class-like symbols (class/record/struct) from one C# file."""
    classes: list[ClassInfo] = []
    for m in _CLASS_DECL_RE.finditer(content):
        name = m.group(1)
        inherit = m.group(2) or ""
        open_pos = m.end() - 1
        end = _find_matching_brace(content, open_pos)
        if end is None:
            continue

        start_line = content.count("\n", 0, m.start()) + 1
        end_line = content.count("\n", 0, end) + 1
        loc = max(1, end_line - start_line + 1)
        block = content[m.start():end + 1]
        methods = _extract_methods_from_block(block, filepath, start_line)
        attributes = _extract_attributes_from_block(block)
        base_classes = _parse_base_classes(inherit)
        classes.append(
            ClassInfo(
                name=name,
                file=filepath,
                line=start_line,
                loc=loc,
                methods=methods,
                attributes=attributes,
                base_classes=base_classes,
            )
        )
    return classes


def extract_csharp_classes(path: Path | str) -> list[ClassInfo]:
    """Extract class-level entities from C# source files."""
    classes: list[ClassInfo] = []
    for filepath in find_csharp_files(path):
        content = _read_file(filepath)
        if content is None:
            continue
        classes.extend(_extract_classes_from_file(filepath, content))
    return classes
