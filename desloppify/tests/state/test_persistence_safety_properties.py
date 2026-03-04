"""Randomized persistence safety regression tests for state payloads."""

from __future__ import annotations

import json
import random

import pytest

from desloppify.base.exception_sets import PersistenceSafetyError
from desloppify.state import empty_state, load_state, save_state


def _valid_issue(issue_id: str) -> dict:
    return {
        "id": issue_id,
        "detector": "unit",
        "file": "src/app.py",
        "tier": 3,
        "confidence": "medium",
        "summary": "sample",
        "detail": {},
        "status": "open",
        "note": None,
        "first_seen": "2026-01-01T00:00:00+00:00",
        "last_seen": "2026-01-01T00:00:00+00:00",
        "resolved_at": None,
        "reopen_count": 0,
    }


def _random_state_payload(rng: random.Random, idx: int) -> dict:
    issue_id = f"issue::{idx}"
    return {
        "version": rng.choice([1, 1, 1, 999]),
        "issues": rng.choice(
            [
                {},
                {issue_id: _valid_issue(issue_id)},
                {issue_id: "not-a-dict"},
                ["bad"],
                "not-a-dict",
                7,
            ]
        ),
        "stats": rng.choice([{}, {"total": idx}, ["bad"], "not-a-dict"]),
        "custom_blob": {
            "case": idx,
            "marker": f"state-{idx}",
        },
    }


def test_state_randomized_load_preserves_custom_payload_and_quarantine(tmp_path):
    rng = random.Random(2)
    for idx in range(30):
        payload = _random_state_payload(rng, idx)
        path = tmp_path / f"state-{idx}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_state(
            path,
            allow_unsafe_coerce=bool(payload.get("version", 0) > 1),
        )
        assert loaded.get("custom_blob") == payload["custom_blob"]

        reasons = loaded.get("_unsafe_load_reasons", [])
        if payload["version"] > 1:
            assert "future_schema_version" in reasons

        mismatches = loaded.get("_load_quarantine", {}).get("container_type_mismatches", {})
        if not isinstance(payload["issues"], dict):
            assert mismatches.get("issues") == payload["issues"]
        if not isinstance(payload["stats"], dict):
            assert mismatches.get("stats") == payload["stats"]

        if isinstance(payload["issues"], dict):
            invalid_issues = loaded.get("_load_quarantine", {}).get("invalid_issues", {})
            for issue_id, issue_payload in payload["issues"].items():
                if not isinstance(issue_payload, dict):
                    assert invalid_issues.get(issue_id) == issue_payload


def test_state_randomized_unsafe_payloads_cannot_auto_save(tmp_path):
    rng = random.Random(3)
    reasons_pool = [
        "future_schema_version",
        "normalized_malformed_sections",
        "legacy_payload_recovered",
    ]
    for idx in range(20):
        state = empty_state()
        reasons = rng.sample(reasons_pool, k=rng.randint(1, len(reasons_pool)))
        state["_unsafe_load_reasons"] = reasons
        path = tmp_path / f"unsafe-state-{idx}.json"

        with pytest.raises(PersistenceSafetyError):
            save_state(state, path)

        save_state(state, path, allow_unsafe_coerce=True)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert "_unsafe_load_reasons" not in persisted
