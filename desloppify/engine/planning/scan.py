"""Issue generation pipeline (phase execution and normalization)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.discovery.file_paths import rel
from desloppify.base.output.terminal import colorize
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine.planning.helpers import is_subjective_phase
from desloppify.engine.policy.zones import ZONE_POLICIES, FileZoneMap
from desloppify.languages.framework import (
    clear_review_phase_prefetch,
    DetectorPhase,
    LangConfig,
    LangRun,
    auto_detect_lang,
    available_langs,
    capability_report,
    get_lang,
    make_lang_run,
    prewarm_review_phase_detectors,
)
from desloppify.state_io import Issue


@dataclass
class PlanScanOptions:
    """Config object for scan execution behavior."""

    include_slow: bool = True
    zone_overrides: dict[str, str] | None = None
    profile: str = "full"


def _stderr(msg: str) -> None:
    print(colorize(msg, "dim"), file=sys.stderr)


def _resolve_lang(
    lang: LangConfig | LangRun | None, project_root: Path
) -> LangConfig | LangRun:
    if lang is not None:
        return lang

    detected = auto_detect_lang(project_root)
    if detected is None:
        langs = available_langs()
        if not langs:
            raise ValueError("No language plugins available")
        detected = langs[0]
    return get_lang(detected)


def _build_zone_map(path: Path, lang: LangRun, zone_overrides: dict[str, str] | None) -> None:
    if not (lang.zone_rules and lang.file_finder):
        return

    files = lang.file_finder(path)
    lang.zone_map = FileZoneMap(
        files, lang.zone_rules, rel_fn=rel, overrides=zone_overrides
    )
    counts = lang.zone_map.counts()
    zone_str = ", ".join(
        f"{zone}: {count}" for zone, count in sorted(counts.items()) if count > 0
    )
    _stderr(f"  Zones: {zone_str}")

    report = capability_report(lang)
    if report is not None:
        present, missing = report
        if present:
            _stderr(f"  Capabilities: {', '.join(present)}")
        if missing:
            _stderr(f"  Not available: {', '.join(missing)}")


def _select_phases(lang: LangRun, *, include_slow: bool, profile: str) -> list[DetectorPhase]:
    active_profile = profile if profile in {"objective", "full", "ci"} else "full"
    phases = lang.phases
    if not include_slow or active_profile == "ci":
        phases = [phase for phase in phases if not phase.slow]
    if active_profile in {"objective", "ci"}:
        phases = [phase for phase in phases if not is_subjective_phase(phase)]
    return phases


def _run_phases(path: Path, lang: LangRun, phases: list[DetectorPhase]) -> tuple[list[Issue], dict[str, int]]:
    issues: list[Issue] = []
    all_potentials: dict[str, int] = {}

    total = len(phases)
    for idx, phase in enumerate(phases, start=1):
        _stderr(f"  [{idx}/{total}] {phase.label}...")
        phase_issues, phase_potentials = phase.run(path, lang)
        all_potentials.update(phase_potentials)
        issues.extend(phase_issues)

    return issues, all_potentials


def _stamp_issue_context(issues: list[Issue], lang: LangRun) -> None:
    if not issues:
        return

    zone_policies = None
    if lang.zone_map is not None:
        zone_policies = ZONE_POLICIES

    for issue in issues:
        issue["lang"] = lang.name
        if lang.zone_map is None:
            continue

        zone = lang.zone_map.get(issue.get("file", ""))
        issue["zone"] = zone.value
        policy = zone_policies.get(zone) if zone_policies else None
        if policy and issue.get("detector") in policy.downgrade_detectors:
            issue["confidence"] = "low"


def _generate_issues_from_lang(
    path: Path,
    lang: LangRun,
    *,
    include_slow: bool = True,
    zone_overrides: dict[str, str] | None = None,
    profile: str = "full",
) -> tuple[list[Issue], dict[str, int]]:
    """Run detector phases from a LangRun."""
    _build_zone_map(path, lang, zone_overrides)
    phases = _select_phases(lang, include_slow=include_slow, profile=profile)
    prewarm_review_phase_detectors(path, lang, phases)
    try:
        issues, all_potentials = _run_phases(path, lang, phases)
    finally:
        clear_review_phase_prefetch(lang)
    _stamp_issue_context(issues, lang)
    _stderr(f"\n  Total: {len(issues)} issues")
    return issues, all_potentials


def generate_issues(
    path: Path,
    lang: LangConfig | LangRun | None = None,
    *,
    options: PlanScanOptions | None = None,
) -> tuple[list[Issue], dict[str, int]]:
    """Run all detectors and convert results to normalized issues."""
    resolved_options = options or PlanScanOptions()

    resolved_lang = _resolve_lang(lang, get_project_root())
    runtime_lang = make_lang_run(resolved_lang)
    return _generate_issues_from_lang(
        path,
        runtime_lang,
        include_slow=resolved_options.include_slow,
        zone_overrides=resolved_options.zone_overrides,
        profile=resolved_options.profile,
    )
