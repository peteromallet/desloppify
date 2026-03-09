"""Flag/config validation helpers for review import flows."""

from __future__ import annotations

from dataclasses import dataclass

from desloppify import state as state_mod
from desloppify.intelligence.review.dimensions import normalize_dimension_name
from desloppify.intelligence.review.importing.contracts_types import ReviewImportPayload

from . import helpers as import_helpers_mod


class ImportFlagValidationError(ValueError):
    """Raised when review import CLI flags are mutually incompatible."""


@dataclass(frozen=True)
class ReviewImportConfig:
    """Configuration bundle for review import/validate flows."""

    config: dict | None = None
    allow_partial: bool = False
    trusted_assessment_source: bool = False
    trusted_assessment_label: str | None = None
    attested_external: bool = False
    manual_override: bool = False
    manual_attest: str | None = None


def build_import_load_config(
    *,
    lang_name: str | None,
    import_config: ReviewImportConfig,
    override_enabled: bool,
    override_attest: str | None,
) -> import_helpers_mod.ImportLoadConfig:
    return import_helpers_mod.ImportLoadConfig(
        lang_name=lang_name,
        allow_partial=import_config.allow_partial,
        trusted_assessment_source=import_config.trusted_assessment_source,
        trusted_assessment_label=import_config.trusted_assessment_label,
        attested_external=import_config.attested_external,
        manual_override=override_enabled,
        manual_attest=override_attest,
    )


def validate_import_flag_combos(
    *,
    attested_external: bool,
    allow_partial: bool,
    override_enabled: bool,
    override_attest: str | None,
) -> None:
    """Fail fast on conflicting import flags to keep behavior explicit."""
    if attested_external and override_enabled:
        raise ImportFlagValidationError(
            "--attested-external cannot be combined with --manual-override"
        )
    if attested_external and allow_partial:
        raise ImportFlagValidationError(
            "--attested-external cannot be combined with --allow-partial"
        )
    if override_enabled and allow_partial:
        raise ImportFlagValidationError(
            "--manual-override cannot be combined with --allow-partial"
        )
    if override_enabled and (
        not isinstance(override_attest, str) or not override_attest.strip()
    ):
        raise ImportFlagValidationError("--manual-override requires --attest")


def imported_assessment_keys(issues_data: ReviewImportPayload) -> set[str]:
    """Return normalized assessment dimension keys from payload."""
    raw_assessments = issues_data["assessments"]
    keys: set[str] = set()
    for raw_key in raw_assessments:
        normalized = normalize_dimension_name(str(raw_key))
        if normalized:
            keys.add(normalized)
    return keys


def mark_manual_override_assessments_provisional(
    state: dict,
    *,
    assessment_keys: set[str],
) -> int:
    """Mark imported manual override assessments as provisional until next scan."""
    if not assessment_keys:
        return 0
    store = state.get("subjective_assessments")
    if not isinstance(store, dict):
        return 0

    now = state_mod.utc_now()
    expires_scan = int(state.get("scan_count", 0) or 0) + 1
    marked = 0
    for key in sorted(assessment_keys):
        payload = store.get(key)
        if not isinstance(payload, dict):
            continue
        payload["source"] = "manual_override"
        payload["assessed_at"] = now
        payload["provisional_override"] = True
        payload["provisional_until_scan"] = expires_scan
        payload.pop("placeholder", None)
        marked += 1
    return marked


def clear_provisional_override_flags(
    state: dict,
    *,
    assessment_keys: set[str],
) -> int:
    """Clear provisional override flags when trusted assessments replace them."""
    if not assessment_keys:
        return 0
    store = state.get("subjective_assessments")
    if not isinstance(store, dict):
        return 0

    cleared = 0
    for key in sorted(assessment_keys):
        payload = store.get(key)
        if not isinstance(payload, dict):
            continue
        if payload.pop("provisional_override", None) is not None:
            cleared += 1
        payload.pop("provisional_until_scan", None)
        if payload.get("source") == "manual_override":
            payload["source"] = "holistic"
    return cleared


__all__ = [
    "ImportFlagValidationError",
    "ReviewImportConfig",
    "build_import_load_config",
    "clear_provisional_override_flags",
    "imported_assessment_keys",
    "mark_manual_override_assessments_provisional",
    "validate_import_flag_combos",
]
