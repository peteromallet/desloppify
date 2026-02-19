"""TypeScript-specific security detectors — eval injection, XSS, client-side secrets, etc."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.core.signal_patterns import SERVICE_ROLE_TOKEN_RE, is_server_only_path
from desloppify.engine.detectors.security import rules as security_detector_mod
from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages.typescript.detectors.contracts import DetectorResult

# ── Patterns ──

_CREATE_CLIENT_RE = re.compile(r"\bcreateClient\s*\(", re.IGNORECASE)

_EVAL_PATTERNS = re.compile(r"\b(?:eval|new\s+Function)\s*\(")

_DANGEROUS_HTML_RE = re.compile(r"dangerouslySetInnerHTML")
_INNER_HTML_RE = re.compile(r"\.innerHTML\s*=")

_DEV_CRED_RE = re.compile(
    r"VITE_\w*(?:PASSWORD|SECRET|TOKEN|API_KEY|APIKEY)\b", re.IGNORECASE
)

_OPEN_REDIRECT_RE = re.compile(
    r"window\.location(?:\.href)?\s*=\s*(?:data\.|response\.|params\.|query\.|\w+\[)",
)

_JSON_PARSE_RE = re.compile(r"JSON\.parse\s*\(")
_JSON_DEEP_CLONE_RE = re.compile(r"JSON\.parse\s*\(\s*JSON\.stringify\s*\(")

# Edge function auth patterns
_SERVE_ASYNC_RE = re.compile(r"\b(?:Deno\.)?serve\s*\(\s*(?:async\s*)?")
_EDGE_ENTRYPOINT_RE = re.compile(
    r"\bexport\s+(?:default\s+)?(?:async\s+)?function\s+(?:GET|POST|PUT|PATCH|DELETE)\b"
)
_AUTH_CHECK_RE = re.compile(
    r"(?:authenticateRequest|auth\.getUser|supabase\.auth(?:\.getUser)?|verifyToken)",
    re.IGNORECASE,
)

# JWT decode without verification
_ATOB_JWT_RE = re.compile(r"atob\s*\(")
_JWT_PAYLOAD_RE = re.compile(r"(?:payload\.sub|\.split\s*\(\s*['\"]\\?\.['\"])")

# RLS bypass in SQL views
_CREATE_VIEW_RE = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b", re.IGNORECASE)
_SECURITY_INVOKER_RE = re.compile(r"security_invoker\s*=\s*true", re.IGNORECASE)
logger = logging.getLogger(__name__)


def _make_security_entry(
    filepath: str,
    line_num: int,
    line: str,
    *,
    check_id: str,
    summary: str,
    severity: str,
    confidence: str,
    remediation: str,
) -> dict:
    return security_detector_mod.make_security_entry(
        filepath,
        line_num,
        line,
        security_detector_mod.SecurityRule(
            check_id=check_id,
            summary=summary,
            severity=severity,
            confidence=confidence,
            remediation=remediation,
        ),
    )


def detect_ts_security(
    files: list[str],
    zone_map: FileZoneMap | None,
) -> tuple[list[dict], int]:
    """Detect TypeScript-specific security issues.

    Returns (entries, files_scanned).
    """
    return detect_ts_security_result(files, zone_map).as_tuple()


def detect_ts_security_result(
    files: list[str],
    zone_map: FileZoneMap | None,
) -> DetectorResult[dict]:
    """Detect TypeScript-specific security issues with explicit result contract."""
    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if zone_map is not None:
            zone = zone_map.get(filepath)
            if zone in (Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR):
                continue

        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            log_best_effort_failure(
                logger, f"read TypeScript security source {filepath}", exc
            )
            continue

        scanned += 1
        normalized_path = filepath.replace("\\", "/")
        is_server_only = is_server_only_path(normalized_path)
        lines = content.splitlines()
        has_dev_guard = "__IS_DEV_ENV__" in content or "isDev" in content

        for line_num, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            entries.extend(
                _line_security_findings(
                    filepath=filepath,
                    normalized_path=normalized_path,
                    lines=lines,
                    line_num=line_num,
                    line=line,
                    is_server_only=is_server_only,
                    has_dev_guard=has_dev_guard,
                )
            )

        entries.extend(
            _file_level_security_findings(
                filepath=filepath,
                normalized_path=normalized_path,
                lines=lines,
                content=content,
            )
        )

    return DetectorResult(entries=entries, population_kind="files", population_size=scanned)


def _line_security_findings(
    *,
    filepath: str,
    normalized_path: str,
    lines: list[str],
    line_num: int,
    line: str,
    is_server_only: bool,
    has_dev_guard: bool,
) -> list[dict]:
    """Detect per-line security patterns and return findings."""
    line_findings: list[dict] = []

    if _CREATE_CLIENT_RE.search(line):
        context = "\n".join(lines[max(0, line_num - 3) : min(len(lines), line_num + 3)])
        if SERVICE_ROLE_TOKEN_RE.search(context) and not is_server_only:
            line_findings.append(
                _make_security_entry(
                    filepath,
                    line_num,
                    line,
                    check_id="service_role_on_client",
                    summary="Supabase service role key used in client code",
                    severity="critical",
                    confidence="high",
                    remediation="Never use SERVICE_ROLE key outside server-only code — use anon key + RLS on clients",
                )
            )

    if _EVAL_PATTERNS.search(line):
        line_findings.append(
            _make_security_entry(
                filepath,
                line_num,
                line,
                check_id="eval_injection",
                summary="eval() or new Function() — potential code injection",
                severity="critical",
                confidence="high",
                remediation="Avoid eval/new Function — use safer alternatives (JSON.parse, Map, etc.)",
            )
        )

    if _DANGEROUS_HTML_RE.search(line):
        line_findings.append(
            _make_security_entry(
                filepath,
                line_num,
                line,
                check_id="dangerously_set_inner_html",
                summary="dangerouslySetInnerHTML — XSS risk if data is untrusted",
                severity="high",
                confidence="medium",
                remediation="Sanitize HTML with DOMPurify before using dangerouslySetInnerHTML",
            )
        )

    if _INNER_HTML_RE.search(line):
        line_findings.append(
            _make_security_entry(
                filepath,
                line_num,
                line,
                check_id="innerHTML_assignment",
                summary="Direct .innerHTML assignment — XSS risk",
                severity="high",
                confidence="medium",
                remediation="Use textContent for text or sanitize HTML with DOMPurify",
            )
        )

    if _DEV_CRED_RE.search(line):
        is_dev_file = "/dev/" in normalized_path or "dev." in Path(filepath).name
        if not (is_dev_file and has_dev_guard):
            line_findings.append(
                _make_security_entry(
                    filepath,
                    line_num,
                    line,
                    check_id="dev_credentials_env",
                    summary="Sensitive credential exposed via VITE_ environment variable",
                    severity="medium",
                    confidence="medium",
                    remediation="Sensitive credentials should never be in client-accessible VITE_ env vars",
                )
            )

    if _OPEN_REDIRECT_RE.search(line):
        line_findings.append(
            _make_security_entry(
                filepath,
                line_num,
                line,
                check_id="open_redirect",
                summary="Potential open redirect: user-controlled data assigned to window.location",
                severity="medium",
                confidence="medium",
                remediation="Validate redirect URLs against an allowlist before redirecting",
            )
        )

    if _ATOB_JWT_RE.search(line):
        context = "\n".join(lines[max(0, line_num - 3) : min(len(lines), line_num + 3)])
        if _JWT_PAYLOAD_RE.search(context):
            line_findings.append(
                _make_security_entry(
                    filepath,
                    line_num,
                    line,
                    check_id="unverified_jwt_decode",
                    summary="JWT decoded with atob() without signature verification",
                    severity="critical",
                    confidence="high",
                    remediation="Use auth.getUser() or a JWT library that verifies signatures",
                )
            )

    return line_findings


def _file_level_security_findings(
    *,
    filepath: str,
    normalized_path: str,
    lines: list[str],
    content: str,
) -> list[dict]:
    """Detect file-level security patterns and return findings."""
    file_findings: list[dict] = []

    if _looks_like_edge_handler(normalized_path, content):
        if not _AUTH_CHECK_RE.search(content):
            file_findings.append(
                _make_security_entry(
                    filepath,
                    1,
                    content.splitlines()[0] if lines else "",
                    check_id="edge_function_missing_auth",
                    summary="Edge function serves requests without authentication check",
                    severity="high",
                    confidence="medium",
                    remediation="Add authentication check (e.g., authenticateRequest, auth.getUser)",
                )
            )

    _check_json_parse_unguarded(filepath, lines, file_findings)
    if filepath.endswith(".sql"):
        _check_rls_bypass(filepath, content, lines, file_findings)
    return file_findings


def _looks_like_edge_handler(normalized_path: str, content: str) -> bool:
    """Detect edge-function style handlers without relying on index.ts naming."""
    in_edge_tree = "/functions/" in normalized_path.replace("\\", "/")
    has_edge_entrypoint = bool(_SERVE_ASYNC_RE.search(content) or _EDGE_ENTRYPOINT_RE.search(content))
    return in_edge_tree and has_edge_entrypoint


def _is_in_try_scope(lines: list[str], target_line: int) -> bool:
    """Check if target_line (1-indexed) is inside a try block by scanning backwards.

    Tracks brace depth going upward. If we reach a `try` keyword when depth <= 0,
    the target is inside a try block. Stops if we encounter a function/arrow boundary
    (conservative: inner functions reset scope).
    """
    depth = 0
    for i in range(target_line - 2, -1, -1):  # 0-indexed, go backwards
        stripped = lines[i].strip()
        # Stop at named function boundaries — inner functions are not guarded by outer try.
        # Arrow functions (=>) are NOT a boundary: they may appear inside a try block.
        if re.match(r"(?:async\s+)?function\b", stripped):
            return False
        depth += stripped.count("}") - stripped.count("{")
        if depth <= 0 and re.search(r"\btry\b", stripped):
            return True
    return False


def _check_json_parse_unguarded(
    filepath: str, lines: list[str], entries: list[dict]
) -> None:
    """Check for JSON.parse not inside a try block."""
    for line_num, line in enumerate(lines, 1):
        if not _JSON_PARSE_RE.search(line):
            continue
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        # Skip JSON.parse(JSON.stringify(...)) — safe deep-clone idiom
        if _JSON_DEEP_CLONE_RE.search(line):
            continue
        if _is_in_try_scope(lines, line_num):
            continue
        entries.append(
            _make_security_entry(
                filepath,
                line_num,
                line,
                check_id="json_parse_unguarded",
                summary="JSON.parse() without try/catch — may throw on malformed input",
                severity="low",
                confidence="low",
                remediation="Wrap JSON.parse() in a try/catch block",
            )
        )


def _check_rls_bypass(filepath: str, content: str, lines: list[str], entries: list[dict]) -> None:
    """Check for CREATE VIEW without security_invoker in SQL files."""
    for m in _CREATE_VIEW_RE.finditer(content):
        # Find the line number
        line_num = content[: m.start()].count("\n") + 1
        # Check if security_invoker is set in the view definition (next ~20 lines)
        view_block = content[m.start() : m.start() + 500]
        if not _SECURITY_INVOKER_RE.search(view_block):
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
