"""Python language security + coverage wiring helpers."""

from __future__ import annotations

import importlib.util
import shutil

from desloppify.base.config import load_config
from desloppify.base.discovery.source import collect_exclude_dirs
from desloppify.languages._framework.base.types import DetectorCoverageStatus, LangSecurityResult
from desloppify.languages.python.detectors.bandit_adapter import detect_with_bandit
from desloppify.languages.python._helpers import scan_root_from_files


def missing_bandit_coverage() -> DetectorCoverageStatus:
    return DetectorCoverageStatus(
        detector="security",
        status="reduced",
        confidence=0.6,
        summary="bandit is not installed — Python-specific security checks will be skipped.",
        impact=(
            "Python-specific security coverage is reduced; clean security output may "
            "miss shell injection, unsafe deserialization, and risky SQL/subprocess patterns."
        ),
        remediation="Install Bandit: pip install bandit",
        tool="bandit",
        reason="missing_dependency",
    )


def _bandit_available() -> bool:
    """Whether bandit can actually be run the way the adapter runs it.

    The adapter invokes ``sys.executable -m bandit``, so an importable bandit
    package is enough — a ``bandit`` console script on PATH is not required.
    Checking only PATH reports reduced coverage for every installation where
    desloppify lives in its own virtualenv (pipx, ``uv tool install``), even
    though bandit ran fine and produced findings.
    """
    if shutil.which("bandit") is not None:
        return True
    try:
        return importlib.util.find_spec("bandit") is not None
    except (ImportError, ValueError):
        return False


def python_scan_coverage_prerequisites() -> list[DetectorCoverageStatus]:
    if _bandit_available():
        return []
    return [missing_bandit_coverage()]


def _load_bandit_skip_tests() -> list[str] | None:
    """Read ``languages.python.bandit_skip_tests`` from project config."""
    cfg = load_config()
    lang_cfg = cfg.get("languages", {})
    py_cfg = lang_cfg.get("python", {}) if isinstance(lang_cfg, dict) else {}
    raw = py_cfg.get("bandit_skip_tests") if isinstance(py_cfg, dict) else None
    if isinstance(raw, list) and all(isinstance(t, str) for t in raw):
        return raw
    return None


def detect_python_security(files, zone_map) -> LangSecurityResult:
    scan_root = scan_root_from_files(files)
    if scan_root is None:
        return LangSecurityResult(entries=[], files_scanned=0)

    exclude_dirs = collect_exclude_dirs(scan_root)
    skip_tests = _load_bandit_skip_tests()
    result = detect_with_bandit(
        scan_root, zone_map, exclude_dirs=exclude_dirs, skip_tests=skip_tests,
    )
    coverage = result.status.coverage()
    return LangSecurityResult(
        entries=result.entries,
        files_scanned=result.files_scanned,
        coverage=coverage,
    )


__all__ = [
    "_bandit_available",
    "detect_python_security",
    "missing_bandit_coverage",
    "python_scan_coverage_prerequisites",
]
