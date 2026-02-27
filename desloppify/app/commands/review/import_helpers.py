"""Import/reporting helpers for holistic review command flows."""

from __future__ import annotations

import hashlib
import json
import shlex
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from desloppify.core._internal.text_utils import get_project_root
from desloppify.intelligence.review.importing.contracts import (
    AssessmentImportPolicyModel,
    AssessmentImportPolicy,
    AssessmentProvenanceModel,
    ReviewFindingPayload,
    ReviewImportPayload,
    validate_review_finding_payload,
)
from desloppify.intelligence.review.feedback_contract import (
    ASSESSMENT_FEEDBACK_THRESHOLD,
    LOW_SCORE_FINDING_THRESHOLD,
    score_requires_dimension_finding,
    score_requires_explicit_feedback,
)
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang
from desloppify.state import coerce_assessment_score

_ASSESSMENT_POLICY_KEY = "_assessment_policy"
_BLIND_PROVENANCE_KIND = "blind_review_batch_import"
_SUPPORTED_BLIND_REVIEW_RUNNERS = {"codex", "claude"}
_ATTESTED_EXTERNAL_RUNNERS = {"claude"}
_ATTESTED_EXTERNAL_REQUIRED_PHRASES = ("without awareness", "unbiased")
_ATTESTED_EXTERNAL_ATTEST_EXAMPLE = (
    "I validated this review was completed without awareness of overall score and is unbiased."
)
_ASSESSMENT_MODE_LABELS = {
    "none": "findings-only (no assessments in payload)",
    "trusted_internal": "trusted internal (durable scores)",
    "attested_external": "attested external (durable scores)",
    "manual_override": "manual override (provisional scores)",
    "findings_only": "findings-only (assessments skipped)",
}


class ImportPayloadLoadError(ValueError):
    """Raised when review import payload parsing/validation fails."""

    def __init__(self, errors: list[str]) -> None:
        cleaned = [str(error).strip() for error in errors if str(error).strip()]
        self.errors = cleaned
        message = "; ".join(cleaned) if cleaned else "import payload validation failed"
        super().__init__(message)


def _normalize_import_payload_shape(
    payload: dict[str, Any],
) -> tuple[ReviewImportPayload | None, list[str]]:
    """Normalize payload into required-key contract with strict type checks."""
    errors: list[str] = []
    findings = payload.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be a JSON array")
        findings = []

    assessments = payload.get("assessments")
    if assessments is None:
        assessments = {}
    elif not isinstance(assessments, dict):
        errors.append("assessments must be an object when provided")
        assessments = {}

    reviewed_files = payload.get("reviewed_files")
    normalized_reviewed_files: list[str] = []
    if reviewed_files is None:
        normalized_reviewed_files = []
    elif isinstance(reviewed_files, list):
        normalized_reviewed_files = [
            str(item).strip()
            for item in reviewed_files
            if isinstance(item, str) and str(item).strip()
        ]
    else:
        errors.append("reviewed_files must be an array when provided")

    review_scope = payload.get("review_scope")
    if review_scope is None:
        review_scope = {}
    elif not isinstance(review_scope, dict):
        errors.append("review_scope must be an object when provided")
        review_scope = {}

    provenance = payload.get("provenance")
    if provenance is None:
        provenance = {}
    elif not isinstance(provenance, dict):
        errors.append("provenance must be an object when provided")
        provenance = {}

    dimension_notes = payload.get("dimension_notes")
    if dimension_notes is None:
        dimension_notes = {}
    elif not isinstance(dimension_notes, dict):
        errors.append("dimension_notes must be an object when provided")
        dimension_notes = {}

    policy = payload.get(_ASSESSMENT_POLICY_KEY)
    normalized_policy = (
        policy if isinstance(policy, dict) else AssessmentImportPolicyModel().to_dict()
    )
    if errors:
        return None, errors
    return (
        {
            "findings": findings,
            "assessments": assessments,
            "reviewed_files": normalized_reviewed_files,
            "review_scope": review_scope,
            "provenance": provenance,
            "dimension_notes": dimension_notes,
            _ASSESSMENT_POLICY_KEY: normalized_policy,
        },
        [],
    )


def _default_blind_packet_path() -> Path:
    return get_project_root() / ".desloppify" / "review_packet_blind.json"


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
    return path if path.is_absolute() else get_project_root() / path


def _assessment_provenance_status(
    findings_data: ReviewImportPayload,
    *,
    import_file: str,
) -> AssessmentProvenanceModel:
    """Evaluate whether assessments come from a trusted blind batch artifact."""
    provenance = findings_data["provenance"]
    if not provenance:
        return AssessmentProvenanceModel(
            trusted=False,
            reason="missing provenance metadata",
            import_file=import_file,
        )

    kind = str(provenance.get("kind", "")).strip()
    if kind != _BLIND_PROVENANCE_KIND:
        return AssessmentProvenanceModel(
            trusted=False,
            reason=f"unsupported provenance kind: {kind or '<missing>'}",
            import_file=import_file,
        )

    if provenance.get("blind") is not True:
        return AssessmentProvenanceModel(
            trusted=False,
            reason="provenance is not marked blind=true",
            import_file=import_file,
        )

    runner = str(provenance.get("runner", "")).strip().lower()
    if runner not in _SUPPORTED_BLIND_REVIEW_RUNNERS:
        return AssessmentProvenanceModel(
            trusted=False,
            reason=f"unsupported runner in provenance: {runner or '<missing>'}",
            import_file=import_file,
        )

    packet_hash = provenance.get("packet_sha256")
    if not _is_sha256_hex(packet_hash):
        return AssessmentProvenanceModel(
            trusted=False,
            reason="missing or invalid packet_sha256 in provenance",
            import_file=import_file,
        )

    packet_path = _resolve_packet_path(provenance.get("packet_path"))
    if packet_path is None:
        packet_path = _default_blind_packet_path()
    if not packet_path.exists():
        return AssessmentProvenanceModel(
            trusted=False,
            reason=f"blind packet not found: {packet_path}",
            import_file=import_file,
        )
    observed_hash = _hash_file_sha256(packet_path)
    if observed_hash is None:
        return AssessmentProvenanceModel(
            trusted=False,
            reason=f"unable to hash blind packet: {packet_path}",
            import_file=import_file,
        )
    if observed_hash != packet_hash:
        return AssessmentProvenanceModel(
            trusted=False,
            reason=(
                "blind packet hash mismatch "
                f"(expected {packet_hash[:12]}..., got {observed_hash[:12]}...)"
            ),
            import_file=import_file,
        )

    return AssessmentProvenanceModel(
        trusted=True,
        reason="trusted blind subagent provenance",
        runner=runner,
        packet_path=str(packet_path),
        packet_sha256=packet_hash,
        import_file=import_file,
    )


def resolve_override_context(
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
    findings_data: ReviewImportPayload,
    *,
    import_file: str,
    attested_external: bool,
    attested_attest: str | None,
    manual_override: bool,
    manual_attest: str | None,
    trusted_assessment_source: bool,
    trusted_assessment_label: str | None,
) -> tuple[ReviewImportPayload | None, list[str]]:
    """Apply trust gating for assessment imports (findings import always allowed)."""
    assessments = findings_data["assessments"]
    has_assessments = bool(assessments)
    assessment_count = len(assessments) if has_assessments else 0
    provenance_status = _assessment_provenance_status(
        findings_data, import_file=import_file
    )
    policy = AssessmentImportPolicyModel(
        assessments_present=has_assessments,
        assessment_count=int(assessment_count),
        trusted=False,
        mode="none",
        reason="",
        provenance=provenance_status,
    )

    def _attach_policy(payload: ReviewImportPayload) -> ReviewImportPayload:
        normalized = dict(payload)
        normalized[_ASSESSMENT_POLICY_KEY] = policy.to_dict()
        return normalized

    if not has_assessments:
        return _attach_policy(findings_data), []

    if trusted_assessment_source:
        policy = replace(
            policy,
            mode="trusted_internal",
            trusted=True,
            reason=(trusted_assessment_label or "trusted internal run-batches import"),
        )
        return _attach_policy(findings_data), []

    if attested_external:
        normalized_attest = _validate_attested_external_attestation(attested_attest)
        if normalized_attest is None:
            return None, [
                "--attested-external requires --attest containing both "
                "'without awareness' and 'unbiased'"
            ]
        if provenance_status.trusted is not True:
            return None, [
                "--attested-external requires valid blind packet provenance "
                f"(current status: {provenance_status.reason or 'untrusted provenance'})"
            ]
        runner = provenance_status.runner.strip().lower()
        if runner not in _ATTESTED_EXTERNAL_RUNNERS:
            return None, [
                "--attested-external currently supports runner='claude' provenance only"
            ]
        policy = replace(
            policy,
            mode="attested_external",
            trusted=True,
            reason="attested external blind subagent provenance",
            attest=normalized_attest,
        )
        return _attach_policy(findings_data), []

    if manual_override:
        if not isinstance(manual_attest, str) or not manual_attest.strip():
            return None, ["--manual-override requires --attest"]
        policy = replace(
            policy,
            mode="manual_override",
            reason="manual override attested by operator",
            attest=manual_attest.strip(),
        )
        return _attach_policy(findings_data), []

    policy = replace(policy, mode="findings_only")
    if findings_data["provenance"]:
        provenance_reason = provenance_status.reason.strip()
        if provenance_status.trusted is True:
            policy = replace(
                policy,
                reason=(
                    "external imports cannot self-attest trust even when provenance appears valid; "
                    "run review --run-batches to apply assessments automatically"
                ),
            )
        elif provenance_reason:
            policy = replace(
                policy,
                reason=(
                    "external imports cannot self-attest trust "
                    f"({provenance_reason}); run review --run-batches to apply assessments automatically"
                ),
            )
        else:
            policy = replace(
                policy,
                reason=(
                    "external imports cannot self-attest trust; "
                    "run review --run-batches to apply assessments automatically"
                ),
            )
    else:
        policy = replace(
            policy,
            reason="missing trusted run-batches source; imported findings only",
        )
    payload = dict(findings_data)
    payload["assessments"] = {}
    payload[_ASSESSMENT_POLICY_KEY] = policy.to_dict()
    return payload, []


def _has_non_empty_strings(items: object) -> bool:
    """Return True when ``items`` is a list with at least one non-empty string."""
    return isinstance(items, list) and any(
        isinstance(item, str) and item.strip() for item in items
    )


def _validate_holistic_findings_schema(
    findings_data: ReviewImportPayload,
    *,
    lang_name: str | None = None,
) -> list[str]:
    """Validate strict holistic finding schema expected by issue import."""
    findings = findings_data["findings"]

    allowed_dimensions: set[str] = set()
    if isinstance(lang_name, str) and lang_name.strip():
        _, dimension_prompts, _ = load_dimensions_for_lang(lang_name)
        allowed_dimensions = set(dimension_prompts)

    errors: list[str] = []
    for idx, entry in enumerate(findings):
        _normalized: ReviewFindingPayload | None
        _normalized, entry_errors = validate_review_finding_payload(
            entry,
            label=f"findings[{idx}]",
            allowed_dimensions=allowed_dimensions or None,
            allow_dismissed=True,
        )
        for message in entry_errors:
            if (
                "is not allowed" in message
                and lang_name
                and "dimension '" in message
            ):
                message = message.replace(
                    "is not allowed",
                    f"is not valid for language '{lang_name}'",
                )
            errors.append(message)
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
    findings_data: ReviewImportPayload,
) -> tuple[list[str], list[str]]:
    """Return dimensions missing required feedback and required low-score findings."""
    assessments = findings_data["assessments"]
    if not assessments:
        return [], []

    finding_dims = _feedback_dimensions_from_findings(findings_data["findings"])
    feedback_dims = set(finding_dims)
    feedback_dims.update(
        _feedback_dimensions_from_dimension_notes(findings_data["dimension_notes"])
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
) -> tuple[ReviewImportPayload | None, list[str]]:
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
    normalized_findings_data, shape_errors = _normalize_import_payload_shape(
        findings_data
    )
    if shape_errors:
        return None, shape_errors
    assert normalized_findings_data is not None

    override_enabled, override_attest = resolve_override_context(
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
        normalized_findings_data,
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
    colorize_fn=None,
    lang_name: str | None = None,
    allow_partial: bool = False,
    trusted_assessment_source: bool = False,
    trusted_assessment_label: str | None = None,
    attested_external: bool = False,
    manual_override: bool = False,
    manual_attest: str | None = None,
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> ReviewImportPayload:
    """Load and normalize review import payload to object format.

    Raises ``ImportPayloadLoadError`` when validation fails.
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
        raise ImportPayloadLoadError(errors)
    assert data is not None  # guaranteed when errors is empty
    return data


def print_import_load_errors(
    errors: list[str],
    *,
    import_file: str,
    colorize_fn,
) -> None:
    """Print import payload validation errors and actionable hints."""
    for err in errors:
        print(colorize_fn(f"  Error: {err}", "red"), file=sys.stderr)
    _print_import_error_hints(errors, import_file=import_file, colorize_fn=colorize_fn)


def assessment_policy_from_payload(payload: ReviewImportPayload) -> AssessmentImportPolicy:
    """Return parsed assessment policy metadata from a loaded import payload."""
    policy = payload[_ASSESSMENT_POLICY_KEY]
    if isinstance(policy, dict):
        return policy
    return AssessmentImportPolicyModel().to_dict()


def assessment_policy_model_from_payload(
    payload: ReviewImportPayload,
) -> AssessmentImportPolicyModel:
    """Return typed assessment policy metadata from a loaded import payload."""
    return AssessmentImportPolicyModel.from_mapping(assessment_policy_from_payload(payload))


def assessment_mode_label(policy: AssessmentImportPolicy) -> str:
    """Return a user-facing label for the selected assessment import mode."""
    mode = AssessmentImportPolicyModel.from_mapping(policy).mode.strip().lower()
    return _ASSESSMENT_MODE_LABELS.get(mode, f"unknown ({mode or 'none'})")


def print_assessment_mode_banner(
    policy: AssessmentImportPolicy,
    *,
    colorize_fn,
) -> None:
    """Print the selected assessment import mode to make policy explicit."""
    policy_model = AssessmentImportPolicyModel.from_mapping(policy)
    mode = policy_model.mode.strip().lower()
    assessments_present = bool(policy_model.assessments_present)
    if not assessments_present and mode == "none":
        return
    style = "yellow" if mode in {"manual_override", "findings_only"} else "dim"
    print(colorize_fn(f"  Assessment import mode: {assessment_mode_label(policy)}", style))


def print_assessment_policy_notice(
    policy: AssessmentImportPolicy,
    *,
    import_file: str,
    colorize_fn,
) -> None:
    """Render trust/override status for assessment-bearing imports."""
    policy_model = AssessmentImportPolicyModel.from_mapping(policy)
    if not policy_model.assessments_present:
        return
    mode = policy_model.mode.strip().lower()
    reason = policy_model.reason.strip()

    if mode == "trusted":
        packet_path = policy_model.provenance.packet_path.strip() or None
        detail = f" · blind packet {packet_path}" if packet_path else ""
        print(
            colorize_fn(
                f"  Assessment provenance: trusted blind batch artifact{detail}.",
                "dim",
            )
        )
        return

    if mode == "trusted_internal":
        count = int(policy_model.assessment_count or 0)
        reason_text = policy_model.reason.strip()
        suffix = f" ({reason_text})" if reason_text else ""
        print(
            colorize_fn(
                f"  Assessment updates applied: {count} dimension(s){suffix}.",
                "dim",
            )
        )
        return

    if mode == "manual_override":
        count = int(policy_model.assessment_count or 0)
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
        count = int(policy_model.assessment_count or 0)
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
        count = int(policy_model.assessment_count or 0)
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
    print(colorize_fn("  Run `desloppify show review --status open` to see the work queue", "dim"))
    return "desloppify show review --status open"


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
    """Print subjective integrity warnings (score line handled by print_score_update)."""
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
    "ImportPayloadLoadError",
    "assessment_mode_label",
    "assessment_policy_model_from_payload",
    "assessment_policy_from_payload",
    "load_import_findings_data",
    "print_assessment_mode_banner",
    "print_import_load_errors",
    "print_assessment_policy_notice",
    "print_assessments_summary",
    "print_open_review_summary",
    "print_review_import_scores_and_integrity",
    "print_skipped_validation_details",
    "resolve_override_context",
]
