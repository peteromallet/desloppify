"""Authorization and RLS signals for review context."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from desloppify.core.signal_patterns import SERVICE_ROLE_TOKEN_RE, is_server_only_path

_ROUTE_AUTH_RE = re.compile(
    r"@(?:app|router|api)\.(?:get|post|put|patch|delete|route)\b"
    r"|app\.(?:get|post|put|patch|delete)\("
    r"|export\s+(?:async\s+)?function\s+(?:GET|POST|PUT|PATCH|DELETE)\b"
    r"|@router\.(?:get|post|put|patch|delete)\b",
    re.MULTILINE,
)
_AUTH_GUARD_RE = re.compile(
    r"@(?:login_required|require_auth|auth_required|requires_auth|authenticated)\b"
    r"|\brequireAuth\b|\bwithAuth\b|\bgetServerSession\b|\bauthenticateRequest\b"
    r"|\bauth\.getUser\b|\bsupabase\.auth\.getUser\b",
)
_AUTH_USAGE_RE = re.compile(r"\buseAuth\b|\brequest\.user\b|\bsession\.user\b|\bgetUser\b")
# Table name pattern: matches unquoted, "double-quoted", `backtick`, or [bracket] names,
# optionally preceded by a schema qualifier (e.g. public.users, "auth"."profiles").
_SQL_IDENT = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|\w+)'
_SCHEMA_QUALIFIED_IDENT = rf"(?:{_SQL_IDENT}\.)?({_SQL_IDENT})"
_RLS_TABLE_RE = re.compile(
    rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_SCHEMA_QUALIFIED_IDENT}",
    re.IGNORECASE,
)
_RLS_ENABLE_RE = re.compile(
    rf"ALTER\s+TABLE\s+{_SCHEMA_QUALIFIED_IDENT}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY"
    rf"|CREATE\s+POLICY\s+{_SQL_IDENT}\s+ON\s+{_SCHEMA_QUALIFIED_IDENT}",
    re.IGNORECASE,
)
_SUPABASE_CLIENT_RE = re.compile(r"\bcreateClient\b")


def _normalize_sql_ident(raw: str) -> str:
    """Strip surrounding quotes/brackets from a SQL identifier for comparison."""
    if len(raw) >= 2:
        if (raw[0] == '"' and raw[-1] == '"') or (raw[0] == '`' and raw[-1] == '`'):
            return raw[1:-1]
        if raw[0] == '[' and raw[-1] == ']':
            return raw[1:-1]
    return raw


@dataclass(frozen=True)
class RouteAuthCoverage:
    handlers: int
    with_auth: int
    without_auth: int

    def as_dict(self) -> dict[str, int]:
        return {
            "handlers": self.handlers,
            "with_auth": self.with_auth,
            "without_auth": self.without_auth,
        }


@dataclass(frozen=True)
class AuthorizationSignals:
    """Canonical authorization-signal payload shared by review context paths."""

    route_auth_coverage: dict[str, RouteAuthCoverage] = field(default_factory=dict)
    rls_with: list[str] = field(default_factory=list)
    rls_without: list[str] = field(default_factory=list)
    rls_files: dict[str, list[str]] = field(default_factory=dict)
    service_role_usage: list[str] = field(default_factory=list)
    auth_patterns: dict[str, int] = field(default_factory=dict)
    auth_guard_patterns: dict[str, int] = field(default_factory=dict)
    auth_usage_patterns: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.route_auth_coverage:
            payload["route_auth_coverage"] = {
                path: coverage.as_dict()
                for path, coverage in sorted(self.route_auth_coverage.items())
            }
        if self.rls_with or self.rls_without:
            rls_payload: dict[str, object] = {
                "with_rls": self.rls_with,
                "without_rls": self.rls_without,
            }
            if self.rls_files:
                rls_payload["files"] = self.rls_files
            payload["rls_coverage"] = rls_payload
        if self.service_role_usage:
            payload["service_role_usage"] = self.service_role_usage
        if self.auth_patterns:
            payload["auth_patterns"] = self.auth_patterns
        if self.auth_guard_patterns:
            payload["auth_guard_patterns"] = self.auth_guard_patterns
        if self.auth_usage_patterns:
            payload["auth_usage_patterns"] = self.auth_usage_patterns
        return payload


def gather_auth_context(
    file_contents: dict[str, str],
    *,
    rel_fn: Callable[[str], str],
) -> dict[str, object]:
    """Compute auth/RLS context from file contents.

    Returns route auth coverage, RLS coverage, service role usage, and auth patterns.
    """
    route_auth: dict[str, RouteAuthCoverage] = {}
    rls_tables: set[str] = set()
    rls_enabled: set[str] = set()
    rls_table_files: dict[str, list[str]] = {}
    service_role_files: set[str] = set()
    auth_patterns: dict[str, int] = {}
    auth_guard_patterns: dict[str, int] = {}
    auth_usage_patterns: dict[str, int] = {}

    for filepath, content in file_contents.items():
        rpath = rel_fn(filepath)

        # Route auth coverage
        route_segments = _route_segments(content)
        if route_segments:
            handler_count = len(route_segments)
            auth_count = sum(1 for segment in route_segments if _AUTH_GUARD_RE.search(segment))
            route_auth[rpath] = RouteAuthCoverage(
                handlers=handler_count,
                with_auth=auth_count,
                without_auth=max(0, handler_count - auth_count),
            )

        # RLS coverage (SQL/migration files)
        for match in _RLS_TABLE_RE.finditer(content):
            table = _normalize_sql_ident(match.group(1))
            rls_tables.add(table)
            rls_table_files.setdefault(table, []).append(rpath)
        for match in _RLS_ENABLE_RE.finditer(content):
            table = match.group(1) or match.group(2)
            if table:
                rls_enabled.add(_normalize_sql_ident(table))

        # Service role usage
        if (
            SERVICE_ROLE_TOKEN_RE.search(content)
            and _SUPABASE_CLIENT_RE.search(content)
            and not is_server_only_path(filepath)
        ):
            service_role_files.add(rpath)

        # Auth check patterns
        guard_count = len(_AUTH_GUARD_RE.findall(content))
        usage_count = len(_AUTH_USAGE_RE.findall(content))
        if guard_count > 0:
            auth_guard_patterns[rpath] = guard_count
        if usage_count > 0:
            auth_usage_patterns[rpath] = usage_count
        total_auth_signals = guard_count + usage_count
        if total_auth_signals > 0:
            auth_patterns[rpath] = total_auth_signals

    tables_without_rls = rls_tables - rls_enabled
    rls_files: dict[str, list[str]] = {
        table: sorted(set(rls_table_files.get(table, [])))
        for table in sorted(tables_without_rls)
        if table in rls_table_files
    }
    return AuthorizationSignals(
        route_auth_coverage=route_auth,
        rls_with=sorted(rls_tables & rls_enabled),
        rls_without=sorted(tables_without_rls),
        rls_files=rls_files,
        service_role_usage=sorted(service_role_files),
        auth_patterns=auth_patterns,
        auth_guard_patterns=auth_guard_patterns,
        auth_usage_patterns=auth_usage_patterns,
    ).as_dict()


def _route_segments(content: str) -> list[str]:
    """Split source into route-handler scoped segments."""
    matches = list(_ROUTE_AUTH_RE.finditer(content))
    if not matches:
        return []
    segments: list[str] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        segments.append(content[start:end])
    return segments


__all__ = ["AuthorizationSignals", "RouteAuthCoverage", "gather_auth_context"]
