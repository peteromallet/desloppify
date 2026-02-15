"""Cross-language security detector — hardcoded secrets, weak crypto, sensitive logging.

Checks that apply to both Python and TypeScript codebases. Language-specific
checks live in lang/{python,typescript}/detectors/security.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..zones import FileZoneMap, Zone

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
        # Skip generated/vendor zones
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
        is_test = zone_map is not None and zone_map.get(filepath) == Zone.TEST

        for line_num, line in enumerate(lines, 1):
            if _is_comment_line(line) and not any(
                pat.search(line) for _, pat, _, _ in _SECRET_FORMAT_PATTERNS
            ):
                continue

            # Check 1: Secret format patterns
            for label, pattern, severity, remediation in _SECRET_FORMAT_PATTERNS:
                m = pattern.search(line)
                if m:
                    entries.append(make_security_entry(
                        filepath, line_num, "hardcoded_secret_value",
                        f"Hardcoded {label} detected",
                        severity, "medium" if is_test else "high",
                        line, remediation,
                    ))

            # Check 2: Secret variable name + literal value
            for m in _SECRET_NAME_RE.finditer(line):
                var_name = m.group(1)
                value = m.group(3)
                if not _SECRET_NAMES.search(var_name):
                    continue
                if _is_env_lookup(line):
                    continue
                if _is_placeholder(value):
                    continue
                entries.append(make_security_entry(
                    filepath, line_num, "hardcoded_secret_name",
                    f"Hardcoded secret in variable '{var_name}'",
                    "high", "medium" if is_test else "high",
                    line, "Move secret to environment variable or secrets manager",
                ))

            # Check 3: Insecure random near security context
            if _RANDOM_CALLS.search(line):
                # Only flag if the random value is ASSIGNED to a security-named variable
                # (same line only — avoids matching UI session IDs near "session" in context)
                if _SECURITY_CONTEXT_WORDS.search(line):
                    entries.append(make_security_entry(
                        filepath, line_num, "insecure_random",
                        "Insecure random used in security context",
                        "medium", "medium",
                        line, "Use secrets.token_hex() (Python) or crypto.randomUUID() (JS)",
                    ))

            # Check 4: Weak crypto / TLS
            for pattern, label, severity, remediation in _WEAK_CRYPTO_PATTERNS:
                if pattern.search(line):
                    entries.append(make_security_entry(
                        filepath, line_num, "weak_crypto_tls",
                        label, severity, "high",
                        line, remediation,
                    ))

            # Check 5: Sensitive data in logs
            if _LOG_CALLS.search(line) and _SENSITIVE_IN_LOG.search(line):
                entries.append(make_security_entry(
                    filepath, line_num, "log_sensitive",
                    "Sensitive data may be logged",
                    "medium", "medium",
                    line, "Remove sensitive data from log statements",
                ))

    return entries, scanned


def make_security_entry(
    filepath: str, line: int, check_id: str,
    summary: str, severity: str, confidence: str,
    content: str, remediation: str,
) -> dict:
    """Build a security finding entry dict."""
    from ..utils import rel
    rel_path = rel(filepath)
    return {
        "file": filepath,
        "name": f"security::{check_id}::{rel_path}::{line}",
        "tier": 2,
        "confidence": confidence,
        "summary": summary,
        "detail": {
            "kind": check_id,
            "severity": severity,
            "line": line,
            "content": content[:200],
            "remediation": remediation,
        },
    }
