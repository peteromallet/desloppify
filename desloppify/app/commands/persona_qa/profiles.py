"""Persona profile loading and validation."""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from desloppify.base.discovery.paths import get_project_root


def _personas_dir() -> Path:
    """Return the personas directory path."""
    return get_project_root() / ".desloppify" / "personas"


def discover_profiles() -> list[Path]:
    """Find all persona YAML profiles in .desloppify/personas/."""
    d = _personas_dir()
    if not d.is_dir():
        return []
    return sorted(d.glob("*.yaml"))


def _require_yaml() -> None:
    if yaml is None:
        raise ImportError(
            "PyYAML is required for persona QA profiles. "
            "Install it with: pip install pyyaml"
        )


def load_profile(path: Path) -> dict[str, Any]:
    """Load and validate a single persona profile from YAML."""
    _require_yaml()
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Persona profile {path.name} must be a YAML mapping")
    _validate_profile(data, path.name)
    return data


def _validate_profile(data: dict[str, Any], filename: str) -> None:
    """Validate required fields in a persona profile."""
    for field in ("name", "description", "scenarios"):
        if field not in data:
            raise ValueError(
                f"Persona profile {filename} missing required field: {field}"
            )
    scenarios = data["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(
            f"Persona profile {filename} must have at least one scenario"
        )
    for i, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            raise ValueError(
                f"Persona profile {filename} scenario {i} must be a mapping"
            )
        for field in ("name", "start", "goal", "check"):
            if field not in scenario:
                raise ValueError(
                    f"Persona profile {filename} scenario {i} missing: {field}"
                )
        checks = scenario["check"]
        if not isinstance(checks, list) or not checks:
            raise ValueError(
                f"Persona profile {filename} scenario {i} must have at least one check"
            )


def load_all_profiles(*, persona_filter: str | None = None) -> list[dict[str, Any]]:
    """Load all persona profiles, optionally filtered by name."""
    paths = discover_profiles()
    if not paths:
        raise FileNotFoundError(
            f"No persona profiles found in {_personas_dir()}. "
            "Create .desloppify/personas/*.yaml files."
        )
    profiles = []
    for path in paths:
        profile = load_profile(path)
        if persona_filter and profile["name"].lower() != persona_filter.lower():
            # Also match by filename stem
            if path.stem.lower().replace("-", " ") != persona_filter.lower().replace("-", " "):
                continue
        profiles.append(profile)

    if persona_filter and not profiles:
        available = [p.stem for p in paths]
        raise ValueError(
            f"No persona profile matching '{persona_filter}'. "
            f"Available: {', '.join(available)}"
        )
    return profiles


def total_check_items(profiles: list[dict[str, Any]]) -> int:
    """Count total check items across all personas for scoring denominator."""
    total = 0
    for profile in profiles:
        for scenario in profile.get("scenarios", []):
            total += len(scenario.get("check", []))
        total += len(profile.get("accessibility", []))
    return total


__all__ = [
    "discover_profiles",
    "load_all_profiles",
    "load_profile",
    "total_check_items",
]
