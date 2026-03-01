"""Focused tests for review batch-core payload extraction."""

from __future__ import annotations

from desloppify.app.commands.review import batch_core as batch_core_mod


def test_extract_json_payload_prefers_richer_candidate() -> None:
    raw = """
runner chatter
{"assessments":{"design_coherence":70},"findings":[]}
more chatter
{"assessments":{"design_coherence":71,"logic_clarity":69},"findings":[{"identifier":"x"}],"dimension_notes":{"design_coherence":{"evidence":["a"],"impact_scope":"subsystem","fix_scope":"single_file","confidence":"medium","issues_preventing_higher_score":"n/a"}}}
"""
    payload = batch_core_mod.extract_json_payload(raw, log_fn=lambda _msg: None)
    assert isinstance(payload, dict)
    assessments = payload.get("assessments")
    assert isinstance(assessments, dict)
    assert set(assessments) == {"design_coherence", "logic_clarity"}
    findings = payload.get("findings")
    assert isinstance(findings, list)
    assert len(findings) == 1


def test_extract_json_payload_returns_none_without_valid_contract() -> None:
    logs: list[str] = []
    payload = batch_core_mod.extract_json_payload(
        "noise\n{\"hello\":\"world\"}\n",
        log_fn=logs.append,
    )
    assert payload is None
    assert logs
