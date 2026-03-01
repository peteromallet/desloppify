"""Direct tests for review packet blinding and subjective import guardrails."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from desloppify.app.commands.review.batches import _require_batches
from desloppify.app.commands.review.import_helpers import (
    ImportPayloadLoadError,
    assessment_mode_label,
    load_import_findings_data,
    print_import_load_errors,
    print_assessment_mode_banner,
)
from desloppify.app.commands.review.prepare import do_prepare
from desloppify.app.commands.review.runner_helpers import write_packet_snapshot


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
    assert assessment_mode_label({"mode": "findings_only"}) == (
        "findings-only (assessments skipped)"
    )


def test_print_assessment_mode_banner_for_findings_only(capsys):
    print_assessment_mode_banner(
        {"mode": "findings_only", "assessments_present": True},
        colorize_fn=_colorize,
    )
    out = capsys.readouterr().out
    assert "Assessment import mode: findings-only (assessments skipped)" in out


def test_import_untrusted_assessments_are_dropped_by_default(tmp_path):
    payload = {
        "findings": [],
        "assessments": {
            "naming_quality": 95,
            "logic_clarity": {"score": 92},
        },
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    assert parsed["assessments"] == {}
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "findings_only"
    assert policy["trusted"] is False


def test_import_manual_override_requires_attestation(tmp_path, capsys):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 95},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            manual_override=True,
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "--manual-override requires --attest" in err


def test_import_manual_override_allows_untrusted_assessments(tmp_path):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 95},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(
        str(findings_path),
        colorize_fn=_colorize,
        manual_override=True,
        manual_attest="Manual review calibrated after independent audit.",
    )
    assert parsed["assessments"]["naming_quality"] == 95
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "manual_override"


def test_import_manual_override_rejects_allow_partial_combo(tmp_path, capsys):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 95},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            allow_partial=True,
            manual_override=True,
            manual_attest="operator note",
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "--manual-override cannot be combined with --allow-partial" in err


def test_import_attested_external_requires_attest_phrases(tmp_path, capsys):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 100},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            attested_external=True,
            manual_attest="looks good",
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "--attested-external requires --attest containing both" in err
    assert "Hint: rerun with the required attestation template" in err
    assert "review --validate-import" in err


def test_import_attested_external_rejects_untrusted_provenance(tmp_path, capsys):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 100},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            attested_external=True,
            manual_attest=(
                "I validated this review was completed without awareness of overall score "
                "and is unbiased."
            ),
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "--attested-external requires valid blind packet provenance" in err
    assert "Hint: if provenance is valid, rerun with" in err
    assert "Findings-only fallback" in err


def test_import_attested_external_accepts_claude_blind_provenance(tmp_path):
    blind_packet = tmp_path / "review_packet_blind.json"
    blind_packet.write_text(json.dumps({"command": "review", "dimensions": ["naming_quality"]}))
    packet_hash = hashlib.sha256(blind_packet.read_bytes()).hexdigest()

    payload = {
        "findings": [],
        "assessments": {"naming_quality": 100},
        "provenance": {
            "kind": "blind_review_batch_import",
            "blind": True,
            "runner": "claude",
            "packet_path": str(blind_packet),
            "packet_sha256": packet_hash,
        },
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(
        str(findings_path),
        colorize_fn=_colorize,
        attested_external=True,
        manual_attest=(
            "I validated this review was completed without awareness of overall score "
            "and is unbiased."
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
        "findings": [],
        "assessments": {"naming_quality": 100},
        "provenance": {
            "kind": "blind_review_batch_import",
            "blind": True,
            "runner": "codex",
            "packet_path": str(blind_packet),
            "packet_sha256": packet_hash,
        },
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            attested_external=True,
            manual_attest=(
                "I validated this review was completed without awareness of overall score "
                "and is unbiased."
            ),
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "supports runner='claude'" in err
    assert "Hint: if provenance is valid, rerun with" in err


def test_import_attested_external_rejects_allow_partial_combo(tmp_path, capsys):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 100},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            attested_external=True,
            manual_attest=(
                "I validated this review was completed without awareness of overall score "
                "and is unbiased."
            ),
            allow_partial=True,
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "--attested-external cannot be combined with --allow-partial" in err


def test_import_external_trusted_provenance_still_defaults_to_findings_only(tmp_path):
    blind_packet = tmp_path / "review_packet_blind.json"
    blind_packet.write_text(json.dumps({"command": "review", "dimensions": ["naming_quality"]}))
    packet_hash = hashlib.sha256(blind_packet.read_bytes()).hexdigest()

    payload = {
        "findings": [
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
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    assert parsed["assessments"] == {}
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "findings_only"
    assert policy["trusted"] is False
    assert "cannot self-attest trust" in policy["reason"]


def test_import_trusted_internal_source_applies_assessments(tmp_path):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 100},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(
        str(findings_path),
        colorize_fn=_colorize,
        trusted_assessment_source=True,
        trusted_assessment_label="internal batch import test",
    )
    assert parsed["assessments"]["naming_quality"] == 100
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "trusted_internal"
    assert policy["trusted"] is True
    assert policy["reason"] == "internal batch import test"


def test_import_hash_mismatch_falls_back_to_findings_only(tmp_path):
    blind_packet = tmp_path / "review_packet_blind.json"
    blind_packet.write_text(json.dumps({"command": "review"}))
    wrong_hash = "0" * 64

    payload = {
        "findings": [],
        "assessments": {"naming_quality": 95},
        "provenance": {
            "kind": "blind_review_batch_import",
            "blind": True,
            "runner": "codex",
            "packet_path": str(blind_packet),
            "packet_sha256": wrong_hash,
        },
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    assert parsed["assessments"] == {}
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "findings_only"
    assert "hash mismatch" in policy["reason"]
    assert "cannot self-attest trust" in policy["reason"]


def test_import_dimension_feedback_without_trusted_provenance_still_drops_assessment(
    tmp_path,
):
    payload = {
        "findings": [
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
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    assert parsed["assessments"] == {}
    assert parsed["_assessment_policy"]["mode"] == "findings_only"


def test_import_rejects_findings_missing_schema_fields(tmp_path, capsys):
    payload = {
        "findings": [
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
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            lang_name="typescript",
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "schema validation failed" in err
    assert "related_files" in err
    assert "evidence" in err


def test_import_rejects_invalid_assessments_shape(tmp_path, capsys):
    payload = {
        "findings": [],
        "assessments": ["naming_quality", 95],
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "assessments must be an object when provided" in err


def test_import_rejects_invalid_reviewed_files_shape(tmp_path, capsys):
    payload = {
        "findings": [],
        "reviewed_files": "src/a.py",
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "reviewed_files must be an array when provided" in err


def test_import_allow_partial_bypasses_schema_gate(tmp_path):
    payload = {
        "findings": [
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
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(
        str(findings_path),
        colorize_fn=_colorize,
        lang_name="typescript",
        allow_partial=True,
    )
    assert parsed["assessments"] == {}
    assert parsed["_assessment_policy"]["mode"] == "findings_only"


def test_import_accepts_perfect_assessment_without_feedback(tmp_path):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 100},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(str(findings_path), colorize_fn=_colorize)
    assert parsed["assessments"] == {}
    assert parsed["_assessment_policy"]["mode"] == "findings_only"


def test_import_trusted_internal_accepts_dimension_notes_feedback(tmp_path):
    payload = {
        "findings": [],
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
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(
        str(findings_path),
        colorize_fn=_colorize,
        trusted_assessment_source=True,
        trusted_assessment_label="internal batch import test",
    )
    assert parsed["assessments"]["naming_quality"] == 95
    policy = parsed.get("_assessment_policy", {})
    assert policy["mode"] == "trusted_internal"


def test_import_trusted_internal_rejects_sub100_without_feedback(tmp_path, capsys):
    payload = {
        "findings": [],
        "assessments": {"naming_quality": 95},
    }
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            trusted_assessment_source=True,
            trusted_assessment_label="internal batch import test",
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "assessments below 100.0 must include explicit feedback" in err


def test_import_trusted_internal_rejects_low_score_without_finding(tmp_path, capsys):
    payload = {
        "findings": [],
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
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    with pytest.raises(ImportPayloadLoadError) as exc:
        load_import_findings_data(
            str(findings_path),
            colorize_fn=_colorize,
            trusted_assessment_source=True,
            trusted_assessment_label="internal batch import test",
        )
    err = _render_import_load_error(exc.value, import_file=findings_path, capsys=capsys)
    assert "assessments below 85.0 must include at least one finding" in err


def test_import_trusted_internal_accepts_low_score_with_finding(tmp_path):
    payload = {
        "findings": [
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
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(payload))

    parsed = load_import_findings_data(
        str(findings_path),
        colorize_fn=_colorize,
        trusted_assessment_source=True,
        trusted_assessment_label="internal batch import test",
    )
    assert parsed["assessments"]["naming_quality"] == 80


def test_write_packet_snapshot_redacts_target_from_blind_packet(tmp_path):
    packet = {
        "command": "review",
        "config": {"target_strict_score": 98, "noise_budget": 10},
        "narrative": {"headline": "target score pressure"},
        "next_command": "desloppify scan",
        "dimensions": ["high_level_elegance"],
    }
    review_packet_dir = tmp_path / "review_packets"
    blind_path = tmp_path / "review_packet_blind.json"

    def _safe_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    packet_path, _ = write_packet_snapshot(
        packet,
        stamp="20260218_160000",
        review_packet_dir=review_packet_dir,
        blind_path=blind_path,
        safe_write_text_fn=_safe_write,
    )

    immutable_payload = json.loads(packet_path.read_text())
    blind_payload = json.loads(blind_path.read_text())

    assert immutable_payload["config"]["target_strict_score"] == 98
    assert "target_strict_score" not in blind_payload["config"]
    assert blind_payload["config"]["noise_budget"] == 10
    assert "narrative" not in blind_payload
    assert "next_command" not in blind_payload


_P_SETUP = "desloppify.app.commands.review.prepare.review_runtime_mod.setup_lang_concrete"
_P_NARRATIVE = "desloppify.app.commands.review.prepare.narrative_mod.compute_narrative"
_P_REVIEW_PREP = "desloppify.app.commands.review.prepare.review_mod.prepare_holistic_review"
_P_REVIEW_OPTS = "desloppify.app.commands.review.prepare.review_mod.HolisticReviewPrepareOptions"
_P_NARRATIVE_CTX = "desloppify.app.commands.review.prepare.narrative_mod.NarrativeContext"
_P_WRITE_QUERY = "desloppify.app.commands.review.prepare.write_query"


def _do_prepare_patched(*, total_files: int = 3, state: dict | None = None, config: dict | None = None):
    """Call do_prepare with mocked dependencies; return captured write_query payload."""
    args = SimpleNamespace(path=".", dimensions=None)
    captured: dict = {}

    def _fake_write_query(payload):
        captured.update(payload)

    with (
        patch(_P_SETUP, return_value=(SimpleNamespace(name="python"), [])),
        patch(_P_NARRATIVE, return_value={"headline": "x"}),
        patch(_P_REVIEW_PREP, return_value={
            "total_files": total_files,
            "investigation_batches": [],
            "workflow": [],
        }),
        patch(_P_REVIEW_OPTS, side_effect=lambda **kw: SimpleNamespace(**kw)),
        patch(_P_NARRATIVE_CTX, side_effect=lambda **kw: SimpleNamespace(**kw)),
        patch(_P_WRITE_QUERY, side_effect=_fake_write_query),
    ):
        do_prepare(
            args,
            state=state or {},
            lang=SimpleNamespace(name="python"),
            _state_path=None,
            config=config or {},
        )
    return captured


def test_review_prepare_zero_files_exits_with_error(capsys):
    """Regression guard for issue #127: 0-file result must error, not silently succeed."""
    with pytest.raises(SystemExit) as exc:
        _do_prepare_patched(total_files=0)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no files found" in err.lower()


def test_review_prepare_zero_files_hints_scan_path(capsys):
    """When state has a scan_path, the error hint mentions it."""
    with pytest.raises(SystemExit):
        _do_prepare_patched(total_files=0, state={"scan_path": "."})
    err = capsys.readouterr().err
    assert "--path" in err


def test_review_prepare_query_redacts_target_score():
    captured = _do_prepare_patched(
        total_files=3,
        config={"target_strict_score": 98, "noise_budget": 10},
    )

    assert "config" in captured
    config = captured["config"]
    assert isinstance(config, dict)
    assert "target_strict_score" not in config
    assert config.get("noise_budget") == 10


def test_require_batches_guides_rebuild_when_packet_has_no_batches(capsys):
    with pytest.raises(SystemExit) as exc:
        _require_batches(
            {"investigation_batches": []},
            colorize_fn=_colorize,
            suggested_prepare_cmd="desloppify review --prepare --path src",
        )
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no investigation_batches" in err
    assert "Regenerate review context first" in err
    assert "review --run-batches --runner codex --parallel --scan-after-import" in err
