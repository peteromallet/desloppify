"""Security finding rule metadata and finding builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desloppify.engine.detectors.patterns.security import LOG_CALLS as _LOG_CALLS
from desloppify.engine.detectors.patterns.security import RANDOM_CALLS as _RANDOM_CALLS
from desloppify.engine.detectors.patterns.security import (
    SECRET_FORMAT_PATTERNS as _SECRET_FORMAT_PATTERNS,
)
from desloppify.engine.detectors.patterns.security import (
    SECRET_NAME_RE as _SECRET_NAME_RE,
)
from desloppify.engine.detectors.patterns.security import SECRET_NAMES as _SECRET_NAMES
from desloppify.engine.detectors.patterns.security import (
    SECURITY_CONTEXT_WORDS as _SECURITY_CONTEXT_WORDS,
)
from desloppify.engine.detectors.patterns.security import (
    SENSITIVE_IN_LOG as _SENSITIVE_IN_LOG,
)
from desloppify.engine.detectors.patterns.security import (
    WEAK_CRYPTO_PATTERNS as _WEAK_CRYPTO_PATTERNS,
)
from desloppify.engine.detectors.patterns.security import (
    is_env_lookup as _is_env_lookup,
)
from desloppify.engine.detectors.patterns.security import (
    is_placeholder as _is_placeholder,
)
from desloppify.file_discovery import rel


@dataclass(frozen=True)
class SecurityRule:
    """Metadata describing one detector finding shape."""

    check_id: str
    summary: str
    severity: str
    confidence: str
    remediation: str


def make_security_entry(
    filepath: str,
    line: int,
    content: str,
    rule: SecurityRule,
) -> dict[str, Any]:
    """Build a security finding entry dict."""
    rel_path = rel(filepath)
    return {
        "file": filepath,
        "name": f"security::{rule.check_id}::{rel_path}::{line}",
        "tier": 2,
        "confidence": rule.confidence,
        "summary": rule.summary,
        "detail": {
            "kind": rule.check_id,
            "severity": rule.severity,
            "line": line,
            "content": content[:200],
            "remediation": rule.remediation,
        },
    }


def _secret_format_entries(
    filepath: str,
    line_num: int,
    line: str,
    is_test: bool,
) -> list[dict[str, Any]]:
    confidence = "medium" if is_test else "high"
    entries: list[dict[str, Any]] = []
    for label, pattern, severity, remediation in _SECRET_FORMAT_PATTERNS:
        if not pattern.search(line):
            continue
        entries.append(
            make_security_entry(
                filepath,
                line_num,
                line,
                SecurityRule(
                    check_id="hardcoded_secret_value",
                    summary=f"Hardcoded {label} detected",
                    severity=severity,
                    confidence=confidence,
                    remediation=remediation,
                ),
            )
        )
    return entries


def _secret_name_entries(
    filepath: str,
    line_num: int,
    line: str,
    is_test: bool,
) -> list[dict[str, Any]]:
    confidence = "medium" if is_test else "high"
    entries: list[dict[str, Any]] = []
    for secret_match in _SECRET_NAME_RE.finditer(line):
        var_name = secret_match.group(1)
        value = secret_match.group(3)
        if not _SECRET_NAMES.search(var_name):
            continue
        if _is_env_lookup(line):
            continue
        if _is_placeholder(value):
            continue
        entries.append(
            make_security_entry(
                filepath,
                line_num,
                line,
                SecurityRule(
                    check_id="hardcoded_secret_name",
                    summary=f"Hardcoded secret in variable '{var_name}'",
                    severity="high",
                    confidence=confidence,
                    remediation="Move secret to environment variable or secrets manager",
                ),
            )
        )
    return entries


def _insecure_random_entries(
    filepath: str,
    line_num: int,
    line: str,
) -> list[dict[str, Any]]:
    if not (_RANDOM_CALLS.search(line) and _SECURITY_CONTEXT_WORDS.search(line)):
        return []
    return [
        make_security_entry(
            filepath,
            line_num,
            line,
            SecurityRule(
                check_id="insecure_random",
                summary="Insecure random used in security context",
                severity="medium",
                confidence="medium",
                remediation="Use secrets.token_hex() (Python) or crypto.randomUUID() (JS)",
            ),
        )
    ]


def _weak_crypto_entries(
    filepath: str,
    line_num: int,
    line: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for pattern, label, severity, remediation in _WEAK_CRYPTO_PATTERNS:
        if not pattern.search(line):
            continue
        entries.append(
            make_security_entry(
                filepath,
                line_num,
                line,
                SecurityRule(
                    check_id="weak_crypto_tls",
                    summary=label,
                    severity=severity,
                    confidence="high",
                    remediation=remediation,
                ),
            )
        )
    return entries


def _sensitive_log_entries(
    filepath: str,
    line_num: int,
    line: str,
) -> list[dict[str, Any]]:
    if not (_LOG_CALLS.search(line) and _SENSITIVE_IN_LOG.search(line)):
        return []
    return [
        make_security_entry(
            filepath,
            line_num,
            line,
            SecurityRule(
                check_id="log_sensitive",
                summary="Sensitive data may be logged",
                severity="medium",
                confidence="medium",
                remediation="Remove sensitive data from log statements",
            ),
        )
    ]
