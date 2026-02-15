"""TypeScript-specific security detectors — eval injection, XSS, client-side secrets, etc."""

from __future__ import annotations

import re
from pathlib import Path

from ....zones import FileZoneMap, Zone

# ── Patterns ──

_SERVICE_ROLE_RE = re.compile(r"createClient\s*\(", re.IGNORECASE)
_SERVICE_ROLE_KEY_RE = re.compile(r"(?:SERVICE_ROLE|service_role)", re.IGNORECASE)

_EVAL_PATTERNS = re.compile(
    r"\b(?:eval|new\s+Function)\s*\("
)

_DANGEROUS_HTML_RE = re.compile(r"dangerouslySetInnerHTML")
_INNER_HTML_RE = re.compile(r"\.innerHTML\s*=")

_DEV_CRED_RE = re.compile(r"VITE_\w*(?:PASSWORD|SECRET|TOKEN|API_KEY|APIKEY)\b", re.IGNORECASE)

_OPEN_REDIRECT_RE = re.compile(
    r"window\.location(?:\.href)?\s*=\s*(?:data\.|response\.|params\.|query\.|\w+\[)",
)

_JSON_PARSE_RE = re.compile(r"JSON\.parse\s*\(")
_JSON_DEEP_CLONE_RE = re.compile(r"JSON\.parse\s*\(\s*JSON\.stringify\s*\(")

# Edge function auth patterns
_SERVE_ASYNC_RE = re.compile(r"serve\s*\(\s*async")
_AUTH_CHECK_RE = re.compile(
    r"(?:authenticateRequest|Authorization|auth\.getUser|supabase\.auth|verifyToken)",
    re.IGNORECASE,
)

# JWT decode without verification
_ATOB_JWT_RE = re.compile(r"atob\s*\(")
_JWT_PAYLOAD_RE = re.compile(r"(?:payload\.sub|\.split\s*\(\s*['\"]\\?\.['\"])")

# RLS bypass in SQL views
_CREATE_VIEW_RE = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b", re.IGNORECASE)
_SECURITY_INVOKER_RE = re.compile(r"security_invoker\s*=\s*true", re.IGNORECASE)


def detect_ts_security(
    files: list[str],
    zone_map: FileZoneMap | None,
) -> tuple[list[dict], int]:
    """Detect TypeScript-specific security issues.

    Returns (entries, files_scanned).
    """
    from ....detectors.security import make_security_entry

    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if zone_map is not None:
            zone = zone_map.get(filepath)
            if zone in (Zone.GENERATED, Zone.VENDOR):
                continue

        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError:
            continue

        scanned += 1
        lines = content.splitlines()
        is_src = "/src/" in filepath or filepath.startswith("src/")

        for line_num, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue

            # Check 1: Service role key used in client-side code
            if is_src and _SERVICE_ROLE_RE.search(line):
                # Check surrounding lines for SERVICE_ROLE
                context = "\n".join(lines[max(0, line_num - 3):min(len(lines), line_num + 3)])
                if _SERVICE_ROLE_KEY_RE.search(context):
                    entries.append(make_security_entry(
                        filepath, line_num, "service_role_on_client",
                        "Supabase service role key used in client code",
                        "critical", "high", line,
                        "Never use SERVICE_ROLE key in client-side code — use anon key and RLS instead",
                    ))

            # Check 2: eval() / new Function()
            if _EVAL_PATTERNS.search(line):
                entries.append(make_security_entry(
                    filepath, line_num, "eval_injection",
                    "eval() or new Function() — potential code injection",
                    "critical", "high", line,
                    "Avoid eval/new Function — use safer alternatives (JSON.parse, Map, etc.)",
                ))

            # Check 3: dangerouslySetInnerHTML
            if _DANGEROUS_HTML_RE.search(line):
                entries.append(make_security_entry(
                    filepath, line_num, "dangerously_set_inner_html",
                    "dangerouslySetInnerHTML — XSS risk if data is untrusted",
                    "high", "medium", line,
                    "Sanitize HTML with DOMPurify before using dangerouslySetInnerHTML",
                ))

            # Check 4: .innerHTML assignment
            if _INNER_HTML_RE.search(line):
                entries.append(make_security_entry(
                    filepath, line_num, "innerHTML_assignment",
                    "Direct .innerHTML assignment — XSS risk",
                    "high", "medium", line,
                    "Use textContent for text or sanitize HTML with DOMPurify",
                ))

            # Check 5: VITE_ env vars with sensitive names
            # Skip in dev-only files (path contains /dev/ or file has dev-env guard)
            if _DEV_CRED_RE.search(line):
                is_dev_file = "/dev/" in filepath or "dev." in Path(filepath).name
                has_dev_guard = "__IS_DEV_ENV__" in content or "isDev" in content
                if not (is_dev_file and has_dev_guard):
                    entries.append(make_security_entry(
                        filepath, line_num, "dev_credentials_env",
                        "Sensitive credential exposed via VITE_ environment variable",
                        "medium", "medium", line,
                        "Sensitive credentials should never be in client-accessible VITE_ env vars",
                    ))

            # Check 6: Open redirect
            if _OPEN_REDIRECT_RE.search(line):
                entries.append(make_security_entry(
                    filepath, line_num, "open_redirect",
                    "Potential open redirect: user-controlled data assigned to window.location",
                    "medium", "medium", line,
                    "Validate redirect URLs against an allowlist before redirecting",
                ))

            # Check 7: Unverified JWT decode
            if _ATOB_JWT_RE.search(line):
                context = "\n".join(lines[max(0, line_num - 3):min(len(lines), line_num + 3)])
                if _JWT_PAYLOAD_RE.search(context):
                    entries.append(make_security_entry(
                        filepath, line_num, "unverified_jwt_decode",
                        "JWT decoded with atob() without signature verification",
                        "critical", "high", line,
                        "Use auth.getUser() or a JWT library that verifies signatures",
                    ))

        # File-level checks

        # Check 8: Edge function missing auth
        basename = Path(filepath).name
        if basename == "index.ts" and "/functions/" in filepath:
            if _SERVE_ASYNC_RE.search(content) and not _AUTH_CHECK_RE.search(content):
                entries.append(make_security_entry(
                    filepath, 1, "edge_function_missing_auth",
                    "Edge function serves requests without authentication check",
                    "high", "medium", content.splitlines()[0] if lines else "",
                    "Add authentication check (e.g., authenticateRequest, auth.getUser)",
                ))

        # Check 9: JSON.parse without try/catch
        _check_json_parse_unguarded(filepath, lines, entries)

        # Check 10: RLS bypass in SQL views
        if filepath.endswith(".sql"):
            _check_rls_bypass(filepath, lines, entries)

    return entries, scanned


def _is_in_try_scope(lines: list[str], target_line: int) -> bool:
    """Check if target_line (1-indexed) is inside a try block by scanning backwards.

    Tracks brace depth going upward. If we reach a `try` keyword when depth <= 0,
    the target is inside a try block. Stops if we encounter a function/arrow boundary
    (conservative: inner functions reset scope).
    """
    depth = 0
    for i in range(target_line - 2, -1, -1):  # 0-indexed, go backwards
        stripped = lines[i].strip()
        # Stop at function boundaries — inner functions are not guarded by outer try
        if re.match(r"(?:async\s+)?function\b", stripped) or '=>' in stripped:
            return False
        depth += stripped.count('}') - stripped.count('{')
        if depth <= 0 and re.search(r'\btry\b', stripped):
            return True
    return False


def _check_json_parse_unguarded(
    filepath: str, lines: list[str], entries: list[dict]
) -> None:
    """Check for JSON.parse not inside a try block."""
    from ....detectors.security import make_security_entry

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
        entries.append(make_security_entry(
            filepath, line_num, "json_parse_unguarded",
            "JSON.parse() without try/catch — may throw on malformed input",
            "low", "low", line,
            "Wrap JSON.parse() in a try/catch block",
        ))


def _check_rls_bypass(
    filepath: str, lines: list[str], entries: list[dict]
) -> None:
    """Check for CREATE VIEW without security_invoker in SQL files."""
    from ....detectors.security import make_security_entry

    content = "\n".join(lines)
    for m in _CREATE_VIEW_RE.finditer(content):
        # Find the line number
        line_num = content[:m.start()].count("\n") + 1
        # Check if security_invoker is set in the view definition (next ~20 lines)
        view_block = content[m.start():m.start() + 500]
        if not _SECURITY_INVOKER_RE.search(view_block):
            entries.append(make_security_entry(
                filepath, line_num, "rls_bypass_views",
                "SQL VIEW without security_invoker=true may bypass RLS",
                "high", "medium",
                lines[line_num - 1] if 0 < line_num <= len(lines) else "",
                "Add 'WITH (security_invoker = true)' to the view definition",
            ))
