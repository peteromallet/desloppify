"""Finding import: import_review_findings, import_holistic_findings, assessments."""

from __future__ import annotations

import hashlib

from ..state import make_finding, merge_scan, utc_now
from ..utils import PROJECT_ROOT
from .dimensions import DIMENSION_PROMPTS, HOLISTIC_DIMENSION_PROMPTS


# ── Assessment storage ─────────────────────────────────────────────

def _store_assessments(state: dict, assessments: dict, source: str):
    """Store dimension assessments in state.

    *assessments*: ``{dim_name: score}`` or ``{dim_name: {score, ...}}``.
    *source*: ``"per_file"`` or ``"holistic"``.

    Holistic assessments overwrite per-file for the same dimension.
    Per-file assessments don't overwrite holistic.
    """
    store = state.setdefault("subjective_assessments", {})
    now = utc_now()

    for dim_name, value in assessments.items():
        score = value if isinstance(value, (int, float)) else value.get("score", 0)
        score = max(0, min(100, score))

        existing = store.get(dim_name)
        if existing and existing.get("source") == "holistic" and source == "per_file":
            continue  # Don't overwrite holistic with per-file

        store[dim_name] = {
            "score": score,
            "source": source,
            "assessed_at": now,
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

def import_review_findings(findings_data: list[dict] | dict, state: dict,
                           lang_name: str) -> dict:
    """Import agent-produced review findings into state.

    Accepts either a bare list of findings (legacy) or a dict with
    ``"assessments"`` and ``"findings"`` keys (new format).

    Validates structure, creates Finding objects, merges into state.
    Returns diff summary.
    """
    findings_list, assessments = _extract_findings_and_assessments(findings_data)
    if assessments:
        _store_assessments(state, assessments, source="per_file")

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
        dimension = f["dimension"]
        if dimension not in DIMENSION_PROMPTS:
            skipped.append({"index": idx, "missing": [f"invalid dimension: {dimension}"],
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

def import_holistic_findings(findings_data: list[dict] | dict, state: dict,
                              lang_name: str) -> dict:
    """Import holistic (codebase-wide) findings into state.

    Accepts either a bare list of findings (legacy) or a dict with
    ``"assessments"`` and ``"findings"`` keys (new format).

    Holistic findings have no `file` field — stored as file="." with
    detail.holistic=True and detail.related_files=[...].
    Returns diff summary.
    """
    from ..scoring import HOLISTIC_POTENTIAL

    findings_list, assessments = _extract_findings_and_assessments(findings_data)
    if assessments:
        _store_assessments(state, assessments, source="holistic")

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

        dimension = f["dimension"]
        if dimension not in HOLISTIC_DIMENSION_PROMPTS:
            skipped.append({"index": idx, "missing": [f"invalid dimension: {dimension}"],
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

    _update_holistic_review_cache(state, findings_list)

    return diff


def _update_holistic_review_cache(state: dict, findings_data: list[dict]):
    """Store holistic review metadata in review_cache."""
    rc = state.setdefault("review_cache", {})
    now = utc_now()

    # Count valid findings
    valid = [f for f in findings_data
             if all(k in f for k in ("dimension", "identifier", "summary", "confidence"))
             and f["dimension"] in HOLISTIC_DIMENSION_PROMPTS]

    # Use per-file review cache count as the file count at review time.
    # This tracks actual files reviewed (vs the staleness detector which
    # compares against len(file_finder(path)) at scan time).
    total_files = len(rc.get("files", {}))

    rc["holistic"] = {
        "reviewed_at": now,
        "file_count_at_review": total_files,
        "finding_count": len(valid),
    }
