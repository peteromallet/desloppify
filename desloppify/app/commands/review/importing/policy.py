"""Assessment import policy and provenance helpers for review imports."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from desloppify.intelligence.review.importing.contracts_models import (
    AssessmentImportPolicyModel,
    AssessmentProvenanceModel,
)
from desloppify.intelligence.review.importing.contracts_types import (
    AssessmentImportPolicy,
    NormalizedReviewImportPayload,
    ReviewImportPayload,
)

from ..runtime_paths import blind_packet_path, runtime_project_root

ASSESSMENT_POLICY_KEY = "_assessment_policy"
BLIND_PROVENANCE_KIND = "blind_review_batch_import"
SUPPORTED_BLIND_REVIEW_RUNNERS = {"codex", "claude", "opencode"}
ATTESTED_EXTERNAL_RUNNERS = {"claude"}
ATTESTED_EXTERNAL_REQUIRED_PHRASES = ("without awareness", "unbiased")
ATTESTED_EXTERNAL_ATTEST_EXAMPLE = "I validated this review was completed without awareness of overall score and is unbiased."
ASSESSMENT_MODE_LABELS = {
    "none": "issues-only (no assessments in payload)",
    "trusted_internal": "trusted internal (durable scores)",
    "attested_external": "attested external (durable scores)",
    "manual_override": "manual override (provisional scores)",
    "issues_only": "issues-only (assessments skipped)",
}


def _default_blind_packet_path() -> Path:
    return blind_packet_path()


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
    return path if path.is_absolute() else runtime_project_root() / path


def _assessment_provenance_status(
    issues_data: NormalizedReviewImportPayload,
    *,
    import_file: str,
) -> AssessmentProvenanceModel:
    """Evaluate whether assessments come from a trusted blind batch artifact."""
    provenance = issues_data["provenance"]
    if not provenance:
        return AssessmentProvenanceModel(
            trusted=False,
            reason="missing provenance metadata",
            import_file=import_file,
        )

    kind = str(provenance.get("kind", "")).strip()
    if kind != BLIND_PROVENANCE_KIND:
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
    if runner not in SUPPORTED_BLIND_REVIEW_RUNNERS:
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


def validate_attested_external_attestation(attest: str | None) -> str | None:
    """Validate and normalize attestation text for attested external imports."""
    if not isinstance(attest, str) or not attest.strip():
        return None
    text = attest.strip()
    lowered = text.lower()
    if all(phrase in lowered for phrase in ATTESTED_EXTERNAL_REQUIRED_PHRASES):
        return text
    return None


def apply_assessment_import_policy(
    issues_data: NormalizedReviewImportPayload,
    *,
    import_file: str,
    attested_external: bool,
    attested_attest: str | None,
    manual_override: bool,
    manual_attest: str | None,
    trusted_assessment_source: bool,
    trusted_assessment_label: str | None,
) -> tuple[NormalizedReviewImportPayload | None, list[str]]:
    """Apply trust gating for assessment imports (issues import always allowed)."""
    assessments = issues_data["assessments"]
    has_assessments = bool(assessments)
    assessment_count = len(assessments) if has_assessments else 0
    provenance_status = _assessment_provenance_status(
        issues_data, import_file=import_file
    )
    policy = AssessmentImportPolicyModel(
        assessments_present=has_assessments,
        assessment_count=int(assessment_count),
        trusted=False,
        mode="none",
        reason="",
        provenance=provenance_status,
    )

    if not has_assessments:
        return _attach_assessment_policy(issues_data, policy), []

    if trusted_assessment_source:
        trusted_policy = replace(
            policy,
            mode="trusted_internal",
            trusted=True,
            reason=(trusted_assessment_label or "trusted internal run-batches import"),
        )
        return _attach_assessment_policy(issues_data, trusted_policy), []

    if attested_external:
        return _apply_attested_external_policy(
            issues_data,
            policy=policy,
            provenance_status=provenance_status,
            attested_attest=attested_attest,
        )

    if manual_override:
        return _apply_manual_override_policy(
            issues_data,
            policy=policy,
            manual_attest=manual_attest,
        )

    return _apply_issues_only_policy(
        issues_data,
        policy=policy,
        provenance_status=provenance_status,
    )


def _attach_assessment_policy(
    payload: NormalizedReviewImportPayload,
    policy: AssessmentImportPolicyModel,
) -> NormalizedReviewImportPayload:
    normalized = dict(payload)
    normalized[ASSESSMENT_POLICY_KEY] = policy.to_dict()
    return normalized


def _apply_attested_external_policy(
    issues_data: NormalizedReviewImportPayload,
    *,
    policy: AssessmentImportPolicyModel,
    provenance_status: AssessmentProvenanceModel,
    attested_attest: str | None,
) -> tuple[NormalizedReviewImportPayload | None, list[str]]:
    normalized_attest = validate_attested_external_attestation(attested_attest)
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
    if runner not in ATTESTED_EXTERNAL_RUNNERS:
        return None, [
            "--attested-external currently supports runner='claude' provenance only"
        ]
    attested_policy = replace(
        policy,
        mode="attested_external",
        trusted=True,
        reason="attested external blind subagent provenance",
        attest=normalized_attest,
    )
    return _attach_assessment_policy(issues_data, attested_policy), []


def _apply_manual_override_policy(
    issues_data: NormalizedReviewImportPayload,
    *,
    policy: AssessmentImportPolicyModel,
    manual_attest: str | None,
) -> tuple[NormalizedReviewImportPayload | None, list[str]]:
    if not isinstance(manual_attest, str) or not manual_attest.strip():
        return None, ["--manual-override requires --attest"]
    override_policy = replace(
        policy,
        mode="manual_override",
        reason="manual override attested by operator",
        attest=manual_attest.strip(),
    )
    return _attach_assessment_policy(issues_data, override_policy), []


def _issues_only_reason(
    issues_data: NormalizedReviewImportPayload,
    *,
    provenance_status: AssessmentProvenanceModel,
) -> str:
    if not issues_data["provenance"]:
        return "missing trusted run-batches source; imported issues only"
    provenance_reason = provenance_status.reason.strip()
    if provenance_status.trusted is True:
        return (
            "external imports cannot self-attest trust even when provenance appears valid; "
            "run review --run-batches to apply assessments automatically"
        )
    if provenance_reason:
        return (
            "external imports cannot self-attest trust "
            f"({provenance_reason}); run review --run-batches to apply assessments automatically"
        )
    return (
        "external imports cannot self-attest trust; "
        "run review --run-batches to apply assessments automatically"
    )


def _apply_issues_only_policy(
    issues_data: NormalizedReviewImportPayload,
    *,
    policy: AssessmentImportPolicyModel,
    provenance_status: AssessmentProvenanceModel,
) -> tuple[NormalizedReviewImportPayload, list[str]]:
    issues_only_policy = replace(
        policy,
        mode="issues_only",
        reason=_issues_only_reason(issues_data, provenance_status=provenance_status),
    )
    payload = dict(issues_data)
    payload["assessments"] = {}
    payload[ASSESSMENT_POLICY_KEY] = issues_only_policy.to_dict()
    return payload, []


def assessment_policy_from_payload(
    payload: NormalizedReviewImportPayload | ReviewImportPayload,
) -> AssessmentImportPolicy:
    """Return parsed assessment policy metadata from a loaded import payload."""
    policy = payload[ASSESSMENT_POLICY_KEY]
    if isinstance(policy, dict):
        return policy
    return AssessmentImportPolicyModel().to_dict()


def assessment_policy_model_from_payload(
    payload: NormalizedReviewImportPayload | ReviewImportPayload,
) -> AssessmentImportPolicyModel:
    """Return typed assessment policy metadata from a loaded import payload."""
    return AssessmentImportPolicyModel.from_mapping(
        assessment_policy_from_payload(payload)
    )


def assessment_mode_label(policy: AssessmentImportPolicy) -> str:
    """Return a user-facing label for the selected assessment import mode."""
    mode = AssessmentImportPolicyModel.from_mapping(policy).mode.strip().lower()
    return ASSESSMENT_MODE_LABELS.get(mode, f"unknown ({mode or 'none'})")
