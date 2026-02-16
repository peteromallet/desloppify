"""C#-specific security detectors."""

from __future__ import annotations

import re
from pathlib import Path

from ....zones import FileZoneMap, Zone

_SQL_INTERPOLATION_RE = re.compile(
    r"\b(?:SqlCommand|Execute(?:Reader|NonQuery|Scalar)?)\s*\([^)]*\$\"",
    re.IGNORECASE,
)
_SQL_CONCAT_RE = re.compile(
    r"\b(?:SqlCommand|Execute(?:Reader|NonQuery|Scalar)?)\s*\([^)]*(?:\+|string\.Format)",
    re.IGNORECASE,
)
_RNG_IN_SECURITY_CONTEXT_RE = re.compile(
    r"\bnew\s+Random\s*\(\s*\).*(?:token|password|secret|key|nonce|salt|otp)",
    re.IGNORECASE,
)
_DISABLED_TLS_VERIFY_RE = re.compile(
    r"ServerCertificateValidationCallback\s*\+=\s*\([^)]*\)\s*=>\s*true",
    re.IGNORECASE,
)
_BINARY_FORMATTER_RE = re.compile(
    r"\bBinaryFormatter\b|\bSoapFormatter\b",
    re.IGNORECASE,
)


def detect_csharp_security(
    files: list[str],
    zone_map: FileZoneMap | None,
) -> tuple[list[dict], int]:
    """Detect C#-specific security issues. Returns (entries, files_scanned)."""
    from ....detectors.security import make_security_entry

    entries: list[dict] = []
    scanned = 0

    for filepath in files:
        if not filepath.endswith(".cs"):
            continue
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
        for line_num, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue

            if _SQL_INTERPOLATION_RE.search(line) or _SQL_CONCAT_RE.search(line):
                entries.append(
                    make_security_entry(
                        filepath,
                        line_num,
                        "sql_injection",
                        "Potential SQL injection: dynamic SQL command construction",
                        "critical",
                        "high",
                        line,
                        "Use parameterized SQL commands with SqlParameter.",
                    )
                )

            if _RNG_IN_SECURITY_CONTEXT_RE.search(line):
                entries.append(
                    make_security_entry(
                        filepath,
                        line_num,
                        "insecure_random",
                        "Insecure random in security-sensitive context",
                        "medium",
                        "medium",
                        line,
                        "Use RandomNumberGenerator.GetBytes or a cryptographic RNG.",
                    )
                )

            if _DISABLED_TLS_VERIFY_RE.search(line):
                entries.append(
                    make_security_entry(
                        filepath,
                        line_num,
                        "weak_crypto_tls",
                        "TLS certificate validation disabled",
                        "high",
                        "high",
                        line,
                        "Remove custom callback or validate certificates properly.",
                    )
                )

            if _BINARY_FORMATTER_RE.search(line):
                entries.append(
                    make_security_entry(
                        filepath,
                        line_num,
                        "unsafe_deserialization",
                        "Unsafe formatter usage may enable insecure deserialization",
                        "high",
                        "medium",
                        line,
                        "Use safe serializers (System.Text.Json) instead of BinaryFormatter/SoapFormatter.",
                    )
                )

    return entries, scanned
