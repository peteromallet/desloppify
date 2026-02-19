"""Line scanner for generic cross-language security checks."""

from __future__ import annotations

from typing import Any

from .rules import (
    _insecure_random_entries,
    _secret_format_entries,
    _secret_name_entries,
    _sensitive_log_entries,
    _weak_crypto_entries,
)


def _scan_line_for_security_entries(
    *,
    filepath: str,
    line_num: int,
    line: str,
    is_test: bool,
) -> list[dict[str, Any]]:
    """Evaluate one source line against all generic security checks."""
    entries: list[dict[str, Any]] = []
    entries.extend(_secret_format_entries(filepath, line_num, line, is_test))
    entries.extend(_secret_name_entries(filepath, line_num, line, is_test))
    entries.extend(_insecure_random_entries(filepath, line_num, line))
    entries.extend(_weak_crypto_entries(filepath, line_num, line))
    entries.extend(_sensitive_log_entries(filepath, line_num, line))
    return entries
