"""File-level TypeScript/SQL security checks."""

from __future__ import annotations

import re

from desloppify.base.signal_patterns import AUTH_LOOKUP_TOKEN_RE
from desloppify.languages.typescript.detectors.security.entries import (
    _make_security_entry,
)
from desloppify.languages.typescript.detectors.security.patterns import (
    _AUTH_CHECK_RE,
    _CREATE_VIEW_RE,
    _EDGE_ENTRYPOINT_RE,
    _JSON_DEEP_CLONE_RE,
    _JSON_PARSE_RE,
    _SECURITY_INVOKER_RE,
    _SERVE_ASYNC_RE,
)

_AUTH_DENIAL_RE = re.compile(
    r"\b(?:401|403|unauthori[sz]ed|forbidden)\b"
    r"|NextResponse\.redirect\b|\bredirect\s*\("
    r"|new\s+Response\s*\([^)]*status\s*:\s*(?:401|403)",
    re.IGNORECASE,
)
_NEGATED_AUTH_BRANCH_RE = re.compile(
    r"\bif\s*\(\s*!\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?\s*\)",
    re.IGNORECASE,
)


def _file_level_security_issues(
    *,
    filepath: str,
    normalized_path: str,
    lines: list[str],
    content: str,
) -> list[dict[str, object]]:
    """Detect file-level security patterns and return issues."""
    file_issues: list[dict[str, object]] = []

    if _looks_like_edge_handler(normalized_path, content):
        if not _handler_has_auth_check(content):
            file_issues.append(
                _make_security_entry(
                    filepath,
                    1,
                    content.splitlines()[0] if lines else "",
                    check_id="edge_function_missing_auth",
                    summary="Edge function serves requests without authentication check",
                    severity="high",
                    confidence="medium",
                    remediation="Add authentication check (e.g., requireAuth, getServerSession, authenticateRequest, auth.getUser, verifyToken)",
                )
            )

    _check_json_parse_unguarded(filepath, lines, file_issues)
    if filepath.endswith(".sql"):
        _check_rls_bypass(filepath, content, lines, file_issues)
    return file_issues


def _looks_like_edge_handler(normalized_path: str, content: str) -> bool:
    """Detect edge-function style handlers without relying on index.ts naming."""
    in_edge_tree = "/functions/" in normalized_path.replace("\\", "/")
    has_edge_entrypoint = bool(
        _SERVE_ASYNC_RE.search(content) or _EDGE_ENTRYPOINT_RE.search(content)
    )
    return in_edge_tree and has_edge_entrypoint


def _extract_handler_body(content: str) -> str | None:
    """Extract body of first serve() or exported handler function."""
    match = _SERVE_ASYNC_RE.search(content) or _EDGE_ENTRYPOINT_RE.search(content)
    if not match:
        return None

    start = match.end()
    brace_pos = content.find("{", start)
    if brace_pos == -1:
        return None

    depth = 0
    for i in range(brace_pos, len(content)):
        ch = content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return content[brace_pos : i + 1]
    return None


def _handler_has_auth_check(content: str) -> bool:
    """Check if auth patterns exist inside handler body, not just file-level."""
    handler_body = _extract_handler_body(content)
    if handler_body is None:
        return _has_auth_enforcement(content)
    return _has_auth_enforcement(handler_body)


def _has_auth_enforcement(content: str) -> bool:
    """Return True when handler code actually enforces auth, not just looks it up."""
    if _AUTH_CHECK_RE.search(content):
        return True
    return bool(
        AUTH_LOOKUP_TOKEN_RE.search(content)
        and _NEGATED_AUTH_BRANCH_RE.search(content)
        and _AUTH_DENIAL_RE.search(content)
    )


def _mask_typescript_non_code(source: str) -> str:
    """Keep source offsets while blanking comments and quoted literals."""
    masked = list(source)
    i = 0
    while i < len(source):
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = len(source) if end == -1 else end
            for j in range(i, end):
                masked[j] = " "
            i = end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = len(source) if end == -1 else end + 2
            for j in range(i, end):
                if source[j] != "\n":
                    masked[j] = " "
            i = end
            continue
        if source[i] in {"'", '"', "`"}:
            quote = source[i]
            j = i + 1
            while j < len(source):
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == quote:
                    j += 1
                    break
                j += 1
            for k in range(i, min(j, len(source))):
                if source[k] != "\n":
                    masked[k] = " "
            i = j
            continue
        i += 1
    return "".join(masked)


def _matching_brace(source: str, opening: int) -> int | None:
    """Return the matching close brace for opening, if one is present."""
    depth = 0
    for i in range(opening, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _inside_function_body(source: str, start: int, target: int) -> bool:
    """Keep a try outside a nested function from guarding that function's body."""
    for match in re.finditer(r"\bfunction\b", source[start:target]):
        function_start = start + match.start()
        body_open = source.find("{", function_start, target)
        if body_open == -1:
            continue
        body_close = _matching_brace(source, body_open)
        if body_close is not None and body_open < target < body_close:
            return True

    for match in re.finditer(r"=>", source[start:target]):
        body_start = start + match.end()
        while body_start < target and source[body_start].isspace():
            body_start += 1
        if body_start > target:
            continue
        if source[body_start] == "{":
            body_close = _matching_brace(source, body_start)
            if body_close is not None and body_start < target < body_close:
                return True
            continue

        parens = brackets = braces = 0
        for i in range(body_start, target):
            char = source[i]
            if char == "(":
                parens += 1
            elif char == ")":
                if parens == 0:
                    break
                parens -= 1
            elif char == "[":
                brackets += 1
            elif char == "]":
                if brackets == 0:
                    break
                brackets -= 1
            elif char == "{":
                braces += 1
            elif char == "}":
                if braces == 0:
                    break
                braces -= 1
            elif char == ";" and parens == brackets == braces == 0:
                break
            elif char == "," and parens == brackets == braces == 0:
                break
        else:
            return True
    return False


def _is_in_try_scope(
    lines: list[str],
    target_line: int,
    target_column: int | None = None,
) -> bool:
    """Check whether a source position lies in a try body with a catch clause."""
    source = "\n".join(lines)
    line_start = sum(len(line) + 1 for line in lines[: target_line - 1])
    if target_column is None:
        target_column = len(lines[target_line - 1]) - len(lines[target_line - 1].lstrip())
    target = line_start + target_column
    code = _mask_typescript_non_code(source)

    for match in re.finditer(r"\btry\b", code[:target]):
        try_pos = match.start()
        body_open = try_pos + len(match.group())
        while body_open < len(code) and code[body_open].isspace():
            body_open += 1
        if body_open >= len(code) or code[body_open] != "{":
            continue
        body_close = _matching_brace(code, body_open)
        if body_close is None or not body_open < target < body_close:
            continue
        if _inside_function_body(code, body_open + 1, target):
            continue
        if re.match(r"\s*catch\b", code[body_close + 1 :]):
            return True
    return False


def _check_json_parse_unguarded(
    filepath: str,
    lines: list[str],
    entries: list[dict[str, object]],
) -> None:
    """Check for JSON.parse not inside a try block."""
    for line_num, line in enumerate(lines, 1):
        matches = list(_JSON_PARSE_RE.finditer(line))
        if not matches:
            continue
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        for match in matches:
            if _JSON_DEEP_CLONE_RE.match(line, match.start()):
                continue
            if _is_in_try_scope(lines, line_num, match.start()):
                continue
            entries.append(
                _make_security_entry(
                    filepath,
                    line_num,
                    line,
                    check_id="json_parse_unguarded",
                    summary="JSON.parse() without try/catch - may throw on malformed input",
                    severity="low",
                    confidence="low",
                    remediation="Wrap JSON.parse() in a try/catch block",
                )
            )


def _check_rls_bypass(
    filepath: str,
    content: str,
    lines: list[str],
    entries: list[dict[str, object]],
) -> None:
    """Check for CREATE VIEW without security_invoker in SQL files."""
    for match in _CREATE_VIEW_RE.finditer(content):
        line_num = content[: match.start()].count("\n") + 1
        view_block = content[match.start() : match.start() + 500]
        if _SECURITY_INVOKER_RE.search(view_block):
            continue
        entries.append(
            _make_security_entry(
                filepath,
                line_num,
                lines[line_num - 1] if 0 < line_num <= len(lines) else "",
                check_id="rls_bypass_views",
                summary="SQL VIEW without security_invoker=true may bypass RLS",
                severity="high",
                confidence="medium",
                remediation="Add 'WITH (security_invoker = true)' to the view definition",
            )
        )


__all__ = [
    "_check_json_parse_unguarded",
    "_check_rls_bypass",
    "_extract_handler_body",
    "_file_level_security_issues",
    "_handler_has_auth_check",
    "_is_in_try_scope",
    "_looks_like_edge_handler",
]
