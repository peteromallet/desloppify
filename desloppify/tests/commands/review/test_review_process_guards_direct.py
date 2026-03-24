"""Direct tests for review packet blinding and subjective import guardrails."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from desloppify.app.commands.review.importing.helpers import (
    ImportLoadConfig,
    ImportPayloadLoadError,
    assessment_mode_label,
    load_import_issues_data,
    print_assessment_mode_banner,
    print_import_load_errors,
)


def _colorize(text: str, _style: str) -> str:
    return text


def _render_import_load_error(
    exc: ImportPayloadLoadError,
    *,
    import_file: Path | str,
    capsys,
) -> str:
    print_import_load_errors(
        exc.errors,
        import_file=str(import_file),
        colorize_fn=_colorize,
    )
    return capsys.readouterr().err


def test_assessment_mode_label_mappings():
    assert assessment_mode_label({"mode": "trusted_internal"}) == (
        "trusted internal (durable scores)"
    )
    assert assessment_mode_label({"mode": "attested_external"}) == (
        "attested external (durable scores)"
    )
    assert assessment_mode_label({"mode": "manual_override"}) == (
        "manual override (provisional scores)"
    )
    assert assessment_mode_label({"mode": "issues_only"}) == (
        "issues-only (assessments skipped)"
    )


def test_print_assessment_mode_banner_for_issues_only(capsys):
    print_assessment_mode_banner(
        {"mode": "issues_only", "assessments_present": True},
        colorize_fn=_colorize,
    )
    out = capsys.readouterr().out
    assert "Assessment import mode: issues-only (assessments skipped)" in out


def test_import_untrusted_assessments_are_dropped_by_default(tmp_path):
    payload = {
        "issues": [],
        "assessments": {
            "naming_quality": 95,
            "logic_clarity": {"score": 92},
        },
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(str(issues_path), config=ImportLoadConfig())
    assert parsed["assessments"] == {}
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "issues_only"
    assert policy["trusted"] is False


def test_import_manual_override_requires_attestation(tmp_path, capsys):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 95},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(manual_override=True),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "--manual-override requires --attest" in err


def test_import_manual_override_allows_untrusted_assessments(tmp_path):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 95},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(
        str(issues_path),
        config=ImportLoadConfig(
            manual_override=True,
            manual_attest="Manual review calibrated after independent audit.",
        ),
    )
    assert parsed["assessments"]["naming_quality"] == 95
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "manual_override"


def test_import_manual_override_rejects_allow_partial_combo(tmp_path, capsys):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 95},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(
                allow_partial=True,
                manual_override=True,
                manual_attest="operator note",
            ),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "--manual-override cannot be combined with --allow-partial" in err


def test_import_config_allows_clean_config_only_path(tmp_path):
    payload = {"issues": [], "assessments": {"naming_quality": 95}}
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(
        str(issues_path),
        config=ImportLoadConfig(manual_override=True, manual_attest="manual override ok"),
    )
    assert parsed["assessments"]["naming_quality"] == 95


def test_import_attested_external_requires_attest_phrases(tmp_path, capsys):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 100},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(
                attested_external=True,
                manual_attest="looks good",
            ),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "--attested-external requires --attest containing both" in err
    assert "Hint: rerun with the required attestation template" in err
    assert "review --validate-import" in err


def test_import_attested_external_rejects_untrusted_provenance(tmp_path, capsys):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 100},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(
                attested_external=True,
                manual_attest=(
                    "I validated this review was completed without awareness of overall score "
                    "and is unbiased."
                ),
            ),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "--attested-external requires valid blind packet provenance" in err
    assert "Hint: if provenance is valid, rerun with" in err
    assert "Issues-only fallback" in err


def test_import_attested_external_accepts_claude_blind_provenance(tmp_path):
    blind_packet = tmp_path / "review_packet_blind.json"
    blind_packet.write_text(json.dumps({"command": "review", "dimensions": ["naming_quality"]}))
    packet_hash = hashlib.sha256(blind_packet.read_bytes()).hexdigest()

    payload = {
        "issues": [],
        "assessments": {"naming_quality": 100},
        "provenance": {
            "kind": "blind_review_batch_import",
            "blind": True,
            "runner": "claude",
            "packet_path": str(blind_packet),
            "packet_sha256": packet_hash,
        },
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(
        str(issues_path),
        config=ImportLoadConfig(
            attested_external=True,
            manual_attest=(
                "I validated this review was completed without awareness of overall score "
                "and is unbiased."
            ),
        ),
    )
    assert parsed["assessments"]["naming_quality"] == 100
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "attested_external"
    assert policy["trusted"] is True


def test_import_attested_external_rejects_non_claude_runner(tmp_path, capsys):
    blind_packet = tmp_path / "review_packet_blind.json"
    blind_packet.write_text(json.dumps({"command": "review", "dimensions": ["naming_quality"]}))
    packet_hash = hashlib.sha256(blind_packet.read_bytes()).hexdigest()

    payload = {
        "issues": [],
        "assessments": {"naming_quality": 100},
        "provenance": {
            "kind": "blind_review_batch_import",
            "blind": True,
            "runner": "codex",
            "packet_path": str(blind_packet),
            "packet_sha256": packet_hash,
        },
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(
                attested_external=True,
                manual_attest=(
                    "I validated this review was completed without awareness of overall score "
                    "and is unbiased."
                ),
            ),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "supports runner='claude'" in err
    assert "Hint: if provenance is valid, rerun with" in err


def test_import_external_opencode_provenance_still_defaults_to_issues_only(tmp_path):
    blind_packet = tmp_path / "review_packet_blind.json"
    blind_packet.write_text(json.dumps({"command": "review", "dimensions": ["naming_quality"]}))
    packet_hash = hashlib.sha256(blind_packet.read_bytes()).hexdigest()

    payload = {
        "issues": [
            {
                "dimension": "naming_quality",
                "identifier": "process_data",
                "summary": "Function name is generic for a payment-reconciliation path.",
                "related_files": ["src/service.ts"],
                "evidence": ["Name does not describe side effects or domain operation."],
                "suggestion": "Rename to reconcile_customer_payment.",
                "confidence": "high",
            }
        ],
        "assessments": {"naming_quality": 95},
        "provenance": {
            "kind": "blind_review_batch_import",
            "blind": True,
            "runner": "opencode",
            "packet_path": str(blind_packet),
            "packet_sha256": packet_hash,
        },
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(str(issues_path), config=ImportLoadConfig())
    assert parsed["assessments"] == {}
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "issues_only"
    assert policy["trusted"] is False
    assert "cannot self-attest trust" in policy["reason"]


def test_import_attested_external_rejects_allow_partial_combo(tmp_path, capsys):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 100},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(
                attested_external=True,
                manual_attest=(
                    "I validated this review was completed without awareness of overall score "
                    "and is unbiased."
                ),
                allow_partial=True,
            ),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "--attested-external cannot be combined with --allow-partial" in err


def test_import_external_trusted_provenance_still_defaults_to_issues_only(tmp_path):
    blind_packet = tmp_path / "review_packet_blind.json"
    blind_packet.write_text(json.dumps({"command": "review", "dimensions": ["naming_quality"]}))
    packet_hash = hashlib.sha256(blind_packet.read_bytes()).hexdigest()

    payload = {
        "issues": [
            {
                "dimension": "naming_quality",
                "identifier": "process_data",
                "summary": "Function name is generic for a payment-reconciliation path.",
                "related_files": ["src/service.ts"],
                "evidence": ["Name does not describe side effects or domain operation."],
                "suggestion": "Rename to reconcile_customer_payment.",
                "confidence": "high",
            }
        ],
        "assessments": {"naming_quality": 95},
        "provenance": {
            "kind": "blind_review_batch_import",
            "blind": True,
            "runner": "codex",
            "packet_path": str(blind_packet),
            "packet_sha256": packet_hash,
        },
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(str(issues_path), config=ImportLoadConfig())
    assert parsed["assessments"] == {}
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "issues_only"
    assert policy["trusted"] is False
    assert "cannot self-attest trust" in policy["reason"]


def test_import_trusted_internal_source_applies_assessments(tmp_path):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 100},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(
        str(issues_path),
        config=ImportLoadConfig(
            trusted_assessment_source=True,
            trusted_assessment_label="internal batch import test",
        ),
    )
    assert parsed["assessments"]["naming_quality"] == 100
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "trusted_internal"
    assert policy["trusted"] is True
    assert policy["reason"] == "internal batch import test"


def test_import_hash_mismatch_falls_back_to_issues_only(tmp_path):
    blind_packet = tmp_path / "review_packet_blind.json"
    blind_packet.write_text(json.dumps({"command": "review"}))
    wrong_hash = "0" * 64

    payload = {
        "issues": [],
        "assessments": {"naming_quality": 95},
        "provenance": {
            "kind": "blind_review_batch_import",
            "blind": True,
            "runner": "codex",
            "packet_path": str(blind_packet),
            "packet_sha256": wrong_hash,
        },
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(str(issues_path), config=ImportLoadConfig())
    assert parsed["assessments"] == {}
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "issues_only"
    assert "hash mismatch" in policy["reason"]
    assert "cannot self-attest trust" in policy["reason"]


def test_import_dimension_feedback_without_trusted_provenance_still_drops_assessment(
    tmp_path,
):
    payload = {
        "issues": [
            {
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Generic name",
                "related_files": ["src/example.ts"],
                "evidence": ["Function name is ambiguous across invoice flow"],
                "suggestion": "Rename to reconcile_invoice",
                "confidence": "medium",
            }
        ],
        "assessments": {"naming_quality": 95},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(str(issues_path), config=ImportLoadConfig())
    assert parsed["assessments"] == {}
    assert parsed["_assessment_policy"]["mode"] == "issues_only"


def test_import_rejects_issues_missing_schema_fields(tmp_path, capsys):
    payload = {
        "issues": [
            {
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Generic name",
                "suggestion": "Rename to reconcile_invoice",
                "confidence": "medium",
            }
        ],
        "assessments": {"naming_quality": 95},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(lang_name="typescript"),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "schema validation failed" in err
    assert "related_files" in err
    assert "evidence" in err


def test_import_rejects_invalid_assessments_shape(tmp_path, capsys):
    payload = {
        "issues": [],
        "assessments": ["naming_quality", 95],
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(str(issues_path), config=ImportLoadConfig())
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "assessments must be an object when provided" in err


def test_import_rejects_invalid_reviewed_files_shape(tmp_path, capsys):
    payload = {
        "issues": [],
        "reviewed_files": "src/a.py",
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(str(issues_path), config=ImportLoadConfig())
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "reviewed_files must be an array when provided" in err


def test_import_allow_partial_bypasses_schema_gate(tmp_path):
    payload = {
        "issues": [
            {
                "dimension": "naming_quality",
                "identifier": "processData",
                "summary": "Generic name",
                "suggestion": "Rename to reconcile_invoice",
                "confidence": "medium",
            }
        ],
        "assessments": {"naming_quality": 95},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(
        str(issues_path),
        config=ImportLoadConfig(lang_name="typescript", allow_partial=True),
    )
    assert parsed["assessments"] == {}
    assert parsed["_assessment_policy"]["mode"] == "issues_only"


def test_import_accepts_perfect_assessment_without_feedback(tmp_path):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 100},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(str(issues_path), config=ImportLoadConfig())
    assert parsed["assessments"] == {}
    assert parsed["_assessment_policy"]["mode"] == "issues_only"


def test_import_trusted_internal_accepts_dimension_notes_feedback(tmp_path):
    payload = {
        "issues": [],
        "dimension_notes": {
            "naming_quality": {
                "evidence": ["Names in payment flow are generic and overloaded."],
                "impact_scope": "module",
                "fix_scope": "multi_file_refactor",
                "confidence": "high",
            }
        },
        "assessments": {"naming_quality": 95},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(
        str(issues_path),
        config=ImportLoadConfig(
            trusted_assessment_source=True,
            trusted_assessment_label="internal batch import test",
        ),
    )
    assert parsed["assessments"]["naming_quality"] == 95
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "trusted_internal"


def test_import_trusted_internal_rejects_sub100_without_feedback(tmp_path, capsys):
    payload = {
        "issues": [],
        "assessments": {"naming_quality": 95},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(
                trusted_assessment_source=True,
                trusted_assessment_label="internal batch import test",
            ),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "assessments below 100.0 must include explicit feedback" in err


def test_import_trusted_internal_rejects_low_score_without_issue(tmp_path, capsys):
    payload = {
        "issues": [],
        "dimension_notes": {
            "naming_quality": {
                "evidence": ["Naming drifts in key workflows."],
                "impact_scope": "module",
                "fix_scope": "multi_file_refactor",
                "confidence": "high",
            }
        },
        "assessments": {"naming_quality": 80},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_issues_data(
            str(issues_path),
            config=ImportLoadConfig(
                trusted_assessment_source=True,
                trusted_assessment_label="internal batch import test",
            ),
        )
    err = _render_import_load_error(exc.value, import_file=issues_path, capsys=capsys)
    assert "assessments below 85.0 must include at least one issue" in err


def test_import_trusted_internal_accepts_low_score_with_issue(tmp_path):
    payload = {
        "issues": [
            {
                "dimension": "naming_quality",
                "identifier": "payment_flow_names",
                "summary": "Generic names in payment flow hide intent",
                "related_files": ["src/payments/service.ts"],
                "evidence": ["processData is used for invoice reconciliation logic"],
                "suggestion": "rename processData to reconcileInvoiceFlow",
                "confidence": "high",
            }
        ],
        "assessments": {"naming_quality": 80},
    }
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps(payload))

    parsed = load_import_issues_data(
        str(issues_path),
        config=ImportLoadConfig(
            trusted_assessment_source=True,
            trusted_assessment_label="internal batch import test",
        ),
    )
    assert parsed["assessments"]["naming_quality"] == 80

