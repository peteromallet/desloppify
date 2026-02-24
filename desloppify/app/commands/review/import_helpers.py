"""Import/reporting helpers for holistic review command flows."""

from __future__ import annotations

import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.intelligence.review.feedback_contract import (
    ASSESSMENT_FEEDBACK_THRESHOLD,
    LOW_SCORE_FINDING_THRESHOLD,
    score_requires_dimension_finding,
    score_requires_explicit_feedback,
)
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.state import coerce_assessment_score

_VALID_CONFIDENCE = {"high", "medium", "low"}
_REQUIRED_HOLISTIC_FIELDS = (
    "dimension",
    "identifier",
    "summary",
    "related_files",
    "evidence",
    "suggestion",
    "confidence",
)
_ASSESSMENT_POLICY_KEY = "_assessment_policy"
_BLIND_PROVENANCE_KIND = "blind_review_batch_import"
_SUPPORTED_BLIND_REVIEW_RUNNERS = {"codex", "claude"}
_ATTESTED_EXTERNAL_RUNNERS = {"claude"}
_ATTESTED_EXTERNAL_REQUIRED_PHRASES = ("without awareness", "unbiased")
_ATTESTED_EXTERNAL_ATTEST_EXAMPLE = (
    "I validated this review was completed without awareness of overall score and is unbiased."
)
_DEFAULT_BLIND_PACKET_PATH = PROJECT_ROOT / ".desloppify" / "review_packet_blind.json"
_ASSESSMENT_MODE_LABELS = {
    "none": "findings-only (no assessments in payload)",
    "trusted_internal": "trusted internal (durable scores)",
    "attested_external": "attested external (durable scores)",
    "manual_override": "manual override (provisional scores)",
    "findings_only": "findings-only (assessments skipped)",
}


def _is_sha256_hex(raw: object) -> bool:
    return (
        isinstance(raw, str)
        and len(raw) == 64
        and all(ch in "0123456789abcdefABCDEF" for ch in raw)
    )


def _hash_file_sha256(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _resolve_packet_path(raw_path: object) -> Path | None:
    if not isinstance(raw_path, str):
        return None
    text = raw_path.strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _assessment_provenance_status(
    findings_data: dict[str, Any],
    *,
    import_file: str,
) -> dict[str, Any]:
    """Evaluate whether assessments come from a trusted blind batch artifact."""
    provenance = findings_data.get("provenance")
    if not isinstance(provenance, dict):
        return {
            "trusted": False,
            "reason": "missing provenance metadata",
            "import_file": import_file,
        }

    kind = str(provenance.get("kind", "")).strip()
    if kind != _BLIND_PROVENANCE_KIND:
        return {
            "trusted": False,
            "reason": f"unsupported provenance kind: {kind or '<missing>'}",
            "import_file": import_file,
        }

    if provenance.get("blind") is not True:
        return {
            "trusted": False,
            "reason": "provenance is not marked blind=true",
            "import_file": import_file,
        }

    runner = str(provenance.get("runner", "")).strip().lower()
    if runner not in _SUPPORTED_BLIND_REVIEW_RUNNERS:
        return {
            "trusted": False,
            "reason": f"unsupported runner in provenance: {runner or '<missing>'}",
            "import_file": import_file,
        }

    packet_hash = provenance.get("packet_sha256")
    if not _is_sha256_hex(packet_hash):
        return {
            "trusted": False,
            "reason": "missing or invalid packet_sha256 in provenance",
            "import_file": import_file,
        }

    packet_path = _resolve_packet_path(provenance.get("packet_path"))
    if packet_path is None:
        packet_path = _DEFAULT_BLIND_PACKET_PATH
    if not packet_path.exists():
        return {
            "trusted": False,
            "reason": f"blind packet not found: {packet_path}",
            "import_file": import_file,
        }
    observed_hash = _hash_file_sha256(packet_path)
    if observed_hash is None:
        return {
            "trusted": False,
            "reason": f"unable to hash blind packet: {packet_path}",
            "import_file": import_file,
        }
    if observed_hash != packet_hash:
        return {
            "trusted": False,
            "reason": (
                "blind packet hash mismatch "
                f"(expected {packet_hash[:12]}..., got {observed_hash[:12]}...)"
            ),
            "import_file": import_file,
        }

    return {
        "trusted": True,
        "reason": "trusted blind subagent provenance",
        "runner": runner,
        "packet_path": str(packet_path),
        "packet_sha256": packet_hash,
        "import_file": import_file,
    }


def _normalize_override_flags(
    *,
    manual_override: bool,
    manual_attest: str | None,
    assessment_override: bool,
    assessment_note: str | None,
) -> tuple[bool, str | None]:
    """Support legacy assessment_* flags while preferring manual_* naming."""
    override = bool(manual_override or assessment_override)
    attest = (
        manual_attest
        if isinstance(manual_attest, str) and manual_attest.strip()
        else assessment_note
    )
    if isinstance(attest, str):
        attest = attest.strip()
    return override, attest


def _validate_attested_external_attestation(attest: str | None) -> str | None:
    """Validate and normalize attestation text for attested external imports."""
    if not isinstance(attest, str) or not attest.strip():
        return None
    text = attest.strip()
    lowered = text.lower()
    if all(phrase in lowered for phrase in _ATTESTED_EXTERNAL_REQUIRED_PHRASES):
        return text
    return None


def _print_import_error_hints(
    errors: list[str],
    *,
    import_file: str,
    colorize_fn,
) -> None:
    """Print actionable retry commands for common import policy failures."""
    joined = " ".join(err.lower() for err in errors)
    quoted_import = shlex.quote(import_file)
    import_cmd = (
        "desloppify review --import "
        f"{quoted_import} --attested-external --attest "
        f"\"{_ATTESTED_EXTERNAL_ATTEST_EXAMPLE}\""
    )
    validate_cmd = (
        "desloppify review --validate-import "
        f"{quoted_import} --attested-external --attest "
        f"\"{_ATTESTED_EXTERNAL_ATTEST_EXAMPLE}\""
    )
    findings_only_cmd = f"desloppify review --import {quoted_import}"

    if "--attested-external requires --attest containing both" in joined:
        print(
            colorize_fn(
                "  Hint: rerun with the required attestation template:",
                "yellow",
            ),
            file=sys.stderr,
        )
        print(colorize_fn(f"    `{import_cmd}`", "dim"), file=sys.stderr)
        print(
            colorize_fn(
                f"  Preflight without state changes: `{validate_cmd}`",
                "dim",
            ),
            file=sys.stderr,
        )
        return

    if (
        "--attested-external requires valid blind packet provenance" in joined
        or "supports runner='claude'" in joined
    ):
        print(
            colorize_fn(
                "  Hint: if provenance is valid, rerun with:",
                "yellow",
            ),
            file=sys.stderr,
        )
        print(colorize_fn(f"    `{import_cmd}`", "dim"), file=sys.stderr)
        print(
            colorize_fn(
                f"  Preflight without state changes: `{validate_cmd}`",
                "dim",
            ),
            file=sys.stderr,
        )
        print(
            colorize_fn(
                f"  Findings-only fallback: `{findings_only_cmd}`",
                "dim",
            ),
            file=sys.stderr,
        )


def _apply_assessment_import_policy(
    findings_data: dict[str, Any],
    *,
    import_file: str,
    attested_external: bool,
    attested_attest: str | None,
    manual_override: bool,
    manual_attest: str | None,
    trusted_assessment_source: bool,
    trusted_assessment_label: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Apply trust gating for assessment imports (findings import always allowed)."""
    has_assessments = isinstance(findings_data.get("assessments"), dict) and bool(
        findings_data.get("assessments")
    )
    assessment_count = (
        len(findings_data.get("assessments", {})) if has_assessments else 0
    )
    provenance_status = _assessment_provenance_status(
        findings_data, import_file=import_file
    )
    policy: dict[str, Any] = {
        "assessments_present": has_assessments,
        "assessment_count": int(assessment_count),
        "trusted": False,
        "mode": "none",
        "reason": "",
        "provenance": provenance_status,
    }
    if not has_assessments:
        payload = dict(findings_data)
        payload[_ASSESSMENT_POLICY_KEY] = policy
        return payload, []

    if trusted_assessment_source:
        policy["mode"] = "trusted_internal"
        policy["trusted"] = True
        policy["reason"] = (
            trusted_assessment_label or "trusted internal run-batches import"
        )
        payload = dict(findings_data)
        payload[_ASSESSMENT_POLICY_KEY] = policy
        return payload, []

    if attested_external:
        normalized_attest = _validate_attested_external_attestation(attested_attest)
        if normalized_attest is None:
            return None, [
                "--attested-external requires --attest containing both "
                "'without awareness' and 'unbiased'"
            ]
        if provenance_status.get("trusted") is not True:
            return None, [
                "--attested-external requires valid blind packet provenance "
                f"(current status: {provenance_status.get('reason', 'untrusted provenance')})"
            ]
        runner = str(provenance_status.get("runner", "")).strip().lower()
        if runner not in _ATTESTED_EXTERNAL_RUNNERS:
            return None, [
                "--attested-external currently supports runner='claude' provenance only"
            ]
        policy["mode"] = "attested_external"
        policy["trusted"] = True
        policy["reason"] = "attested external blind subagent provenance"
        policy["attest"] = normalized_attest
        payload = dict(findings_data)
        payload[_ASSESSMENT_POLICY_KEY] = policy
        return payload, []

    if manual_override:
        if not isinstance(manual_attest, str) or not manual_attest.strip():
            return None, ["--manual-override requires --attest"]
        policy["mode"] = "manual_override"
        policy["reason"] = "manual override attested by operator"
        policy["attest"] = manual_attest.strip()
        payload = dict(findings_data)
        payload[_ASSESSMENT_POLICY_KEY] = policy
        return payload, []

    policy["mode"] = "findings_only"
    if findings_data.get("provenance") is not None:
        provenance_reason = str(provenance_status.get("reason", "")).strip()
        if provenance_status.get("trusted") is True:
            policy["reason"] = (
                "external imports cannot self-attest trust even when provenance appears valid; "
                "run review --run-batches to apply assessments automatically"
            )
        elif provenance_reason:
            policy["reason"] = (
                "external imports cannot self-attest trust "
                f"({provenance_reason}); run review --run-batches to apply assessments automatically"
            )
        else:
            policy["reason"] = (
                "external imports cannot self-attest trust; "
                "run review --run-batches to apply assessments automatically"
            )
    else:
        policy["reason"] = (
            "missing trusted run-batches source; imported findings only"
        )
    payload = dict(findings_data)
    payload.pop("assessments", None)
    payload[_ASSESSMENT_POLICY_KEY] = policy
    return payload, []


def _has_non_empty_strings(items: object) -> bool:
    """Return True when ``items`` is a list with at least one non-empty string."""
    return isinstance(items, list) and any(
        isinstance(item, str) and item.strip() for item in items
    )


def _validate_holistic_findings_schema(
    findings_data: dict[str, Any],
    *,
    lang_name: str | None = None,
) -> list[str]:
    """Validate strict holistic finding schema expected by issue import."""
    findings = findings_data.get("findings")
    if not isinstance(findings, list):
        return ["findings must be a JSON array"]

    allowed_dimensions: set[str] = set()
    if isinstance(lang_name, str) and lang_name.strip():
        _, dimension_prompts, _ = load_dimensions_for_lang(lang_name)
        allowed_dimensions = set(dimension_prompts)

    errors: list[str] = []
    for idx, entry in enumerate(findings):
        label = f"findings[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue

        # Dismissed concern records use a different shape.
        if entry.get("concern_verdict") == "dismissed":
            fingerprint = entry.get("concern_fingerprint")
            if not isinstance(fingerprint, str) or not fingerprint.strip():
                errors.append(
                    f"{label}.concern_fingerprint is required when concern_verdict='dismissed'"
                )
            continue

        missing = [field for field in _REQUIRED_HOLISTIC_FIELDS if field not in entry]
        if missing:
            errors.append(f"{label} missing required fields: {', '.join(missing)}")
            continue

        dimension = entry.get("dimension")
        if not isinstance(dimension, str) or not dimension.strip():
            errors.append(f"{label}.dimension must be a non-empty string")
        elif allowed_dimensions and dimension not in allowed_dimensions:
            errors.append(
                f"{label}.dimension '{dimension}' is not valid for language '{lang_name}'"
            )

        identifier = entry.get("identifier")
        if not isinstance(identifier, str) or not identifier.strip():
            errors.append(f"{label}.identifier must be a non-empty string")

        summary = entry.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"{label}.summary must be a non-empty string")

        suggestion = entry.get("suggestion")
        if not isinstance(suggestion, str) or not suggestion.strip():
            errors.append(f"{label}.suggestion must be a non-empty string")

        confidence = str(entry.get("confidence", "")).strip().lower()
        if confidence not in _VALID_CONFIDENCE:
            errors.append(
                f"{label}.confidence must be one of: high, medium, low"
            )

        if not _has_non_empty_strings(entry.get("related_files")):
            errors.append(
                f"{label}.related_files must contain at least one file path string"
            )

        if not _has_non_empty_strings(entry.get("evidence")):
            errors.append(
                f"{label}.evidence must contain at least one concrete evidence string"
            )

    return errors


def _feedback_dimensions_from_findings(findings: object) -> set[str]:
    """Return dimensions with explicit improvement guidance in findings payload."""
    if not isinstance(findings, list):
        return set()
    dims: set[str] = set()
    for entry in findings:
        if not isinstance(entry, dict):
            continue
        dim = entry.get("dimension")
        if not isinstance(dim, str) or not dim.strip():
            continue
        suggestion = entry.get("suggestion")
        if isinstance(suggestion, str) and suggestion.strip():
            dims.add(dim.strip())
    return dims


def _feedback_dimensions_from_dimension_notes(dimension_notes: object) -> set[str]:
    """Return dimensions with concrete review evidence in dimension_notes payload."""
    if not isinstance(dimension_notes, dict):
        return set()
    dims: set[str] = set()
    for dim, note in dimension_notes.items():
        if not isinstance(dim, str) or not dim.strip():
            continue
        if not isinstance(note, dict):
            continue
        if not _has_non_empty_strings(note.get("evidence")):
            continue
        dims.add(dim.strip())
    return dims


def _validate_assessment_feedback(
    findings_data: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Return dimensions missing required feedback and required low-score findings."""
    assessments = findings_data.get("assessments")
    if not isinstance(assessments, dict) or not assessments:
        return [], []

    finding_dims = _feedback_dimensions_from_findings(findings_data.get("findings"))
    feedback_dims = set(finding_dims)
    feedback_dims.update(
        _feedback_dimensions_from_dimension_notes(findings_data.get("dimension_notes"))
    )
    missing_feedback: list[str] = []
    missing_low_score_findings: list[str] = []
    for dim_name, payload in assessments.items():
        if not isinstance(dim_name, str) or not dim_name.strip():
            continue
        score = coerce_assessment_score(payload)
        if score is None:
            continue
        if score_requires_dimension_finding(score) and dim_name not in finding_dims:
            missing_low_score_findings.append(f"{dim_name} ({score:.1f})")
        if score_requires_explicit_feedback(score) and dim_name not in feedback_dims:
            missing_feedback.append(f"{dim_name} ({score:.1f})")
    return sorted(missing_feedback), sorted(missing_low_score_findings)


def _parse_and_validate_import(
    import_file: str,
    *,
    lang_name: str | None = None,
    allow_partial: bool = False,
    trusted_assessment_source: bool = False,
    trusted_assessment_label: str | None = None,
    attested_external: bool = False,
    manual_override: bool = False,
    manual_attest: str | None = None,
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse and validate a review import file (pure function).

    Returns ``(data, errors)`` where *data* is the normalized payload on
    success, or ``None`` when errors prevent import.
    """
    findings_path = Path(import_file)
    if not findings_path.exists():
        return None, [f"file not found: {import_file}"]
    try:
        findings_data = json.loads(findings_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return None, [f"error reading findings: {exc}"]

    if isinstance(findings_data, list):
        findings_data = {"findings": findings_data}

    if not isinstance(findings_data, dict):
        return None, ["findings file must contain a JSON array or object"]

    if "findings" not in findings_data:
        return None, ["findings object must contain a 'findings' key"]

    override_enabled, override_attest = _normalize_override_flags(
        manual_override=manual_override,
        manual_attest=manual_attest,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )
    if attested_external and override_enabled:
        return None, [
            "--attested-external cannot be combined with --manual-override"
        ]
    if attested_external and allow_partial:
        return None, [
            "--attested-external cannot be combined with --allow-partial; "
            "attested score imports require fully valid findings payloads"
        ]
    if override_enabled and allow_partial:
        return None, [
            "--manual-override cannot be combined with --allow-partial; "
            "manual score imports require fully valid findings payloads"
        ]
    findings_data, policy_errors = _apply_assessment_import_policy(
        findings_data,
        import_file=import_file,
        attested_external=attested_external,
        attested_attest=override_attest,
        manual_override=override_enabled,
        manual_attest=override_attest,
        trusted_assessment_source=trusted_assessment_source,
        trusted_assessment_label=trusted_assessment_label,
    )
    if policy_errors:
        return None, policy_errors
    assert findings_data is not None

    missing_feedback, missing_low_score_findings = _validate_assessment_feedback(
        findings_data
    )
    if missing_low_score_findings:
        if override_enabled:
            if not isinstance(override_attest, str) or not override_attest.strip():
                return None, ["--manual-override requires --attest"]
            return findings_data, []
        return None, [
            f"assessments below {LOW_SCORE_FINDING_THRESHOLD:.1f} must include at "
            "least one finding for that same dimension with a concrete suggestion. "
            f"Missing: {', '.join(missing_low_score_findings)}"
        ]

    if missing_feedback:
        if override_enabled:
            if not isinstance(override_attest, str) or not override_attest.strip():
                return None, ["--manual-override requires --attest"]
            return findings_data, []
        return None, [
            f"assessments below {ASSESSMENT_FEEDBACK_THRESHOLD:.1f} must include explicit feedback "
            "(finding with same dimension and non-empty suggestion, or "
            "dimension_notes evidence for that dimension). "
            f"Missing: {', '.join(missing_feedback)}"
        ]

    schema_errors = _validate_holistic_findings_schema(
        findings_data,
        lang_name=lang_name,
    )
    if schema_errors and not allow_partial:
        visible_errors = schema_errors[:10]
        remaining = len(schema_errors) - len(visible_errors)
        errors = [
            "findings schema validation failed for holistic import. "
            "Fix payload or rerun with --allow-partial to continue."
        ]
        errors.extend(visible_errors)
        if remaining > 0:
            errors.append(f"... {remaining} additional schema error(s) omitted")
        return None, errors

    return findings_data, []


def load_import_findings_data(
    import_file: str,
    *,
    colorize_fn,
    lang_name: str | None = None,
    allow_partial: bool = False,
    trusted_assessment_source: bool = False,
    trusted_assessment_label: str | None = None,
    attested_external: bool = False,
    manual_override: bool = False,
    manual_attest: str | None = None,
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> dict[str, Any]:
    """Load and normalize review import payload to object format.

    CLI wrapper over ``_parse_and_validate_import`` that prints errors
    and calls ``sys.exit(1)`` on failure.
    """
    data, errors = _parse_and_validate_import(
        import_file,
        lang_name=lang_name,
        allow_partial=allow_partial,
        trusted_assessment_source=trusted_assessment_source,
        trusted_assessment_label=trusted_assessment_label,
        attested_external=attested_external,
        manual_override=manual_override,
        manual_attest=manual_attest,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )
    if errors:
        for err in errors:
            print(colorize_fn(f"  Error: {err}", "red"), file=sys.stderr)
        _print_import_error_hints(errors, import_file=import_file, colorize_fn=colorize_fn)
        sys.exit(1)
    assert data is not None  # guaranteed when errors is empty
    return data


def assessment_policy_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return parsed assessment policy metadata from a loaded import payload."""
    policy = payload.get(_ASSESSMENT_POLICY_KEY)
    return policy if isinstance(policy, dict) else {}


def assessment_mode_label(policy: dict[str, Any]) -> str:
    """Return a user-facing label for the selected assessment import mode."""
    mode = str(policy.get("mode", "none")).strip().lower()
    return _ASSESSMENT_MODE_LABELS.get(mode, f"unknown ({mode or 'none'})")


def print_assessment_mode_banner(
    policy: dict[str, Any],
    *,
    colorize_fn,
) -> None:
    """Print the selected assessment import mode to make policy explicit."""
    if not policy:
        return
    mode = str(policy.get("mode", "none")).strip().lower()
    assessments_present = bool(policy.get("assessments_present"))
    if not assessments_present and mode == "none":
        return
    style = "yellow" if mode in {"manual_override", "findings_only"} else "dim"
    print(colorize_fn(f"  Assessment import mode: {assessment_mode_label(policy)}", style))


def print_assessment_policy_notice(
    policy: dict[str, Any],
    *,
    import_file: str,
    colorize_fn,
) -> None:
    """Render trust/override status for assessment-bearing imports."""
    if not policy or not policy.get("assessments_present"):
        return
    mode = str(policy.get("mode", "none")).strip().lower()
    reason = str(policy.get("reason", "")).strip()

    if mode == "trusted":
        packet_path = None
        if isinstance(policy.get("provenance"), dict):
            packet_path = policy.get("provenance", {}).get("packet_path")
        detail = f" · blind packet {packet_path}" if isinstance(packet_path, str) else ""
        print(
            colorize_fn(
                f"  Assessment provenance: trusted blind batch artifact{detail}.",
                "dim",
            )
        )
        return

    if mode == "trusted_internal":
        count = int(policy.get("assessment_count", 0) or 0)
        reason_text = str(policy.get("reason", "")).strip()
        suffix = f" ({reason_text})" if reason_text else ""
        print(
            colorize_fn(
                f"  Assessment updates applied: {count} dimension(s){suffix}.",
                "dim",
            )
        )
        return

    if mode == "manual_override":
        count = int(policy.get("assessment_count", 0) or 0)
        print(
            colorize_fn(
                f"  WARNING: applying {count} assessment update(s) via manual override from untrusted provenance.",
                "yellow",
            )
        )
        if reason:
            print(colorize_fn(f"  Reason: {reason}", "dim"))
        return

    if mode == "attested_external":
        count = int(policy.get("assessment_count", 0) or 0)
        print(
            colorize_fn(
                f"  Assessment updates applied via attested external blind review: {count} dimension(s).",
                "dim",
            )
        )
        if reason:
            print(colorize_fn(f"  Reason: {reason}", "dim"))
        return

    if mode == "findings_only":
        count = int(policy.get("assessment_count", 0) or 0)
        print(
            colorize_fn(
                "  WARNING: untrusted assessment source detected. "
                f"Imported findings only; skipped {count} assessment score update(s).",
                "yellow",
            )
        )
        if reason:
            print(colorize_fn(f"  Reason: {reason}", "dim"))
        print(
            colorize_fn(
                "  Assessment scores in state were left unchanged.",
                "dim",
            )
        )
        print(
            colorize_fn(
                "  Happy path: use `desloppify review --run-batches --parallel --scan-after-import`.",
                "dim",
            )
        )
        print(
            colorize_fn(
                "  If you intentionally want manual assessment import, rerun with "
                f"`desloppify review --import {import_file} --manual-override --attest \"<why this is justified>\"`.",
                "dim",
            )
        )
        print(
            colorize_fn(
                "  Claude cloud path for durable scores: "
                f"`desloppify review --import {import_file} --attested-external "
                f"--attest \"{_ATTESTED_EXTERNAL_ATTEST_EXAMPLE}\"`",
                "dim",
            )
        )


def print_skipped_validation_details(diff: dict[str, Any], *, colorize_fn) -> None:
    """Print validation warnings for skipped imported findings."""
    n_skipped = diff.get("skipped", 0)
    if n_skipped <= 0:
        return
    print(
        colorize_fn(
            f"\n  \u26a0 {n_skipped} finding(s) skipped (validation errors):",
            "yellow",
        )
    )
    for detail in diff.get("skipped_details", []):
        reasons = detail["missing"]
        missing_fields = [r for r in reasons if not r.startswith("invalid ")]
        validation_errors = [r for r in reasons if r.startswith("invalid ")]
        parts = []
        if missing_fields:
            parts.append(f"missing {', '.join(missing_fields)}")
        parts.extend(validation_errors)
        print(
            colorize_fn(
                f"    #{detail['index']} ({detail['identifier']}): {'; '.join(parts)}",
                "yellow",
            )
        )


def print_assessments_summary(state: dict[str, Any], *, colorize_fn) -> None:
    """Print holistic subjective assessment summary when present."""
    assessments = state.get("subjective_assessments") or {}
    if not assessments:
        return
    parts = [
        f"{key.replace('_', ' ')} {value['score']}"
        for key, value in sorted(assessments.items())
    ]
    print(colorize_fn(f"\n  Assessments: {', '.join(parts)}", "bold"))


def print_open_review_summary(state: dict[str, Any], *, colorize_fn) -> str:
    """Print current open review finding count and return next command."""
    open_review = [
        finding
        for finding in state["findings"].values()
        if finding["status"] == "open" and finding.get("detector") == "review"
    ]
    if not open_review:
        return "desloppify scan"
    print(
        colorize_fn(
            f"\n  {len(open_review)} review issue{'s' if len(open_review) != 1 else ''} open total "
            f"({len(open_review)} review finding{'s' if len(open_review) != 1 else ''} open total)",
            "bold",
        )
    )
    print(colorize_fn("  Run `desloppify issues` to see the work queue", "dim"))
    return "desloppify issues"


def print_review_import_scores_and_integrity(
    state: dict[str, Any],
    config: dict[str, Any],
    *,
    state_mod,
    target_strict_score_from_config_fn,
    subjective_at_target_fn,
    subjective_rerun_command_fn,
    colorize_fn,
) -> list[dict[str, Any]]:
    """Print score snapshot plus subjective integrity warnings."""
    scores = state_mod.score_snapshot(state)
    if scores.overall is not None and scores.objective is not None and scores.strict is not None:
        print(
            colorize_fn(
                f"\n  Current scores: overall {scores.overall:.1f}/100 · "
                f"objective {scores.objective:.1f}/100 · strict {scores.strict:.1f}/100",
                "dim",
            )
        )

    target_strict = target_strict_score_from_config_fn(config, fallback=95.0)
    at_target = subjective_at_target_fn(
        state,
        state.get("dimension_scores", {}),
        target=target_strict,
    )
    if not at_target:
        return []

    command = subjective_rerun_command_fn(at_target, max_items=5)
    count = len(at_target)
    if count >= 2:
        print(
            colorize_fn(
                "  WARNING: "
                f"{count} subjective scores match the target score. "
                "On the next scan, those dimensions will be reset to 0.0 by the anti-gaming safeguard "
                f"unless you rerun and re-import objective reviews first: {command}",
                "red",
            )
        )
    else:
        print(
            colorize_fn(
                "  WARNING: "
                f"{count} subjective score matches the target score, indicating a high risk of gaming. "
                f"Can you rerun it by running {command} taking extra care to be objective.",
                "yellow",
            )
        )
    return at_target


__all__ = [
    "assessment_mode_label",
    "assessment_policy_from_payload",
    "load_import_findings_data",
    "print_assessment_mode_banner",
    "print_assessment_policy_notice",
    "print_assessments_summary",
    "print_open_review_summary",
    "print_review_import_scores_and_integrity",
    "print_skipped_validation_details",
]
