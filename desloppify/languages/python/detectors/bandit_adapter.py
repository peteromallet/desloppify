"""Bandit adapter — Python security detection via the bandit static analyser.

Runs ``bandit -r -f json --quiet <path>`` as a subprocess and converts its JSON
output into the security entry dicts expected by ``phase_security``.

Bandit covers AST-level security checks (shell injection, unsafe deserialization,
SQL injection, etc.) more reliably than custom regex/AST patterns. When bandit is
installed, it is used as the lang-specific security detector; otherwise
Python-specific security checks will be skipped.

Bandit severity → desloppify tier/confidence mapping:
  HIGH   → tier=4, confidence="high"
  MEDIUM → tier=3, confidence="medium"
  LOW    → tier=3, confidence="low"

The ``check_id`` in the entry detail is the bandit test ID (e.g., "B602") so
findings are stable across reruns and can be wontfix-tracked by ID.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import rel

logger = logging.getLogger(__name__)

_SEVERITY_TO_TIER = {"HIGH": 4, "MEDIUM": 3, "LOW": 3}
_SEVERITY_TO_CONFIDENCE = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}

# Bandit test IDs that overlap with the cross-language security detector
# (secret names, hardcoded passwords). Skip these to avoid duplicate findings.
_CROSS_LANG_OVERLAP = frozenset(
    {
        "B105",  # hardcoded_password_string
        "B106",  # hardcoded_password_funcarg
        "B107",  # hardcoded_password_default
        "B501",  # request_with_no_cert_validation  (covered by weak_crypto_tls)
        "B502",  # ssl_with_bad_version
        "B503",  # ssl_with_bad_defaults
        "B504",  # ssl_with_no_version
        "B505",  # weak_cryptographic_key
    }
)


def _to_security_entry(
    result: dict,
    zone_map: FileZoneMap | None,
) -> dict | None:
    """Convert a single bandit result dict to a security entry, or None to skip."""
    filepath = result.get("filename", "")
    if not filepath:
        return None

    # Apply zone filtering — only GENERATED and VENDOR are excluded for security.
    if zone_map is not None:
        zone = zone_map.get(filepath)
        if zone in (Zone.GENERATED, Zone.VENDOR):
            return None

    test_id = result.get("test_id", "")
    if test_id in _CROSS_LANG_OVERLAP:
        return None

    raw_severity = result.get("issue_severity", "MEDIUM").upper()
    raw_confidence = result.get("issue_confidence", "MEDIUM").upper()

    # Suppress LOW-severity + LOW-confidence (very noisy, low signal).
    if raw_severity == "LOW" and raw_confidence == "LOW":
        return None

    tier = _SEVERITY_TO_TIER.get(raw_severity, 3)
    confidence = _SEVERITY_TO_CONFIDENCE.get(raw_severity, "medium")

    line = result.get("line_number", 0)
    summary = result.get("issue_text", "")
    test_name = result.get("test_name", test_id)
    rel_path = rel(filepath)

    return {
        "file": filepath,
        "name": f"security::{test_id}::{rel_path}::{line}",
        "tier": tier,
        "confidence": confidence,
        "summary": f"[{test_id}] {summary}",
        "detail": {
            "kind": test_id,
            "severity": raw_severity.lower(),
            "line": line,
            "content": result.get("code", "")[:200],
            "remediation": result.get("more_info", ""),
            "test_name": test_name,
            "source": "bandit",
        },
    }


def detect_with_bandit(
    path: Path,
    zone_map: FileZoneMap | None,
    timeout: int = 120,
) -> tuple[list[dict], int] | None:
    """Run bandit on *path* and return (entries, files_scanned), or None on failure.

    Returns None when bandit is not installed, so the caller knows to skip
    Python-specific security checks.
    """
    try:
        result = subprocess.run(
            [
                "bandit",
                "-r",
                "-f",
                "json",
                "--quiet",
                str(path),
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.debug("bandit: not installed — Python-specific security checks will be skipped")
        return None
    except subprocess.TimeoutExpired:
        logger.debug("bandit: timed out after %ds", timeout)
        return None
    except OSError as exc:
        logger.debug("bandit: OSError: %s", exc)
        return None

    stdout = result.stdout.strip()
    if not stdout:
        # Bandit exits 0 with no output when there's nothing to scan.
        return [], 0

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.debug("bandit: JSON parse error: %s", exc)
        return None

    raw_results: list[dict] = data.get("results", [])
    metrics: dict = data.get("metrics", {})

    # Count scanned files from metrics (bandit reports per-file stats).
    files_scanned = sum(
        1
        for key in metrics
        if key != "_totals" and not key.endswith("_totals")
    )

    entries: list[dict] = []
    for res in raw_results:
        entry = _to_security_entry(res, zone_map)
        if entry is not None:
            entries.append(entry)

    logger.debug("bandit: %d findings from %d files", len(entries), files_scanned)
    return entries, files_scanned
