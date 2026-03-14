"""DetectorPhase factories for framework specs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from desloppify.base.output.terminal import log as _log
from desloppify.languages._framework.base.types import DetectorPhase, LangRuntimeContract
from desloppify.languages._framework.generic_support.core import make_tool_phase
from desloppify.state_io import Issue

from .detection import detect_ecosystem_frameworks
from .registry import ensure_builtin_specs_loaded, list_framework_specs
from .types import FrameworkSpec, ScannerRule, ToolIntegration


def _has_capability(lang: LangRuntimeContract, cap: str) -> bool:
    key = str(cap or "").strip()
    if not key:
        return True
    if key == "dep_graph":
        return getattr(lang, "dep_graph", None) is not None
    if key == "zone_map":
        return getattr(lang, "zone_map", None) is not None
    if key == "file_finder":
        return callable(getattr(lang, "file_finder", None))
    return bool(getattr(lang, key, None))


def _record_capability_degradation(
    lang: Any,
    *,
    detector: str,
    rule_id: str,
    missing: list[str],
) -> None:
    """Record reduced coverage metadata when a framework rule cannot run."""
    if not missing:
        return
    summary = (
        f"Skipped {detector} framework rule '{rule_id}' (missing: {', '.join(missing)})."
    )
    record = {
        "detector": detector,
        "status": "reduced",
        "confidence": 0.5,
        "summary": summary,
        "impact": "Some framework-specific issues may be under-reported for this scan.",
        "remediation": "Enable the required language capabilities and rerun scan.",
        "tool": "",
        "reason": "missing_capability",
    }
    detector_coverage = getattr(lang, "detector_coverage", None)
    if isinstance(detector_coverage, dict):
        existing = detector_coverage.get(detector)
        if isinstance(existing, dict):
            merged = dict(existing)
            merged["status"] = "reduced"
            merged["confidence"] = min(float(existing.get("confidence", 1.0)), 0.5)
            merged_summary = str(merged.get("summary", "") or "").strip()
            if merged_summary and summary not in merged_summary:
                merged["summary"] = f"{merged_summary} | {summary}"
            elif not merged_summary:
                merged["summary"] = summary
            detector_coverage[detector] = merged
        else:
            detector_coverage[detector] = dict(record)

    coverage_warnings = getattr(lang, "coverage_warnings", None)
    if isinstance(coverage_warnings, list):
        if not any(
            isinstance(entry, dict) and entry.get("detector") == detector for entry in coverage_warnings
        ):
            coverage_warnings.append(dict(record))


def _run_scanner_rules(
    scan_root: Path,
    lang: LangRuntimeContract,
    *,
    detector: str,
    rules: tuple[ScannerRule, ...],
) -> tuple[list[Issue], int]:
    issues: list[Issue] = []
    potential = 0

    for rule in rules:
        scan_fn = rule.scan
        issue_factory = rule.issue_factory
        if scan_fn is None or issue_factory is None:
            continue

        missing = [cap for cap in rule.requires if not _has_capability(lang, cap)]
        if missing:
            _record_capability_degradation(
                lang,
                detector=detector,
                rule_id=rule.id,
                missing=missing,
            )
            continue

        entries, scanned = scan_fn(scan_root, lang)
        potential = max(potential, int(scanned or 0))
        for entry in entries:
            issues.append(issue_factory(entry))
        if entries and rule.log_message:
            _log(rule.log_message(len(entries)))

    return issues, potential


def _framework_smells_phase(spec: FrameworkSpec) -> DetectorPhase:
    label = f"{spec.label} framework smells"

    def run(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
        detection = detect_ecosystem_frameworks(path, lang, spec.ecosystem)
        if spec.id not in detection.present:
            return [], {}

        scan_root = detection.package_root
        issues, potential = _run_scanner_rules(
            scan_root,
            lang,
            detector=spec.id,
            rules=spec.scanners,
        )
        return issues, ({spec.id: potential} if potential > 0 else {})

    return DetectorPhase(label, run)


def _framework_tool_phase(spec: FrameworkSpec, tool: ToolIntegration) -> DetectorPhase:
    tool_phase = make_tool_phase(
        tool.label,
        tool.cmd,
        tool.fmt,
        tool.id,
        tool.tier,
        confidence=tool.confidence,
    )
    tool_phase.slow = bool(tool.slow)

    def run(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
        detection = detect_ecosystem_frameworks(path, lang, spec.ecosystem)
        if spec.id not in detection.present:
            return [], {}

        scan_root = detection.package_root
        return tool_phase.run(scan_root, lang)

    return DetectorPhase(tool_phase.label, run, slow=tool_phase.slow)


def framework_phases(lang_name: str) -> list[DetectorPhase]:
    """Return all framework phases for a language plugin."""
    del lang_name
    ensure_builtin_specs_loaded()

    phases: list[DetectorPhase] = []
    for spec in list_framework_specs().values():
        phases.append(_framework_smells_phase(spec))
        for tool in spec.tools:
            phases.append(_framework_tool_phase(spec, tool))
    return phases


__all__ = ["framework_phases"]

