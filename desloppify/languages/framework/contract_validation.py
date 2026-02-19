"""Runtime contract validation for LangConfig plugins."""

from __future__ import annotations

from desloppify.languages.framework.base.types import (
    DetectorPhase,
    FixerConfig,
    LangConfig,
    LangValueSpec,
)
from desloppify.languages.framework.policy import ALLOWED_SCAN_PROFILES


def _validate_core_identity(name: str, cfg: LangConfig) -> list[str]:
    errors: list[str] = []
    if cfg.name != name:
        errors.append(f"config name mismatch: expected '{name}', got '{cfg.name}'")
    if not cfg.extensions:
        errors.append("extensions must be non-empty")
    if not callable(cfg.build_dep_graph):
        errors.append("build_dep_graph must be callable")
    if not callable(cfg.file_finder):
        errors.append("file_finder must be callable")
    if not callable(cfg.extract_functions):
        errors.append("extract_functions must be callable")
    if cfg.default_scan_profile not in ALLOWED_SCAN_PROFILES:
        allowed = ", ".join(sorted(ALLOWED_SCAN_PROFILES))
        errors.append(f"default_scan_profile must be one of: {allowed}")
    return errors


def _validate_phases(cfg: LangConfig) -> list[str]:
    errors: list[str] = []
    if not cfg.phases:
        errors.append("phases must be non-empty")
        return errors

    for idx, phase in enumerate(cfg.phases):
        if not isinstance(phase, DetectorPhase):
            errors.append(f"phase[{idx}] is not DetectorPhase")
            continue
        if not isinstance(phase.label, str) or not phase.label.strip():
            errors.append(f"phase[{idx}] has empty label")
        if not callable(phase.run):
            errors.append(f"phase[{idx}] run must be callable")
    return errors


def _validate_detect_commands(cfg: LangConfig) -> list[str]:
    errors: list[str] = []
    if not isinstance(cfg.detect_commands, dict) or not cfg.detect_commands:
        errors.append("detect_commands must be a non-empty dict")
        return errors

    for key, fn in cfg.detect_commands.items():
        if not isinstance(key, str) or not key.strip():
            errors.append("detect_commands has empty/non-string key")
        elif (
            key != key.lower()
            or "-" in key
            or not all(ch.isalnum() or ch == "_" for ch in key)
        ):
            errors.append(f"detect command '{key}' must use lowercase snake_case")
        if not callable(fn):
            errors.append(f"detect command '{key}' is not callable")
    return errors


def _validate_fixers(cfg: LangConfig) -> list[str]:
    errors: list[str] = []
    if not isinstance(cfg.fixers, dict):
        errors.append("fixers must be a dict")
        return errors

    for key, fixer in cfg.fixers.items():
        if not isinstance(fixer, FixerConfig):
            errors.append(f"fixer '{key}' is not FixerConfig")
    return errors


def _validate_setting_specs(cfg: LangConfig) -> list[str]:
    errors: list[str] = []
    if not isinstance(cfg.setting_specs, dict):
        errors.append("setting_specs must be a dict")
        return errors

    for key, spec in cfg.setting_specs.items():
        if not isinstance(key, str) or not key.strip():
            errors.append("setting_specs has empty/non-string key")
        if not isinstance(spec, LangValueSpec):
            errors.append(f"setting_specs['{key}'] is not LangValueSpec")
    return errors


def _validate_runtime_option_specs(cfg: LangConfig) -> list[str]:
    errors: list[str] = []
    if not isinstance(cfg.runtime_option_specs, dict):
        errors.append("runtime_option_specs must be a dict")
        return errors

    for key, spec in cfg.runtime_option_specs.items():
        if not isinstance(key, str) or not key.strip():
            errors.append("runtime_option_specs has empty/non-string key")
        if not isinstance(spec, LangValueSpec):
            errors.append(f"runtime_option_specs['{key}'] is not LangValueSpec")
    return errors


def _validate_zone_rules(cfg: LangConfig) -> list[str]:
    return [] if cfg.zone_rules else ["zone_rules must be non-empty"]


def validate_lang_contract(name: str, cfg: LangConfig) -> None:
    """Validate LangConfig runtime contract so broken plugins fail fast."""
    errors: list[str] = []

    if not isinstance(cfg, LangConfig):
        errors.append(f"plugin class for '{name}' must return LangConfig")
    else:
        errors.extend(_validate_core_identity(name, cfg))
        errors.extend(_validate_phases(cfg))
        errors.extend(_validate_detect_commands(cfg))
        errors.extend(_validate_fixers(cfg))
        errors.extend(_validate_setting_specs(cfg))
        errors.extend(_validate_runtime_option_specs(cfg))
        errors.extend(_validate_zone_rules(cfg))

    if errors:
        raise ValueError(
            f"Language plugin '{name}' has invalid LangConfig contract:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
