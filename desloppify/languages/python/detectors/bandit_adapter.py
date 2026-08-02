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
import time
from collections.abc import Iterable
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

# Keep a batch well below platform command-line limits while ensuring a single
# slow directory cannot consume the adapter's whole timeout budget.
_BANDIT_FILE_BATCH_SIZE = 250


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


def _run_bandit(
    targets: list[Path],
    zone_map: FileZoneMap | None,
    timeout: int = 120,
    exclude_dirs: list[str] | None = None,
    skip_tests: list[str] | None = None,
    require_target_metrics: bool = False,
) -> BanditScanResult:
    """Run Bandit for one non-empty set of explicit targets."""
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
        cmd.extend(["--exclude", ",".join(exclude_dirs)])
    if skip_tests:
        cmd.extend(["--skip", ",".join(skip_tests)])
    cmd.extend(str(target) for target in targets)

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

    returncode = getattr(result, "returncode", 0)
    fatal_returncode = isinstance(returncode, int) and returncode > 1
    stdout = result.stdout.strip()
    if not stdout:
        if fatal_returncode:
            status = BanditRunStatus(
                state="error",
                detail=f"bandit exited with status {returncode}",
            )
        elif require_target_metrics:
            status = BanditRunStatus(
                state="error",
                detail=f"bandit produced no output for {len(targets)} target(s)",
            )
        else:
            # Bandit exits 0 with no output when a legacy recursive call has
            # nothing to scan.
            status = BanditRunStatus(state="ok")
        return BanditScanResult(
            entries=[],
            files_scanned=0,
            status=status,
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

    raw_results = data.get("results", [])
    metrics = data.get("metrics", {})
    errors = data.get("errors", [])
    if not isinstance(raw_results, list):
        raw_results = []
    if not isinstance(metrics, dict):
        metrics = {}

    # Count scanned files from metrics (bandit reports per-file stats).
    files_scanned = sum(
        1
        for key in metrics
        if key != "_totals" and not key.endswith("_totals")
    )

    entries: list[dict] = []
    for res in raw_results:
        if not isinstance(res, dict):
            continue
        entry = _to_security_entry(res, zone_map)
        if entry is not None:
            entries.append(entry)

    status = BanditRunStatus(state="ok")
    if fatal_returncode:
        status = BanditRunStatus(
            state="error",
            detail=f"bandit exited with status {returncode}",
        )
    elif errors:
        error_count = len(errors) if isinstance(errors, list) else 1
        status = BanditRunStatus(
            state="error",
            detail=f"bandit reported {error_count} file error(s)",
        )
    elif require_target_metrics:
        project_root = get_project_root()
        metric_paths = {
            (Path(path) if Path(path).is_absolute() else project_root / path).resolve()
            for path in metrics
            if path != "_totals" and not path.endswith("_totals")
        }
        missing_targets = [target for target in targets if target.resolve() not in metric_paths]
        if missing_targets:
            status = BanditRunStatus(
                state="error",
                detail=f"bandit omitted metrics for {len(missing_targets)} target(s)",
            )

    logger.debug(
        "bandit: %d issues from %d files (%s)",
        len(entries),
        files_scanned,
        status.state,
    )
    return BanditScanResult(
        entries=entries,
        files_scanned=files_scanned,
        status=status,
    )


def _file_targets(files: Iterable[str | Path]) -> list[Path]:
    """Normalize, filter, and de-duplicate discovered Python file targets."""
    project_root = get_project_root()
    targets: list[Path] = []
    seen: set[Path] = set()
    for file in files:
        target = Path(file)
        if target.suffix != ".py":
            continue
        if not target.is_absolute():
            target = project_root / target
        target = target.resolve()
        if target in seen:
            continue
        seen.add(target)
        targets.append(target)
    return targets


def detect_with_bandit_files(
    files: Iterable[str | Path],
    zone_map: FileZoneMap | None,
    timeout: int = 120,
    exclude_dirs: list[str] | None = None,
    skip_tests: list[str] | None = None,
    batch_size: int = _BANDIT_FILE_BATCH_SIZE,
) -> BanditScanResult:
    """Run Bandit over the scanner's discovered Python files in safe batches.

    Scanning explicit file targets keeps Bandit's traversal aligned with the
    scanner's exclusion-aware source discovery. A failure in any batch retains
    findings from successful batches but reports reduced coverage.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    targets = _file_targets(files)
    if not targets:
        return BanditScanResult(
            entries=[],
            files_scanned=0,
            status=BanditRunStatus(state="ok"),
        )

    batches = [
        targets[index : index + batch_size]
        for index in range(0, len(targets), batch_size)
    ]
    deadline = time.monotonic() + timeout
    entries_by_name: dict[str, dict] = {}
    files_scanned = 0
    first_failure: BanditRunStatus | None = None

    for batch_number, batch in enumerate(batches, start=1):
        remaining_timeout = deadline - time.monotonic()
        if remaining_timeout <= 0:
            first_failure = first_failure or BanditRunStatus(
                state="timeout",
                detail=f"total timeout={timeout}s before batch {batch_number}/{len(batches)}",
            )
            break
        result = _run_bandit(
            batch,
            zone_map,
            timeout=remaining_timeout,
            exclude_dirs=exclude_dirs,
            skip_tests=skip_tests,
            require_target_metrics=True,
        )
        files_scanned += result.files_scanned
        for entry in result.entries:
            entries_by_name.setdefault(str(entry["name"]), entry)

        if result.status.state != "ok" and first_failure is None:
            detail = result.status.detail or result.status.state
            first_failure = BanditRunStatus(
                state=result.status.state,
                detail=f"batch {batch_number}/{len(batches)}: {detail}",
            )
        if result.status.state == "missing_tool":
            break

    status = first_failure or BanditRunStatus(state="ok")
    return BanditScanResult(
        entries=list(entries_by_name.values()),
        files_scanned=files_scanned,
        status=status,
    )


def detect_with_bandit(
    path: Path,
    zone_map: FileZoneMap | None,
    timeout: int = 120,
    exclude_dirs: list[str] | None = None,
    skip_tests: list[str] | None = None,
) -> BanditScanResult:
    """Run Bandit recursively on *path* for legacy direct callers.

    Parameters
    ----------
    exclude_dirs:
        Absolute directory paths to pass to bandit's ``--exclude`` flag.
        When non-empty, bandit will skip these directories during its
        recursive scan.
    skip_tests:
        Bandit test IDs to suppress via ``--skip`` (e.g. ``["B101", "B601"]``).
        Allows users to disable entire rule families from ``config.json``.
    """
    return _run_bandit(
        [path.resolve()],
        zone_map,
        timeout=timeout,
        exclude_dirs=exclude_dirs,
        skip_tests=skip_tests,
    )
