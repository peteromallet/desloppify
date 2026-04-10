"""Top-level batch building APIs for holistic review preparation."""

from __future__ import annotations

from pathlib import Path

from .personas import assign_personas
from .prepare_batches_collectors import _DIMENSION_FILE_MAPPING
from .prepare_batches_core import (
    _ensure_holistic_context,
    _normalize_file_path,
)


def _count_findings_for_dimensions(
    state: dict,
    dimensions: list[str],
) -> tuple[dict[str, int], dict[str, int]]:
    """Count open findings for detectors relevant to the given dimensions.

    Returns (judgment_counts, mechanical_counts) keyed by detector name.
    """
    from desloppify.base.registry import JUDGMENT_DETECTORS, dimension_to_detectors

    dim_detectors = dimension_to_detectors()
    relevant: set[str] = set()
    for dim in dimensions:
        relevant.update(dim_detectors.get(dim, ()))
    if not relevant:
        return {}, {}

    issues = state.get("work_items")
    if not isinstance(issues, dict):
        return {}, {}

    judgment: dict[str, int] = {}
    mechanical: dict[str, int] = {}
    for issue in issues.values():
        if not isinstance(issue, dict):
            continue
        status = str(issue.get("status", "")).strip()
        if status not in ("open", "reopened"):
            continue
        detector = str(issue.get("detector", "")).strip()
        if detector not in relevant:
            continue
        target = judgment if detector in JUDGMENT_DETECTORS else mechanical
        target[detector] = target.get(detector, 0) + 1

    return judgment, mechanical


def build_investigation_batches(
    holistic_ctx,
    lang: object,
    *,
    repo_root: Path | None = None,
    max_files_per_batch: int | None = None,
    state: dict | None = None,
) -> list[dict]:
    """Build one batch per dimension from holistic context."""
    _ensure_holistic_context(holistic_ctx)
    del lang
    del repo_root
    del max_files_per_batch

    batches: list[dict] = []

    for dimension in _DIMENSION_FILE_MAPPING:
        batch: dict[str, object] = {
            "name": dimension,
            "dimensions": [dimension],
            "why": f"{dimension} review",
        }

        if state is not None:
            j_counts, m_counts = _count_findings_for_dimensions(state, [dimension])
            if j_counts:
                batch["judgment_finding_counts"] = j_counts
            if m_counts:
                batch["mechanical_finding_counts"] = m_counts

        batches.append(batch)

    personas = assign_personas(len(batches))
    for batch, persona in zip(batches, personas):
        if persona is not None:
            batch["persona"] = persona.name

    return batches


def filter_batches_to_dimensions(
    batches: list[dict],
    dimensions: list[str],
    *,
    fallback_max_files: int | None = 80,
) -> list[dict]:
    """Keep only batches whose dimension is in the active set."""
    del fallback_max_files
    selected = [dimension for dimension in dimensions if isinstance(dimension, str) and dimension]
    if not selected:
        return []
    selected_set = set(selected)
    filtered: list[dict] = []
    covered: set[str] = set()
    for batch in batches:
        batch_dims = [dim for dim in batch.get("dimensions", []) if dim in selected_set]
        if not batch_dims:
            continue
        filtered.append({**batch, "dimensions": batch_dims})
        covered.update(batch_dims)

    # Create empty batches for dimensions not covered by existing batches
    missing = [dim for dim in selected if dim not in covered]
    for dim in missing:
        filtered.append(
            {
                "name": dim,
                "dimensions": [dim],
                "why": f"{dim} review",
            }
        )
    return filtered


def batch_concerns(
    concerns: list,
    *,
    max_files: int | None = None,
    active_dimensions: list[str] | None = None,
) -> dict | None:
    """Build investigation batch from mechanical concern signals."""
    del active_dimensions
    if not concerns:
        return None

    types = sorted({concern.type for concern in concerns if concern.type})
    why_parts = ["mechanical detectors identified structural patterns needing judgment"]
    if types:
        why_parts.append(f"concern types: {', '.join(types)}")

    files: list[str] = []
    seen: set[str] = set()
    concern_signals: list[dict[str, object]] = []
    for concern in concerns:
        candidate = _normalize_file_path(getattr(concern, "file", ""))
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        files.append(candidate)

        evidence_raw = getattr(concern, "evidence", ())
        evidence = [
            str(entry).strip()
            for entry in evidence_raw
            if isinstance(entry, str) and entry.strip()
        ][:4]
        summary = str(getattr(concern, "summary", "")).strip()
        question = str(getattr(concern, "question", "")).strip()
        concern_type = str(getattr(concern, "type", "")).strip()
        fingerprint = str(getattr(concern, "fingerprint", "")).strip()
        source_issues = tuple(
            str(sid)
            for sid in getattr(concern, "source_issues", ())
            if isinstance(sid, str) and sid
        )
        signal: dict[str, object] = {
            "type": concern_type or "design_concern",
            "file": candidate,
            "summary": summary or "Mechanical concern requires subjective judgment",
            "question": question or "Is this pattern intentional or debt?",
            "evidence": evidence,
        }
        if fingerprint:
            signal["fingerprint"] = fingerprint
        if source_issues:
            signal["finding_ids"] = list(source_issues)
        concern_signals.append(signal)

    # Build per-detector judgment finding counts by extracting the detector name
    # from each source issue ID (format: "detector::file::detail").
    detector_counts: dict[str, int] = {}
    seen_source_ids: set[str] = set()
    for concern in concerns:
        for sid in getattr(concern, "source_issues", ()):
            sid_str = str(sid)
            if sid_str in seen_source_ids:
                continue
            seen_source_ids.add(sid_str)
            detector = sid_str.split("::", 1)[0] if "::" in sid_str else ""
            if detector:
                detector_counts[detector] = detector_counts.get(detector, 0) + 1

    result: dict[str, object] = {
        "name": "design_coherence",
        "dimensions": ["design_coherence"],
        "why": "; ".join(why_parts),
        "concern_signals": concern_signals,
        "concern_signal_count": len(concern_signals),
    }
    if detector_counts:
        result["judgment_finding_counts"] = detector_counts
    return result


__all__ = [
    "batch_concerns",
    "build_investigation_batches",
    "filter_batches_to_dimensions",
]
