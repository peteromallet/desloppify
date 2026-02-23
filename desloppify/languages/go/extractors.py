"""Go function extraction: regex-based with brace-depth tracking.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.file_discovery import find_source_files, resolve_path

GO_FILE_EXCLUSIONS = ["vendor", "testdata", ".git", "node_modules"]

_FUNC_DECL_RE = re.compile(
    r"(?m)^func\s+"
    r"(?:\(\s*\w+\s+\*?\w+(?:\[[\w,\s]+\])?\s*\)\s*)?"  # optional receiver
    r"(\w+)"  # function name
    r"(?:\[[\w,\s~|]+\])?"  # optional type params (generics)
    r"\s*\("
)


def find_go_files(path: Path | str) -> list[str]:
    """Find Go source files under path."""
    return find_source_files(path, [".go"], exclusions=GO_FILE_EXCLUSIONS)


def _find_matching_brace(content: str, open_pos: int) -> int | None:
    """Find closing brace for a Go function body with string/comment awareness."""
    depth = 0
    i = open_pos
    length = len(content)
    while i < length:
        ch = content[i]

        # Backtick raw string — skip until closing backtick
        if ch == '`':
            i += 1
            while i < length and content[i] != '`':
                i += 1
            i += 1
            continue

        # Block comment
        if ch == '/' and i + 1 < length and content[i + 1] == '*':
            i += 2
            while i + 1 < length:
                if content[i] == '*' and content[i + 1] == '/':
                    i += 2
                    break
                i += 1
            else:
                i += 1
            continue

        # Line comment
        if ch == '/' and i + 1 < length and content[i + 1] == '/':
            while i < length and content[i] != '\n':
                i += 1
            continue

        # Interpreted string literal
        if ch == '"':
            i += 1
            while i < length:
                c = content[i]
                if c == '\\':
                    i += 2
                    continue
                if c == '"':
                    break
                i += 1
            i += 1
            continue

        # Rune literal
        if ch == "'":
            i += 1
            while i < length:
                c = content[i]
                if c == '\\':
                    i += 2
                    continue
                if c == "'":
                    break
                i += 1
            i += 1
            continue

        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i

        i += 1
    return None


def normalize_go_body(body: str) -> str:
    """Strip comments, blank lines, and logging for duplicate detection."""
    lines: list[str] = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        # Skip line comments
        if stripped.startswith("//"):
            continue
        # Skip common logging/debug statements
        if re.match(r"^\s*(?:log\.\w+|fmt\.Print)", stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _find_body_brace(content: str, pos: int) -> int | None:
    """Find the body-opening '{' after a Go func signature, skipping return types.

    Handles return types like ``map[string]struct{}`` that contain braces
    before the actual function body.  The body-opening brace in Go is always
    preceded by whitespace, while type-literal braces (``struct{}``,
    ``interface{}``) are preceded by an identifier character.
    """
    paren_depth = 1  # we start inside the param list '('
    i = pos
    length = len(content)
    while i < length:
        ch = content[i]

        # Skip string / rune / backtick / comment literals
        if ch == '`':
            i += 1
            while i < length and content[i] != '`':
                i += 1
            i += 1
            continue
        if ch == '"':
            i += 1
            while i < length:
                if content[i] == '\\':
                    i += 2
                    continue
                if content[i] == '"':
                    break
                i += 1
            i += 1
            continue
        if ch == '/' and i + 1 < length and content[i + 1] == '/':
            while i < length and content[i] != '\n':
                i += 1
            continue
        if ch == '/' and i + 1 < length and content[i + 1] == '*':
            i += 2
            while i + 1 < length:
                if content[i] == '*' and content[i + 1] == '/':
                    i += 2
                    break
                i += 1
            else:
                i += 1
            continue

        if ch == '(':
            paren_depth += 1
        elif ch == ')':
            paren_depth -= 1
        elif ch == '{' and paren_depth == 0:
            # In Go, the body-opening '{' is always preceded by whitespace
            # (or ')' / '}' at end of return type).  Type-literal braces
            # like struct{} and interface{} are preceded by an identifier.
            prev = content[i - 1] if i > 0 else ' '
            if not prev.isalnum() and prev != '_':
                return i
            # Otherwise it's a type-literal brace — skip the balanced pair.
        i += 1
    return None


def _extract_params(content: str, open_paren: int) -> list[str]:
    """Extract parameter names from the first balanced (...) starting at open_paren."""
    depth = 0
    i = open_paren
    length = len(content)
    # Find closing paren of param list
    while i < length:
        ch = content[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                break
        i += 1
    else:
        return []

    raw_params = content[open_paren + 1 : i]
    params: list[str] = []
    for chunk in raw_params.split(","):
        token = chunk.strip()
        if not token:
            continue
        parts = token.split()
        if parts:
            param_name = parts[0]
            if re.fullmatch(r"[A-Za-z_]\w*", param_name):
                params.append(param_name)
    return params


def extract_go_functions(filepath: str) -> list[FunctionInfo]:
    """Extract Go functions/methods from one file."""
    try:
        content = Path(resolve_path(filepath)).read_text(errors="replace")
    except OSError:
        return []

    functions: list[FunctionInfo] = []
    for match in _FUNC_DECL_RE.finditer(content):
        name = match.group(1)
        start = match.start()
        start_line = content.count("\n", 0, start) + 1

        # The regex ends just after the opening '(' of the param list.
        # Scan forward to find the body-opening '{' while respecting
        # balanced parens/brackets in return types like map[K]struct{}.
        brace_pos = _find_body_brace(content, match.end())
        if brace_pos is None:
            continue

        end = _find_matching_brace(content, brace_pos)
        if end is None:
            continue

        end_line = content.count("\n", 0, end) + 1
        body = content[start : end + 1]

        # Extract parameter names — the regex match ends at '(' so
        # match.end() - 1 is the opening paren position.
        params = _extract_params(content, match.end() - 1)

        normalized = normalize_go_body(body)
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
    """Extract all Go functions below a directory path."""
    functions: list[FunctionInfo] = []
    for filepath in find_go_files(path):
        functions.extend(extract_go_functions(filepath))
    return functions
