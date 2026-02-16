"""Finding import: import_review_findings, import_holistic_findings, assessments."""

from __future__ import annotations

import hashlib

from ..state import make_finding, merge_scan, utc_now
from ..utils import PROJECT_ROOT
from .dimensions import normalize_dimension_name
from .policy import (
    append_custom_dimensions,
    build_dimension_policy,
    is_allowed_dimension,
    normalize_assessment_inputs,
)


# Import-integrity tuning for assessment-only score swings.
INTEGRITY_DELTA_THRESHOLD = 35.0
INTEGRITY_MAX_DIM_DELTA = 25.0
_PROVENANCE_KEYS = (
    "reviewer_id",
    "prompt_hash",
    "model",
    "tool_version",
    "timestamp",
    "run_id",
)


class AssessmentImportIntegrityError(ValueError):
    """Raised when assessment imports fail integrity validation."""


# ── Assessment integrity + provenance helpers ─────────────────────

def _normalize_assessment_scores(raw: dict | None) -> dict[str, float]:
    """Normalize assessment payload to ``{dimension: score}``."""
    if not raw:
        return {}
    normalized: dict[str, float] = {}
    for dim_name, value in raw.items():
        canonical = normalize_dimension_name(str(dim_name))
        if not canonical:
            continue
        score = value if isinstance(value, (int, float)) else value.get("score", 0)
        normalized[canonical] = float(max(0, min(100, score)))
    return normalized


def _extract_import_provenance(findings_data: list[dict] | dict) -> dict:
    """Extract provenance metadata from an import payload."""
    if not isinstance(findings_data, dict):
        return {}
    provenance: dict = {}
    payload_prov = findings_data.get("provenance")
    if isinstance(payload_prov, dict):
        for key in _PROVENANCE_KEYS:
            if payload_prov.get(key):
                provenance[key] = payload_prov[key]
    for key in _PROVENANCE_KEYS:
        if key in findings_data and findings_data.get(key):
            provenance[key] = findings_data[key]
    return provenance


def validate_assessment_import_integrity(
    state: dict,
    findings_data: list[dict] | dict,
    *,
    mode: str,
    allow_override: bool = False,
    override_note: str | None = None,
    policy=None,
) -> dict:
    """Validate whether an assessment import is plausibly evidence-backed.

    Guardrail: if prior assessments exist, and a new import makes a large
    aggregate assessment swing without any findings payload, block unless an
    explicit override + note is provided.
    """
    if not isinstance(findings_data, dict):
        return {}

    assessments = findings_data.get("assessments") or {}
    if not isinstance(assessments, dict) or not assessments:
        return {}

    previous = _normalize_assessment_scores(state.get("subjective_assessments") or {})
    if not previous:
        return {"checked": False, "reason": "no_prior_assessments"}

    effective_policy = policy or build_dimension_policy(
        state=state,
        config=(state.get("config") if isinstance(state.get("config"), dict) else None),
        allow_custom_dimensions=False,
    )
    normalized_assessments, _skipped, _new_custom = normalize_assessment_inputs(
        assessments,
        policy=effective_policy,
    )
    incoming = _normalize_assessment_scores(normalized_assessments)
    deltas: dict[str, float] = {}
    for dim_name, new_score in incoming.items():
        old_score = previous.get(dim_name, 0.0)
        delta = round(new_score - old_score, 1)
        if abs(delta) >= 0.1:
            deltas[dim_name] = delta

    if not deltas:
        return {"checked": True, "reason": "no_score_change"}

    findings_list = findings_data.get("findings") or []
    finding_count = len(findings_list) if isinstance(findings_list, list) else 0
    aggregate_delta = round(sum(abs(d) for d in deltas.values()), 1)
    max_dim_delta = round(max(abs(d) for d in deltas.values()), 1)
    needs_integrity_override = (
        finding_count == 0
        and (
            aggregate_delta >= INTEGRITY_DELTA_THRESHOLD
            or max_dim_delta >= INTEGRITY_MAX_DIM_DELTA
        )
    )

    if needs_integrity_override and not allow_override:
        raise AssessmentImportIntegrityError(
            f"assessment import blocked ({mode}): large score swing without findings "
            f"(aggregate Δ={aggregate_delta}, max dimension Δ={max_dim_delta}). "
            f"Re-import with --assessment-override --assessment-note \"<reason>\" if intentional."
        )
    if needs_integrity_override and not (override_note or "").strip():
        raise AssessmentImportIntegrityError(
            "assessment import override requires --assessment-note to document rationale."
        )

    return {
        "checked": True,
        "mode": mode,
        "changed_dimensions": sorted(deltas.keys()),
        "aggregate_delta": aggregate_delta,
        "max_dimension_delta": max_dim_delta,
        "finding_count": finding_count,
        "override_used": bool(needs_integrity_override and allow_override),
        "override_note": (override_note or "").strip() if needs_integrity_override else "",
    }


# ── Assessment storage ─────────────────────────────────────────────

def _store_assessments(
    state: dict,
    assessments: dict,
    source: str,
    provenance: dict | None = None,
    *,
    allow_custom_dimensions: bool = False,
    policy=None,
) -> dict[str, list[str]]:
    """Store dimension assessments in state.

    *assessments*: ``{dim_name: score}`` or ``{dim_name: {score, ...}}``.
    *source*: ``"per_file"`` or ``"holistic"``.

    Holistic assessments overwrite per-file for the same dimension.
    Per-file assessments don't overwrite holistic.
    """
    store = state.setdefault("subjective_assessments", {})
    effective_policy = policy or build_dimension_policy(
        state=state,
        config=(state.get("config") if isinstance(state.get("config"), dict) else None),
        allow_custom_dimensions=allow_custom_dimensions,
    )
    normalized_assessments, skipped, discovered_custom = normalize_assessment_inputs(
        assessments,
        policy=effective_policy,
    )
    append_custom_dimensions(state, discovered_custom)
    now = utc_now()
    stored: list[str] = []

    for normalized_dim, value in normalized_assessments.items():
        score = value if isinstance(value, (int, float)) else value.get("score", 0)
        score = max(0, min(100, score))
        per_dim_provenance: dict = {}
        if isinstance(provenance, dict):
            for key in _PROVENANCE_KEYS:
                if provenance.get(key):
                    per_dim_provenance[key] = provenance[key]
        if isinstance(value, dict):
            nested = value.get("provenance")
            if isinstance(nested, dict):
                for key in _PROVENANCE_KEYS:
                    if nested.get(key):
                        per_dim_provenance[key] = nested[key]
            for key in _PROVENANCE_KEYS:
                if value.get(key):
                    per_dim_provenance[key] = value[key]

        existing = store.get(normalized_dim)
        if existing and existing.get("source") == "holistic" and source == "per_file":
            continue  # Don't overwrite holistic with per-file

        if per_dim_provenance:
            store[normalized_dim] = {
                "score": score,
                "source": source,
                "assessed_at": now,
                "provenance": per_dim_provenance,
            }
        else:
            store[normalized_dim] = {
                "score": score,
                "source": source,
                "assessed_at": now,
            }
        stored.append(normalized_dim)

    return {
        "stored": sorted(set(stored)),
        "skipped": sorted(set(skipped)),
    }


def _extract_findings_and_assessments(
    data: list[dict] | dict,
) -> tuple[list[dict], dict | None]:
    """Parse import data, accepting both legacy (list) and new (dict) formats.

    Legacy: ``[{finding}, ...]``
    New:    ``{"assessments": {...}, "findings": [{finding}, ...]}``

    Returns ``(findings_list, assessments_or_none)``.
    """
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        return data.get("findings", []), data.get("assessments") or None
    return [], None


# ── Per-file finding import ───────────────────────────────────────

def import_review_findings(
    findings_data: list[dict] | dict,
    state: dict,
    lang_name: str,
    *,
    allow_custom_dimensions: bool = False,
    policy=None,
) -> dict:
    """Import agent-produced review findings into state.

    Accepts either a bare list of findings (legacy) or a dict with
    ``"assessments"`` and ``"findings"`` keys (new format).

    Validates structure, creates Finding objects, merges into state.
    Returns diff summary.
    """
    findings_list, assessments = _extract_findings_and_assessments(findings_data)
    effective_policy = policy or build_dimension_policy(
        state=state,
        config=(state.get("config") if isinstance(state.get("config"), dict) else None),
        allow_custom_dimensions=allow_custom_dimensions,
    )
    provenance = _extract_import_provenance(findings_data)
    assessment_meta = {"stored": [], "skipped": []}
    if assessments:
        assessment_meta = _store_assessments(
            state,
            assessments,
            source="per_file",
            provenance=provenance,
            allow_custom_dimensions=allow_custom_dimensions,
            policy=effective_policy,
        )

    review_findings = []
    skipped: list[dict] = []
    required_fields = ("file", "dimension", "identifier", "summary", "confidence")
    for idx, f in enumerate(findings_list):
        # Validate required fields
        missing = [k for k in required_fields if k not in f]
        if missing:
            skipped.append({"index": idx, "missing": missing,
                            "identifier": f.get("identifier", "<none>")})
            continue

        # Validate confidence value
        confidence = f.get("confidence", "low")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        # Validate dimension
        raw_dimension = str(f["dimension"])
        dimension = normalize_dimension_name(raw_dimension)
        if not is_allowed_dimension(dimension, holistic=False, policy=effective_policy):
            skipped.append({"index": idx, "missing": [f"invalid dimension: {raw_dimension}"],
                            "identifier": f.get("identifier", "<none>")})
            continue

        content_hash = hashlib.sha256(f["summary"].encode()).hexdigest()[:8]
        finding = make_finding(
            detector="review",
            file=str(PROJECT_ROOT / f["file"]),  # make_finding calls rel() internally
            name=f"{dimension}::{f['identifier']}::{content_hash}",
            tier=3,  # Always judgment-required
            confidence=confidence,
            summary=f["summary"],
            detail={
                "dimension": dimension,
                "evidence": f.get("evidence", []),
                "suggestion": f.get("suggestion", ""),
                "reasoning": f.get("reasoning", ""),
                "evidence_lines": f.get("evidence_lines", []),
            },
        )
        finding["lang"] = lang_name
        review_findings.append(finding)

    # Count files evaluated for potentials
    reviewed_files = set(f["file"] for f in findings_list
                         if all(k in f for k in ("file", "dimension", "identifier",
                                                   "summary", "confidence")))
    pots = state.setdefault("potentials", {}).setdefault(lang_name, {})
    pots["review"] = len(reviewed_files)

    # Pass only review potential so merge_scan knows only 'review' ran —
    # protects other detectors' findings from being auto-resolved.
    # (pots is a reference to state["potentials"][lang] which has ALL detectors)
    diff = merge_scan(
        state, review_findings,
        lang=lang_name,
        potentials={"review": pots.get("review", 0)},
        merge_potentials=True,
    )

    # Auto-resolve per-file review findings for re-reviewed files that no longer
    # have findings — the reviewer saw the file and found nothing wrong.
    new_ids = {f["id"] for f in review_findings}
    reviewed_files = set(f["file"] for f in findings_list
                         if all(k in f for k in required_fields))
    for fid, f in state.get("findings", {}).items():
        if (f["status"] == "open" and f.get("detector") == "review"
                and not f.get("detail", {}).get("holistic")
                and f.get("file", "") in reviewed_files
                and fid not in new_ids):
            f["status"] = "auto_resolved"
            f["resolved_at"] = utc_now()
            f["note"] = "not reported in latest per-file re-import"
            diff["auto_resolved"] = diff.get("auto_resolved", 0) + 1

    # Track skipped findings in diff
    if skipped:
        diff["skipped"] = len(skipped)
        diff["skipped_details"] = skipped
    if assessment_meta.get("skipped"):
        diff["assessment_skipped_dimensions"] = assessment_meta["skipped"]
    if assessment_meta.get("stored"):
        diff["assessment_dimensions"] = assessment_meta["stored"]

    # Update review cache
    _update_review_cache(state, findings_list)

    return diff


def _update_review_cache(state: dict, findings_data: list[dict]):
    """Update per-file review cache with timestamps and content hashes."""
    from .selection import hash_file

    rc = state.setdefault("review_cache", {})
    file_cache = rc.setdefault("files", {})
    now = utc_now()

    reviewed_files = set(f["file"] for f in findings_data
                         if "file" in f)
    for filepath in reviewed_files:
        abs_path = PROJECT_ROOT / filepath
        content_hash = hash_file(str(abs_path)) if abs_path.exists() else ""
        file_findings = [f for f in findings_data if f.get("file") == filepath]
        file_cache[filepath] = {
            "content_hash": content_hash,
            "reviewed_at": now,
            "finding_count": len(file_findings),
        }


# ── Holistic finding import ──────────────────────────────────────

def import_holistic_findings(
    findings_data: list[dict] | dict,
    state: dict,
    lang_name: str,
    *,
    allow_custom_dimensions: bool = False,
    policy=None,
) -> dict:
    """Import holistic (codebase-wide) findings into state.

    Accepts either a bare list of findings (legacy) or a dict with
    ``"assessments"`` and ``"findings"`` keys (new format).

    Holistic findings have no `file` field — stored as file="." with
    detail.holistic=True and detail.related_files=[...].
    Returns diff summary.
    """
    from ..scoring import HOLISTIC_POTENTIAL

    findings_list, assessments = _extract_findings_and_assessments(findings_data)
    effective_policy = policy or build_dimension_policy(
        state=state,
        config=(state.get("config") if isinstance(state.get("config"), dict) else None),
        allow_custom_dimensions=allow_custom_dimensions,
    )
    provenance = _extract_import_provenance(findings_data)
    assessment_meta = {"stored": [], "skipped": []}
    if assessments:
        assessment_meta = _store_assessments(
            state,
            assessments,
            source="holistic",
            provenance=provenance,
            allow_custom_dimensions=allow_custom_dimensions,
            policy=effective_policy,
        )

    review_findings = []
    skipped: list[dict] = []
    holistic_required = ("dimension", "identifier", "summary", "confidence")
    for idx, f in enumerate(findings_list):
        # Validate required fields (no 'file' required for holistic)
        missing = [k for k in holistic_required if k not in f]
        if missing:
            skipped.append({"index": idx, "missing": missing,
                            "identifier": f.get("identifier", "<none>")})
            continue

        confidence = f.get("confidence", "low")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        raw_dimension = str(f["dimension"])
        dimension = normalize_dimension_name(raw_dimension)
        if not is_allowed_dimension(dimension, holistic=True, policy=effective_policy):
            skipped.append({"index": idx, "missing": [f"invalid dimension: {raw_dimension}"],
                            "identifier": f.get("identifier", "<none>")})
            continue

        related_files = f.get("related_files", [])

        content_hash = hashlib.sha256(f["summary"].encode()).hexdigest()[:8]
        # Use empty string for file — make_finding calls rel("") which returns "."
        finding = make_finding(
            detector="review",
            file="",
            name=f"holistic::{dimension}::{f['identifier']}::{content_hash}",
            tier=3,
            confidence=confidence,
            summary=f["summary"],
            detail={
                "holistic": True,
                "dimension": dimension,
                "related_files": related_files,
                "evidence": f.get("evidence", []),
                "suggestion": f.get("suggestion", ""),
                "reasoning": f.get("reasoning", ""),
            },
        )
        finding["lang"] = lang_name
        review_findings.append(finding)

    # Set holistic potential — fixed value, not cumulative across re-imports.
    pots = state.setdefault("potentials", {}).setdefault(lang_name, {})
    existing_review = pots.get("review", 0)
    # Holistic potential is additive to per-file potential, but capped at one
    # HOLISTIC_POTENTIAL increment (don't grow on repeated holistic imports).
    pots["review"] = max(existing_review, HOLISTIC_POTENTIAL)

    # Pass only review potential so merge_scan knows only 'review' ran —
    # protects other detectors' findings from being auto-resolved.
    diff = merge_scan(
        state, review_findings,
        lang=lang_name,
        potentials={"review": pots.get("review", 0)},
        merge_potentials=True,
    )

    # Auto-resolve old holistic findings not in the new import
    new_ids = {f["id"] for f in review_findings}
    for fid, f in state.get("findings", {}).items():
        if (f["status"] == "open" and f.get("detector") == "review"
                and f.get("detail", {}).get("holistic")
                and fid not in new_ids):
            f["status"] = "auto_resolved"
            f["resolved_at"] = utc_now()
            f["note"] = "not reported in latest holistic re-import"
            diff["auto_resolved"] = diff.get("auto_resolved", 0) + 1

    # Track skipped findings in diff
    if skipped:
        diff["skipped"] = len(skipped)
        diff["skipped_details"] = skipped
    if assessment_meta.get("skipped"):
        diff["assessment_skipped_dimensions"] = assessment_meta["skipped"]
    if assessment_meta.get("stored"):
        diff["assessment_dimensions"] = assessment_meta["stored"]

    _update_holistic_review_cache(state, findings_list)

    return diff


def _update_holistic_review_cache(state: dict, findings_data: list[dict]):
    """Store holistic review metadata in review_cache."""
    rc = state.setdefault("review_cache", {})
    now = utc_now()
    policy = build_dimension_policy(
        state=state,
        config=(state.get("config") if isinstance(state.get("config"), dict) else None),
        allow_custom_dimensions=False,
    )

    # Count valid findings
    valid = [f for f in findings_data
             if all(k in f for k in ("dimension", "identifier", "summary", "confidence"))
             and is_allowed_dimension(normalize_dimension_name(str(f["dimension"])), holistic=True, policy=policy)]

    # Use per-file review cache count as the file count at review time.
    # This tracks actual files reviewed (vs the staleness detector which
    # compares against len(file_finder(path)) at scan time).
    total_files = len(rc.get("files", {}))

    rc["holistic"] = {
        "reviewed_at": now,
        "file_count_at_review": total_files,
        "finding_count": len(valid),
    }
