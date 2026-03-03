"""Go-specific security detectors."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.engine.detectors.security import rules as security_detector_mod
from desloppify.engine.policy.zones import FileZoneMap, Zone

logger = logging.getLogger(__name__)

# ── Patterns ──

_UNSAFE_POINTER_RE = re.compile(r"\bunsafe\.Pointer\b")

# SQL injection: string concat in Query/Exec calls
_SQL_CONCAT_RE = re.compile(
    r"\b(?:Query|QueryRow|Exec|ExecContext|QueryContext)\s*\("
    r"[^)]*(?:fmt\.Sprintf|\"[^\"]*\"\s*\+|\+\s*\")"
)

# Also catch simpler pattern: db.Query("SELECT * FROM " + var)
_SQL_CONCAT_SIMPLE_RE = re.compile(
    r"\b(?:Query|QueryRow|Exec)\s*\(\s*\"[^\"]*\"\s*\+"
)

# Weak crypto
_WEAK_HASH_USE_RE = re.compile(r"\b(?:md5|sha1)\.(?:New|Sum)")

# Insecure random for crypto
_MATH_RAND_IMPORT_RE = re.compile(r'"math/rand"')
_CRYPTO_CONTEXT_RE = re.compile(
    r"(?:token|secret|password|key|nonce|salt|cipher|crypt|auth)", re.IGNORECASE
)

# HTTP without TLS
_HTTP_LISTEN_RE = re.compile(r"\bhttp\.ListenAndServe\s*\(")

# Command injection
_EXEC_COMMAND_VAR_RE = re.compile(r"\bexec\.Command\s*\(\s*[a-zA-Z_]\w*")

# Hardcoded credentials
_HARDCODED_CRED_RE = re.compile(
    r'(?:password|passwd|secret|token|api_?key)\s*(?::=|=)\s*"[^"]{8,}"',
    re.IGNORECASE,
)

# InsecureSkipVerify disables TLS certificate verification
_INSECURE_SKIP_VERIFY_RE = re.compile(r"InsecureSkipVerify\s*:\s*true")


def _make_entry(filepath, line_num, line, *, check_id, summary, severity, confidence, remediation):
    return security_detector_mod.make_security_entry(
        filepath, line_num, line,
        security_detector_mod.SecurityRule(
            check_id=check_id, summary=summary,
            severity=severity, confidence=confidence,
            remediation=remediation,
        ),
    )


def detect_go_security(
    files: list[str],
    zone_map: FileZoneMap | None,
) -> tuple[list[dict], int]:
    """Detect Go-specific security issues."""
    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if zone_map is not None:
            zone = zone_map.get(filepath)
            if zone in (Zone.TEST, Zone.VENDOR, Zone.GENERATED, Zone.CONFIG):
                continue

        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            log_best_effort_failure(logger, f"read Go security source {filepath}", exc)
            continue

        scanned += 1
        lines = content.splitlines()

        for line_num, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue

            # Unsafe pointer
            if _UNSAFE_POINTER_RE.search(line):
                entries.append(_make_entry(
                    filepath, line_num, line,
                    check_id="unsafe_pointer",
                    summary="unsafe.Pointer usage — bypasses Go type safety",
                    severity="high", confidence="medium",
                    remediation="Avoid unsafe.Pointer unless absolutely necessary; document why",
                ))

            # SQL injection via string concatenation
            if _SQL_CONCAT_RE.search(line) or _SQL_CONCAT_SIMPLE_RE.search(line):
                entries.append(_make_entry(
                    filepath, line_num, line,
                    check_id="sql_injection",
                    summary="SQL query built with string concatenation — verify values are parameterized",
                    severity="critical", confidence="medium",
                    remediation="Use db.Query(\"SELECT ... WHERE id = $1\", id) with placeholders; if only table/column names are interpolated, add a // SECURITY: comment explaining why",
                ))

            # Weak hash usage
            if _WEAK_HASH_USE_RE.search(line):
                entries.append(_make_entry(
                    filepath, line_num, line,
                    check_id="weak_hash",
                    summary="Weak hash function (MD5/SHA1) — use SHA-256 or stronger",
                    severity="medium", confidence="high",
                    remediation="Replace with crypto/sha256 or crypto/sha512",
                ))

            # HTTP without TLS
            if _HTTP_LISTEN_RE.search(line):
                entries.append(_make_entry(
                    filepath, line_num, line,
                    check_id="http_no_tls",
                    summary="http.ListenAndServe without TLS — use ListenAndServeTLS",
                    severity="medium", confidence="medium",
                    remediation="Use http.ListenAndServeTLS() or put behind a TLS-terminating proxy",
                ))

            # Command injection
            if _EXEC_COMMAND_VAR_RE.search(line):
                # Check if the argument is a variable (not a string literal)
                if not re.search(r'exec\.Command\s*\(\s*"', line):
                    entries.append(_make_entry(
                        filepath, line_num, line,
                        check_id="command_injection",
                        summary="exec.Command with variable argument — potential command injection",
                        severity="high", confidence="medium",
                        remediation="Validate and sanitize command arguments; prefer allowlisted commands",
                    ))

            # Hardcoded credentials
            if _HARDCODED_CRED_RE.search(line):
                entries.append(_make_entry(
                    filepath, line_num, line,
                    check_id="hardcoded_credentials",
                    summary="Hardcoded credential detected",
                    severity="high", confidence="medium",
                    remediation="Use environment variables or a secrets manager",
                ))

            # InsecureSkipVerify disables TLS cert verification
            if _INSECURE_SKIP_VERIFY_RE.search(line):
                entries.append(_make_entry(
                    filepath, line_num, line,
                    check_id="insecure_tls",
                    summary="InsecureSkipVerify disables TLS certificate verification",
                    severity="high", confidence="high",
                    remediation="Remove InsecureSkipVerify or use a proper CA certificate",
                ))

        # File-level: check for math/rand in security context
        if _MATH_RAND_IMPORT_RE.search(content) and _CRYPTO_CONTEXT_RE.search(content):
            # Find the import line
            for i, line in enumerate(lines, 1):
                if _MATH_RAND_IMPORT_RE.search(line):
                    entries.append(_make_entry(
                        filepath, i, line,
                        check_id="insecure_random",
                        summary="math/rand used in file with crypto context — use crypto/rand",
                        severity="medium", confidence="medium",
                        remediation="Use crypto/rand for security-sensitive random number generation",
                    ))
                    break

    return entries, scanned
