"""Shared regex patterns and tiny helper predicates for security checks."""

from __future__ import annotations

import re

# Secret format patterns (high-confidence format-based detection).
SECRET_FORMAT_PATTERNS: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "AWS access key",
        re.compile(r"AKIA[0-9A-Z]{16}"),
        "critical",
        "Rotate the AWS key immediately and use IAM roles or environment variables",
    ),
    (
        "GitHub token",
        re.compile(r"gh[ps]_[A-Za-z0-9_]{36,}"),
        "critical",
        "Revoke the token and use environment variables or GitHub Actions secrets",
    ),
    (
        "Private key block",
        re.compile(r"-----BEGIN\s+(?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
        "critical",
        "Remove the private key from source and store in a secrets manager",
    ),
    (
        "Stripe key",
        re.compile(r"[sr]k_(?:live|test)_[0-9a-zA-Z]{20,}"),
        "high",
        "Move Stripe keys to environment variables",
    ),
    (
        "Slack token",
        re.compile(r"xox[bpas]-[0-9a-zA-Z-]+"),
        "high",
        "Revoke the Slack token and use environment variables",
    ),
    (
        "JWT token",
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),
        "medium",
        "Do not hardcode JWTs — generate them at runtime",
    ),
    (
        "Database connection string with password",
        re.compile(r"(?:postgres|mysql|mongodb|redis)://\w+:[^@\s]{3,}@"),
        "critical",
        "Move database credentials to environment variables",
    ),
]

# Secret variable-name + literal patterns.
SECRET_NAME_RE = re.compile(
    r"""(?:^|[\s,;(])          # start of line or delimiter
    (?:const|let|var|export)?  # optional JS/TS keyword
    \s*
    \$?                        # optional PHP $ sigil
    ([A-Za-z_]\w*)             # variable name (captured)
    \s*[:=]\s*                 # assignment
    (['"`])                    # opening quote
    (.+?)                      # value (captured)
    \2                         # closing quote
    """,
    re.VERBOSE,
)

SECRET_NAMES = re.compile(
    r"(?i)(?:password|passwd|secret|api_key|apikey|token|credentials|"
    r"auth_token|private_key|access_key|client_secret|secret_key)",
)

PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "xxx",
    "yyy",
    "zzz",
    "placeholder",
    "test",
    "example",
    "dummy",
    "none",
    "null",
    "undefined",
    "todo",
    "fixme",
}

PLACEHOLDER_PREFIXES = ("your-", "your_", "<", "${", "{{")

# Environment lookups are not hardcoded secrets.
ENV_LOOKUPS = (
    "os.environ",
    "os.getenv",
    "process.env.",
    "import.meta.env",
    "os.environ.get(",
    "os.environ[",
    # PHP
    "env(",
    "getenv(",
    "$_ENV[",
    "$_SERVER[",
    "config(",
)

# Insecure random usage near security-sensitive contexts.
RANDOM_CALLS = re.compile(
    r"(?:Math\.random|random\.random|random\.randint"
    r"|(?<!\w)rand|(?<!\w)mt_rand|(?<!\w)array_rand)\s*\("
)
SECURITY_CONTEXT_WORDS = re.compile(
    r"(?i)(?:token|key|nonce|session|salt|secret|password|otp|csrf|auth)",
)

# Weak crypto / TLS configuration patterns.
WEAK_CRYPTO_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(r"verify\s*=\s*False"),
        "TLS verification disabled",
        "high",
        "Never disable TLS verification — use proper certificates",
    ),
    (
        re.compile(r"ssl\._create_unverified_context\s*\("),
        "Unverified SSL context",
        "high",
        "Use ssl.create_default_context() instead",
    ),
    (
        re.compile(r"rejectUnauthorized\s*:\s*false"),
        "TLS rejection disabled",
        "high",
        "Never disable TLS certificate validation",
    ),
    (
        re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]0['\"]"),
        "TLS rejection disabled via env",
        "high",
        "Never disable TLS certificate validation",
    ),
]

# Sensitive values leaking into log calls.
LOG_CALLS = re.compile(
    r"(?:console\.(?:log|warn|error|info|debug)|"
    r"log(?:ger)?\.(?:info|debug|warning|error|critical)|"
    r"logging\.(?:info|debug|warning|error|critical)|"
    r"Log::(?:info|debug|warning|error|critical|notice|alert|emergency)|"
    r"\berror_log|"
    r"\bprint)\s*\(",
)

SENSITIVE_IN_LOG = re.compile(
    r"(?i)(?:password|token|secret|api_key|apikey|credentials|"
    r"private_key|access_key|authorization)",
)


def has_secret_format_match(line: str) -> bool:
    """Whether a line matches any high-confidence secret format."""
    return any(pattern.search(line) for _, pattern, _, _ in SECRET_FORMAT_PATTERNS)


def is_comment_line(line: str) -> bool:
    """Quick check if a line is likely a comment."""
    stripped = line.lstrip()
    return (
        stripped.startswith("//")
        or stripped.startswith("#")
        or stripped.startswith("*")
        or stripped.startswith("/*")
    )


def is_env_lookup(line: str) -> bool:
    """Check if a line contains an environment variable lookup."""
    return any(lookup in line for lookup in ENV_LOOKUPS)


def is_placeholder(value: str) -> bool:
    """Check if a value is a placeholder, not a real secret."""
    lower = value.lower().strip()
    if lower in PLACEHOLDER_VALUES:
        return True
    if any(lower.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES):
        return True
    return len(value) < 8
