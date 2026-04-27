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
issues are stable across reruns and can be wontfix-tracked by ID.
"""

from __future__ import annotations

import json
import logging
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from desloppify.base.discovery.file_paths import rel
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages._framework.base.types import DetectorCoverageStatus

logger = logging.getLogger(__name__)

_SEVERITY_TO_TIER = {"HIGH": 4, "MEDIUM": 3, "LOW": 3}
_SEVERITY_TO_CONFIDENCE = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}

# Bandit test IDs that overlap with the cross-language security detector
# (secret names, hardcoded passwords). Skip these to avoid duplicate issues.
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

_BANDIT_IMPACT_TEXT = (
    "Python-specific security checks were skipped; this can miss shell injection, "
    "unsafe deserialization, and risky SQL/subprocess patterns."
)


BanditRunState = Literal["ok", "missing_tool", "timeout", "error", "parse_error"]


@dataclass(frozen=True)
class BanditRunStatus:
    """Typed execution status for a Bandit adapter invocation."""

    state: BanditRunState
    detail: str = ""
    tool: str = "bandit"

    def coverage(self) -> DetectorCoverageStatus | None:
        """Convert non-success statuses into detector coverage metadata."""
        if self.state == "ok":
            return None

        if self.state == "missing_tool":
            return DetectorCoverageStatus(
                detector="security",
                status="reduced",
                confidence=0.6,
                summary="bandit is not installed — Python-specific security checks were skipped.",
                impact=_BANDIT_IMPACT_TEXT,
                remediation="Install Bandit: pip install bandit",
                tool=self.tool,
                reason="missing_dependency",
            )

        if self.state == "timeout":
            return DetectorCoverageStatus(
                detector="security",
                status="reduced",
                confidence=0.75,
                summary="bandit timed out — Python-specific security checks were skipped this scan.",
                impact=_BANDIT_IMPACT_TEXT,
                remediation="Rerun scan or run `bandit -r -f json --quiet <path>` manually.",
                tool=self.tool,
                reason="timeout",
            )

        if self.state == "parse_error":
            return DetectorCoverageStatus(
                detector="security",
                status="reduced",
                confidence=0.75,
                summary="bandit output could not be parsed — Python-specific security checks were skipped this scan.",
                impact=_BANDIT_IMPACT_TEXT,
                remediation="Update/reinstall Bandit and rerun scan.",
                tool=self.tool,
                reason="parse_error",
            )

        return DetectorCoverageStatus(
            detector="security",
            status="reduced",
            confidence=0.75,
            summary="bandit failed to execute — Python-specific security checks were skipped this scan.",
            impact=_BANDIT_IMPACT_TEXT,
            remediation="Verify Bandit is runnable and rerun scan.",
            tool=self.tool,
            reason="execution_error",
        )


@dataclass(frozen=True)
class BanditScanResult:
    """Bandit issues plus typed execution status."""

    entries: list[dict]
    files_scanned: int
    status: BanditRunStatus


def _to_security_entry(
    result: dict,
    zone_map: FileZoneMap | None,
) -> dict | None:
    """Convert a single bandit result dict to a security entry, or None to skip."""
    filepath = str(result.get("filename", "") or "")
    if not filepath:
        return None

    rel_path = rel(filepath)

    # Apply zone filtering — only GENERATED and VENDOR are excluded for security.
    if zone_map is not None:
        zone = zone_map.get(rel_path)
        if zone in (Zone.TEST, Zone.CONFIG, Zone.GENERATED, Zone.VENDOR):
            return None

    test_id = result.get("test_id", "")
    if test_id in _CROSS_LANG_OVERLAP:
        return None

    raw_severity = result.get("issue_severity", "MEDIUM").upper()
    raw_confidence = result.get("issue_confidence", "MEDIUM").upper()

    # Suppress noisy low-signal combinations:
    # - LOW severity + LOW confidence (very noisy, low signal)
    # - MEDIUM severity + LOW confidence (e.g. "tokenizer_name" flagged as hardcoded secret)
    if raw_confidence == "LOW" and raw_severity in ("LOW", "MEDIUM"):
        return None

    tier = _SEVERITY_TO_TIER.get(raw_severity, 3)
    confidence = _SEVERITY_TO_CONFIDENCE.get(raw_severity, "medium")

    line = result.get("line_number", 0)
    summary = result.get("issue_text", "")
    test_name = result.get("test_name", test_id)
    return {
        "file": rel_path,
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


def _exclude_globs(exclude_dirs: list[str]) -> list[str]:
    """Expand absolute exclude paths into bandit-friendly glob patterns.

    Bandit's ``--exclude`` is matched against filenames it discovers during
    its recursive walk. When desloppify hands it absolute directory paths
    (e.g. ``/repo/.claude``), bandit only filters files whose name *equals*
    one of those paths — directories *under* the exclude (e.g.
    ``/repo/.claude/worktrees/foo.py``) still get scanned because their
    full filename does not equal the exclude string.

    Expanding each absolute path into ``**/<basename>/**`` (and a sibling
    ``<basename>`` form for the directory itself) ensures bandit prunes the
    whole subtree the way the rest of desloppify already does. The
    original absolute paths are kept as a belt-and-braces fallback.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for raw in exclude_dirs:
        if not raw:
            continue
        if raw not in seen:
            expanded.append(raw)
            seen.add(raw)
        # Walk every path component and emit a glob; this catches both
        # top-level (``.claude``) and nested (``.claude/worktrees``) excludes
        # without requiring callers to know the layout.
        parts = [p for p in raw.replace("\\", "/").split("/") if p]
        for part in parts:
            if not part or part in {"*", "**"}:
                continue
            for candidate in (f"**/{part}", f"**/{part}/**"):
                if candidate not in seen:
                    expanded.append(candidate)
                    seen.add(candidate)
    return expanded


def detect_with_bandit(
    path: Path,
    zone_map: FileZoneMap | None,
    timeout: int = 120,
    exclude_dirs: list[str] | None = None,
    skip_tests: list[str] | None = None,
) -> BanditScanResult:
    """Run bandit on *path* and return issues + typed execution status.

    Parameters
    ----------
    exclude_dirs:
        Absolute directory paths to skip. Each path is expanded into a
        ``**/<name>/**`` glob (in addition to the original absolute path)
        before being passed to bandit's ``--exclude`` flag, so that nested
        files under the exclude are pruned, not just the directory entry
        itself.
    skip_tests:
        Bandit test IDs to suppress via ``--skip`` (e.g. ``["B101", "B601"]``).
        Allows users to disable entire rule families from ``config.json``.
    """
    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        "-f",
        "json",
        "--quiet",
    ]
    if exclude_dirs:
        cmd.extend(["--exclude", ",".join(_exclude_globs(exclude_dirs))])
    if skip_tests:
        cmd.extend(["--skip", ",".join(skip_tests)])
    cmd.append(str(path.resolve()))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=get_project_root(),
            timeout=timeout,
        )  # nosec B603
    except FileNotFoundError:
        logger.debug("bandit: not installed — Python-specific security checks will be skipped")
        return BanditScanResult(
            entries=[],
            files_scanned=0,
            status=BanditRunStatus(state="missing_tool"),
        )
    except subprocess.TimeoutExpired:
        logger.debug("bandit: timed out after %ds", timeout)
        return BanditScanResult(
            entries=[],
            files_scanned=0,
            status=BanditRunStatus(state="timeout", detail=f"timeout={timeout}s"),
        )
    except OSError as exc:
        logger.debug("bandit: OSError: %s", exc)
        return BanditScanResult(
            entries=[],
            files_scanned=0,
            status=BanditRunStatus(state="error", detail=str(exc)),
        )

    stdout = result.stdout.strip()
    if not stdout:
        # Bandit exits 0 with no output when there's nothing to scan.
        return BanditScanResult(
            entries=[],
            files_scanned=0,
            status=BanditRunStatus(state="ok"),
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.debug("bandit: JSON parse error: %s", exc)
        return BanditScanResult(
            entries=[],
            files_scanned=0,
            status=BanditRunStatus(state="parse_error", detail=str(exc)),
        )

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

    logger.debug("bandit: %d issues from %d files", len(entries), files_scanned)
    return BanditScanResult(
        entries=entries,
        files_scanned=files_scanned,
        status=BanditRunStatus(state="ok"),
    )
