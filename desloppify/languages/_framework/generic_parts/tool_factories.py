"""Detector/fixer factory helpers for generic language plugins."""

from __future__ import annotations

import subprocess  # nosec B404
from collections.abc import Callable
from pathlib import Path
from typing import Any

from desloppify.languages._framework.base.types import (
    DetectorPhase,
    FixerConfig,
    FixResult,
)
from desloppify.languages._framework.generic_parts.parsers import PARSERS
from desloppify.languages._framework.generic_parts.tool_runner import (
    SubprocessRun,
    ToolRunResult,
    resolve_command_argv,
    run_tool_result,
)
from desloppify.languages._framework.generic_parts.tool_spec import ToolSpec
from desloppify.base.discovery.file_paths import matches_exclusion
from desloppify.base.discovery.source import DEFAULT_EXCLUSIONS, get_exclusions
from desloppify.engine._state.filtering import make_issue


def _record_tool_failure_coverage(
    lang: Any,
    *,
    detector: str,
    label: str,
    result: ToolRunResult,
) -> None:
    """Attach reduced-coverage metadata when generic detector tooling fails."""
    if result.status != "error":
        return

    record = {
        "detector": detector,
        "status": "reduced",
        "confidence": 0.0,
        "summary": f"{label} tooling unavailable ({result.error_kind or 'error'})",
        "impact": "Detector results may be under-reported for this scan.",
        "remediation": "Install/fix the tool command and rerun scan.",
        "tool": label,
        "reason": result.error_kind or "tool_error",
    }
    detector_coverage = getattr(lang, "detector_coverage", None)
    if isinstance(detector_coverage, dict):
        detector_coverage[detector] = dict(record)

    coverage_warnings = getattr(lang, "coverage_warnings", None)
    if isinstance(coverage_warnings, list):
        if not any(
            isinstance(entry, dict) and entry.get("detector") == detector
            for entry in coverage_warnings
        ):
            coverage_warnings.append(dict(record))


def _drop_excluded_entries(
    entries: list[dict[str, Any]], run_path: Path
) -> list[dict[str, Any]]:
    """Drop tool findings for paths the scan excludes.

    External linters read their own config, not desloppify's, so running one at
    the project root reports on vendored and excluded directories the user has
    asked the scan to ignore. Those findings are not actionable and, in a
    project with a large vendor tree, can outnumber real ones several times
    over — so they are filtered on the way in rather than scored.
    """
    exclusions = tuple(get_exclusions()) + tuple(DEFAULT_EXCLUSIONS)
    if not exclusions:
        return entries

    kept: list[dict[str, Any]] = []
    for entry in entries:
        raw = str(entry.get("file") or "")
        if not raw:
            kept.append(entry)
            continue
        candidate = Path(raw)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(run_path)
            except ValueError:
                kept.append(entry)
                continue
        rel_path = candidate.as_posix()
        if not any(matches_exclusion(rel_path, pat) for pat in exclusions if pat):
            kept.append(entry)
    return kept


def make_tool_phase(
    label: str,
    cmd: str,
    fmt: str,
    smell_id: str,
    tier: int,
    *,
    confidence: str = "medium",
    cwd_fn: Callable[[Path, Any], Path] | None = None,
) -> DetectorPhase:
    """Create a DetectorPhase that runs an external tool and parses output."""
    parser = PARSERS[fmt]

    def run(path: Path, lang: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
        run_path = cwd_fn(path, lang).resolve() if cwd_fn is not None else path
        run_result = run_tool_result(cmd, run_path, parser)
        if run_result.status == "error":
            _record_tool_failure_coverage(
                lang,
                detector=smell_id,
                label=label,
                result=run_result,
            )
            return [], {}
        entries = _drop_excluded_entries(list(run_result.entries), run_path)
        meta = run_result.meta if isinstance(run_result.meta, dict) else {}
        meta_potential = meta.get("potential")
        potential = meta_potential if isinstance(meta_potential, int) else 0

        if run_result.status == "empty":
            return [], ({smell_id: potential} if potential > 0 else {})

        if not entries:
            return [], ({smell_id: potential} if potential > 0 else {})
        issues = [
            make_issue(
                smell_id,
                entry["file"],
                str(entry.get("id") or f"{smell_id}::{entry['line']}"),
                tier=tier,
                confidence=str(entry.get("confidence") or confidence),
                summary=str(entry.get("summary") or entry["message"]),
                detail=entry.get("detail") if isinstance(entry.get("detail"), dict) else None,
            )
            for entry in entries
        ]
        return issues, {smell_id: potential if potential > 0 else len(entries)}

    return DetectorPhase(label, run)


def make_detect_fn(
    cmd: str,
    parser: Callable[[str, Path], list[dict[str, Any]]],
    *,
    run_subprocess: SubprocessRun | None = None,
) -> Callable:
    """Create detect function that runs a tool with an optional injected runner."""

    def detect(path: Path | Any, **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        scan_path = _coerce_detect_path(path)
        result = run_tool_result(cmd, scan_path, parser, run_subprocess=run_subprocess)
        return list(result.entries)

    return detect


def _coerce_detect_path(path_or_args: Path | Any) -> Path:
    """Accept both generic detector Path calls and cmd_detect Namespace calls."""
    if isinstance(path_or_args, Path):
        return path_or_args
    raw_path = getattr(path_or_args, "path", path_or_args)
    return Path(raw_path)


def make_generic_fixer(
    tool: ToolSpec,
    *,
    run_subprocess: SubprocessRun | None = None,
) -> FixerConfig:
    """Create a FixerConfig from a tool spec with an optional injected runner."""
    smell_id = tool["id"]
    fix_cmd = tool["fix_cmd"]
    if fix_cmd is None:
        raise ValueError("make_generic_fixer requires tool['fix_cmd'] to be provided")
    detect = make_detect_fn(
        tool["cmd"],
        PARSERS[tool["fmt"]],
        run_subprocess=run_subprocess,
    )

    def fix(
        entries: list[dict[str, Any]],
        dry_run: bool = False,
        path: Path | None = None,
        **kwargs: Any,
    ) -> FixResult:
        del kwargs
        if dry_run or not path:
            return FixResult(entries=[{"file": e["file"], "line": e["line"]} for e in entries])
        runner = run_subprocess or subprocess.run
        try:
            runner(
                resolve_command_argv(fix_cmd),
                shell=False,
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return FixResult(entries=[], skip_reasons={"tool_unavailable": len(entries)})
        remaining = detect(path)
        fixed_count = max(0, len(entries) - len(remaining))
        return FixResult(
            entries=[{"file": e["file"], "fixed": True} for e in entries[:fixed_count]]
        )

    return FixerConfig(
        label=f"Fix {tool['label']} issues",
        detect=detect,
        fix=fix,
        detector=smell_id,
        verb="Fixed",
        dry_verb="Would fix",
    )


__all__ = [
    "make_detect_fn",
    "make_generic_fixer",
    "make_tool_phase",
]
