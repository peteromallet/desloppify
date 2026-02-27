"""Coverage-confidence helpers used by scan workflow."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.languages._framework.base.types import DetectorCoverageRecord
from desloppify.languages._framework.runtime import LangRun


def coerce_int(value: object, *, default: int) -> int:
    """Best-effort int coercion for config values."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return int(text)
            except ValueError:
                return default
    return default


def coerce_float(value: object, *, default: float) -> float:
    """Best-effort float coercion for scan metadata payloads."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return float(text)
            except ValueError:
                return default
    return default


def normalize_coverage_warning(raw: object) -> DetectorCoverageRecord | None:
    """Normalize runtime coverage payloads to a stable typed shape."""
    if raw is None:
        return None

    if hasattr(raw, "__dataclass_fields__"):
        payload = {
            key: getattr(raw, key)
            for key in getattr(raw, "__dataclass_fields__", {})
            if hasattr(raw, key)
        }
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        return None

    detector = str(payload.get("detector", "") or "").strip()
    if not detector:
        return None

    status = str(payload.get("status", "full") or "full").strip().lower()
    confidence = coerce_float(payload.get("confidence"), default=1.0)
    summary = str(payload.get("summary", "") or "").strip()
    impact = str(payload.get("impact", "") or "").strip()
    remediation = str(payload.get("remediation", "") or "").strip()
    tool = str(payload.get("tool", "") or "").strip()
    reason = str(payload.get("reason", "") or "").strip()

    return {
        "detector": detector,
        "status": "reduced" if status == "reduced" or confidence < 1.0 else "full",
        "confidence": max(0.0, min(1.0, confidence)),
        "summary": summary,
        "impact": impact,
        "remediation": remediation,
        "tool": tool,
        "reason": reason,
    }


def seed_runtime_coverage_warnings(lang: LangRun | None) -> list[DetectorCoverageRecord]:
    """Collect preflight scan-coverage warnings and seed runtime coverage state."""
    if lang is None:
        return []

    warnings: list[DetectorCoverageRecord] = []
    raw_entries = lang.scan_coverage_prerequisites()
    for raw in raw_entries:
        normalized = normalize_coverage_warning(raw)
        if normalized is None:
            continue
        detector = str(normalized.get("detector", "")).strip()
        if detector:
            lang.detector_coverage[detector] = dict(normalized)
        if normalized.get("status") == "reduced":
            warnings.append(dict(normalized))
    lang.coverage_warnings = warnings
    return warnings


def persist_scan_coverage(
    state: state_mod.StateModel,
    lang: LangRun | None,
) -> None:
    """Persist detector coverage confidence for the active language scan."""
    if lang is None:
        return

    detectors: dict[str, DetectorCoverageRecord] = {}
    for detector, payload in lang.detector_coverage.items():
        normalized = normalize_coverage_warning(payload)
        if normalized is None:
            continue
        detectors[str(detector)] = normalized

    warnings: list[DetectorCoverageRecord] = []
    for warning in lang.coverage_warnings:
        normalized_warning = normalize_coverage_warning(warning)
        if normalized_warning is not None and normalized_warning.get("status") == "reduced":
            warnings.append(normalized_warning)

    reduced_entries = [
        payload
        for payload in detectors.values()
        if payload.get("status") == "reduced"
    ]
    if reduced_entries:
        confidence = min(
            coerce_float(entry.get("confidence"), default=1.0)
            for entry in reduced_entries
        )
        status = "reduced"
    else:
        confidence = 1.0
        status = "full"

    state.setdefault("scan_coverage", {})[lang.name] = {
        "status": status,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "detectors": detectors,
        "warnings": warnings,
        "updated_at": state_mod.utc_now(),
    }


__all__ = [
    "coerce_float",
    "coerce_int",
    "normalize_coverage_warning",
    "persist_scan_coverage",
    "seed_runtime_coverage_warnings",
]
