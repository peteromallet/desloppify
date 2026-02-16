"""Cross-language security detector — hardcoded secrets, weak crypto, sensitive logging.

Contains generic checks shared by all language plugins. Additional language-
specific checks live under ``lang/<name>/detectors/security.py``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..zones import FileZoneMap, Zone

LOGGER = logging.getLogger(__name__)

# ── Secret format patterns (high-confidence format-based detection) ──

_SECRET_FORMAT_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}"),
     "critical", "Rotate the AWS key immediately and use IAM roles or environment variables"),
    ("GitHub token", re.compile(r"gh[ps]_[A-Za-z0-9_]{36,}"),
     "critical", "Revoke the token and use environment variables or GitHub Actions secrets"),
    ("Private key block", re.compile(r"-----BEGIN\s+(?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
     "critical", "Remove the private key from source and store in a secrets manager"),
    ("Stripe key", re.compile(r"[sr]k_(?:live|test)_[0-9a-zA-Z]{20,}"),
     "high", "Move Stripe keys to environment variables"),
    ("Slack token", re.compile(r"xox[bpas]-[0-9a-zA-Z-]+"),
     "high", "Revoke the Slack token and use environment variables"),
    ("JWT token", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),
     "medium", "Do not hardcode JWTs — generate them at runtime"),
    ("Database connection string with password",
     re.compile(r"(?:postgres|mysql|mongodb|redis)://\w+:[^@\s]{3,}@"),
     "critical", "Move database credentials to environment variables"),
]

# ── Secret variable name patterns ──

_SECRET_NAME_RE = re.compile(
    r"""(?:^|[\s,;(])          # start of line or delimiter
    (?:const|let|var|export)?  # optional JS/TS keyword
    \s*
    ([A-Za-z_]\w*)             # variable name (captured)
    \s*[:=]\s*                 # assignment
    (['"`])                    # opening quote
    (.+?)                      # value (captured)
    \2                         # closing quote
    """,
    re.VERBOSE,
)

_SECRET_NAMES = re.compile(
    r"(?i)(?:password|passwd|secret|api_key|apikey|token|credentials|"
    r"auth_token|private_key|access_key|client_secret|secret_key)",
)

_PLACEHOLDER_VALUES = {
    "", "changeme", "xxx", "yyy", "zzz", "placeholder", "test",
    "example", "dummy", "none", "null", "undefined", "todo", "fixme",
}

_PLACEHOLDER_PREFIXES = ("your-", "your_", "<", "${", "{{")

# ── Environment lookup patterns (not hardcoded) ──

_ENV_LOOKUPS = (
    "os.environ", "os.getenv", "process.env.", "import.meta.env",
    "os.environ.get(", "os.environ[",
)

# ── Insecure random usage near security contexts ──

_RANDOM_CALLS = re.compile(r"(?:Math\.random|random\.random|random\.randint)\s*\(")
_SECURITY_CONTEXT_WORDS = re.compile(
    r"(?i)(?:token|key|nonce|session|salt|secret|password|otp|csrf|auth)",
)

# ── Weak crypto / TLS patterns ──

_WEAK_CRYPTO_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"verify\s*=\s*False"), "TLS verification disabled",
     "high", "Never disable TLS verification — use proper certificates"),
    (re.compile(r"ssl\._create_unverified_context\s*\("), "Unverified SSL context",
     "high", "Use ssl.create_default_context() instead"),
    (re.compile(r"rejectUnauthorized\s*:\s*false"), "TLS rejection disabled",
     "high", "Never disable TLS certificate validation"),
    (re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]0['\"]"),
     "TLS rejection disabled via env",
     "high", "Never disable TLS certificate validation"),
]

# ── Sensitive data in logs ──

_LOG_CALLS = re.compile(
    r"(?:console\.(?:log|warn|error|info|debug)|"
    r"log(?:ger)?\.(?:info|debug|warning|error|critical)|"
    r"logging\.(?:info|debug|warning|error|critical)|"
    r"\bprint)\s*\(",
)

_SENSITIVE_IN_LOG = re.compile(
    r"(?i)(?:password|token|secret|api_key|apikey|credentials|"
    r"private_key|access_key|authorization)",
)


def _is_comment_line(line: str) -> bool:
    """Quick check if a line is likely a comment."""
    stripped = line.lstrip()
    if stripped.startswith("//") or stripped.startswith("#"):
        return True
    if stripped.startswith("*") or stripped.startswith("/*"):
        return True
    return False


def _is_env_lookup(line: str) -> bool:
    """Check if a line contains an environment variable lookup."""
    return any(lookup in line for lookup in _ENV_LOOKUPS)


def _is_placeholder(value: str) -> bool:
    """Check if a value is a placeholder, not a real secret."""
    lower = value.lower().strip()
    if lower in _PLACEHOLDER_VALUES:
        return True
    if any(lower.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        return True
    if len(value) < 8:
        return True
    return False


def _detect_secret_format_findings(filepath: str, line_num: int, line: str, is_test: bool) -> list[dict]:
    findings: list[dict] = []
    for label, pattern, severity, remediation in _SECRET_FORMAT_PATTERNS:
        if not pattern.search(line):
            continue
        findings.append(
            make_security_entry(
                filepath,
                line_num,
                "hardcoded_secret_value",
                f"Hardcoded {label} detected",
                confidence="medium" if is_test else "high",
                detail=_security_detail(
                    check_id="hardcoded_secret_value",
                    severity=severity,
                    line=line_num,
                    content=line,
                    remediation=remediation,
                ),
            )
        )
    return findings


def _detect_secret_name_findings(filepath: str, line_num: int, line: str, is_test: bool) -> list[dict]:
    findings: list[dict] = []
    for match in _SECRET_NAME_RE.finditer(line):
        var_name = match.group(1)
        value = match.group(3)
        if not _SECRET_NAMES.search(var_name):
            continue
        if _is_env_lookup(line) or _is_placeholder(value):
            continue
        findings.append(
            make_security_entry(
                filepath,
                line_num,
                "hardcoded_secret_name",
                f"Hardcoded secret in variable '{var_name}'",
                confidence="medium" if is_test else "high",
                detail=_security_detail(
                    check_id="hardcoded_secret_name",
                    severity="high",
                    line=line_num,
                    content=line,
                    remediation="Move secret to environment variable or secrets manager",
                ),
            )
        )
    return findings


def _detect_insecure_random_findings(filepath: str, line_num: int, line: str) -> list[dict]:
    if not (_RANDOM_CALLS.search(line) and _SECURITY_CONTEXT_WORDS.search(line)):
        return []
    return [
        make_security_entry(
            filepath,
            line_num,
            "insecure_random",
            "Insecure random used in security context",
            confidence="medium",
            detail=_security_detail(
                check_id="insecure_random",
                severity="medium",
                line=line_num,
                content=line,
                remediation="Use secrets.token_hex() (Python) or crypto.randomUUID() (JS)",
            ),
        )
    ]


def _detect_weak_crypto_findings(filepath: str, line_num: int, line: str) -> list[dict]:
    findings: list[dict] = []
    for pattern, label, severity, remediation in _WEAK_CRYPTO_PATTERNS:
        if not pattern.search(line):
            continue
        findings.append(
            make_security_entry(
                filepath,
                line_num,
                "weak_crypto_tls",
                label,
                confidence="high",
                detail=_security_detail(
                    check_id="weak_crypto_tls",
                    severity=severity,
                    line=line_num,
                    content=line,
                    remediation=remediation,
                ),
            )
        )
    return findings


def _detect_sensitive_log_findings(filepath: str, line_num: int, line: str) -> list[dict]:
    if not (_LOG_CALLS.search(line) and _SENSITIVE_IN_LOG.search(line)):
        return []
    return [
        make_security_entry(
            filepath,
            line_num,
            "log_sensitive",
            "Sensitive data may be logged",
            confidence="medium",
            detail=_security_detail(
                check_id="log_sensitive",
                severity="medium",
                line=line_num,
                content=line,
                remediation="Remove sensitive data from log statements",
            ),
        )
    ]


def _scan_line_for_security_findings(filepath: str, line_num: int, line: str, is_test: bool) -> list[dict]:
    findings: list[dict] = []
    findings.extend(_detect_secret_format_findings(filepath, line_num, line, is_test))
    findings.extend(_detect_secret_name_findings(filepath, line_num, line, is_test))
    findings.extend(_detect_insecure_random_findings(filepath, line_num, line))
    findings.extend(_detect_weak_crypto_findings(filepath, line_num, line))
    findings.extend(_detect_sensitive_log_findings(filepath, line_num, line))
    return findings


def _security_detail(*, check_id: str, severity: str, line: int, content: str, remediation: str) -> dict[str, Any]:
    return {
        "kind": check_id,
        "severity": severity,
        "line": line,
        "content": content[:200],
        "remediation": remediation,
    }


def detect_security_issues(
    files: list[str],
    zone_map: FileZoneMap | None,
    lang_name: str,
) -> tuple[list[dict], int]:
    """Detect cross-language security issues in source files.

    Returns (entries, potential) where potential = number of files scanned.
    """
    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if zone_map is not None and zone_map.get(filepath) in (Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR):
            continue
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError as exc:
            LOGGER.debug("Skipping unreadable file during security scan: %s", filepath, exc_info=exc)
            continue

        scanned += 1
        lines = content.splitlines()
        is_test = zone_map is not None and zone_map.get(filepath) == Zone.TEST

        for line_num, line in enumerate(lines, 1):
            if _is_comment_line(line) and not any(pattern.search(line) for _, pattern, _, _ in _SECRET_FORMAT_PATTERNS):
                continue
            entries.extend(_scan_line_for_security_findings(filepath, line_num, line, is_test))

    return entries, scanned


def make_security_entry(
    filepath: str,
    line: int,
    check_id: str,
    summary: str,
    *legacy_fields,
    confidence: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a security finding entry dict.

    Supports both call shapes:
    - modern: make_security_entry(..., confidence=..., detail={...})
    - legacy: make_security_entry(..., severity, confidence, content, remediation)
    """
    from ..utils import rel

    if detail is None:
        if len(legacy_fields) != 4:
            raise TypeError(
                "make_security_entry() expected 4 legacy fields "
                "(severity, confidence, content, remediation) when detail is omitted."
            )
        severity, legacy_confidence, content, remediation = legacy_fields
        detail = _security_detail(
            check_id=check_id,
            severity=str(severity),
            line=line,
            content=str(content),
            remediation=str(remediation),
        )
        confidence = str(legacy_confidence)

    if confidence is None:
        raise TypeError("make_security_entry() missing required keyword argument: 'confidence'")

    rel_path = rel(filepath)
    return {
        "file": filepath,
        "name": f"security::{check_id}::{rel_path}::{line}",
        "tier": 2,
        "confidence": confidence,
        "summary": summary,
        "detail": detail,
    }
