"""Finding generation pipeline (phase execution and normalization)."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

from desloppify.engine.planning.common import is_subjective_phase
from desloppify.languages.framework.base.types import LangConfig
from desloppify.languages.framework.runtime import LangRun, make_lang_run
from desloppify.utils import colorize


@dataclass
class PlanScanOptions:
    """Config object for scan execution behavior."""

    include_slow: bool = True
    zone_overrides: dict[str, str] | None = None
    profile: str = "full"


def _stderr(msg: str) -> None:
    print(colorize(msg, "dim"), file=sys.stderr)


def _resolve_lang(lang, project_root: Path):
    if lang is not None:
        return lang

    lang_mod = importlib.import_module("desloppify.languages")

    detected = lang_mod.auto_detect_lang(project_root)
    if detected is None:
        langs = lang_mod.available_langs()
        if not langs:
            raise ValueError("No language plugins available")
        detected = langs[0]
    return lang_mod.get_lang(detected)


def _build_zone_map(path: Path, lang, zone_overrides: dict[str, str] | None) -> None:
    if not (lang.zone_rules and lang.file_finder):
        return

    utils_mod = importlib.import_module("desloppify.utils")
    zones_mod = importlib.import_module("desloppify.engine.policy.zones")

    files = lang.file_finder(path)
    lang.zone_map = zones_mod.FileZoneMap(
        files, lang.zone_rules, rel_fn=utils_mod.rel, overrides=zone_overrides
    )
    counts = lang.zone_map.counts()
    zone_str = ", ".join(
        f"{zone}: {count}" for zone, count in sorted(counts.items()) if count > 0
    )
    _stderr(f"  Zones: {zone_str}")


def _select_phases(lang, *, include_slow: bool, profile: str):
    active_profile = profile if profile in {"objective", "full", "ci"} else "full"
    phases = lang.phases
    if not include_slow or active_profile == "ci":
        phases = [phase for phase in phases if not phase.slow]
    if active_profile in {"objective", "ci"}:
        phases = [phase for phase in phases if not is_subjective_phase(phase)]
    return phases


def _run_phases(path: Path, lang, phases) -> tuple[list[dict], dict[str, int]]:
    findings: list[dict] = []
    all_potentials: dict[str, int] = {}

    total = len(phases)
    for idx, phase in enumerate(phases, start=1):
        _stderr(f"  [{idx}/{total}] {phase.label}...")
        phase_findings, phase_potentials = phase.run(path, lang)
        all_potentials.update(phase_potentials)
        findings.extend(phase_findings)

    return findings, all_potentials


def _stamp_finding_context(findings: list[dict], lang) -> None:
    if not findings:
        return

    zone_policies = None
    if lang.zone_map is not None:
        zones_mod = importlib.import_module("desloppify.engine.policy.zones")
        zone_policies = zones_mod.ZONE_POLICIES

    for finding in findings:
        finding["lang"] = lang.name
        if lang.zone_map is None:
            continue

        zone = lang.zone_map.get(finding.get("file", ""))
        finding["zone"] = zone.value
        policy = zone_policies.get(zone) if zone_policies else None
        if policy and finding.get("detector") in policy.downgrade_detectors:
            finding["confidence"] = "low"


def _generate_findings_from_lang(
    path: Path,
    lang,
    *,
    include_slow: bool = True,
    zone_overrides: dict[str, str] | None = None,
    profile: str = "full",
) -> tuple[list[dict], dict[str, int]]:
    """Run detector phases from a LangRun."""
    _build_zone_map(path, lang, zone_overrides)
    phases = _select_phases(lang, include_slow=include_slow, profile=profile)
    findings, all_potentials = _run_phases(path, lang, phases)
    _stamp_finding_context(findings, lang)
    _stderr(f"\n  Total: {len(findings)} findings")
    return findings, all_potentials


def generate_findings(
    path: Path,
    lang: LangConfig | LangRun | None = None,
    *,
    options: PlanScanOptions | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Run all detectors and convert results to normalized findings."""
    utils_mod = importlib.import_module("desloppify.utils")
    resolved_options = options or PlanScanOptions()

    resolved_lang = _resolve_lang(lang, utils_mod.PROJECT_ROOT)
    runtime_lang = make_lang_run(resolved_lang)
    return _generate_findings_from_lang(
        path,
        runtime_lang,
        include_slow=resolved_options.include_slow,
        zone_overrides=resolved_options.zone_overrides,
        profile=resolved_options.profile,
    )
