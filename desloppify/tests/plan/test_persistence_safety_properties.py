"""Randomized persistence safety regression tests for plan payloads."""

from __future__ import annotations

import json
import random

import pytest

from desloppify.base.exception_sets import PersistenceSafetyError
from desloppify.engine.plan import empty_plan, load_plan, save_plan


def _random_plan_payload(rng: random.Random, idx: int) -> dict:
    return {
        "version": rng.choice([7, 7, 7, 999]),
        "created": "2026-01-01T00:00:00+00:00",
        "updated": "2026-01-01T00:00:00+00:00",
        "queue_order": rng.choice(
            [
                [],
                [f"issue::{idx}"],
                {"bad": idx},
                "not-a-list",
                42,
                None,
            ]
        ),
        "skipped": rng.choice(
            [
                {},
                {
                    f"skip::{idx}": {
                        "issue_id": f"skip::{idx}",
                        "kind": "temporary",
                    }
                },
                ["bad"],
                "not-a-dict",
                42,
            ]
        ),
        "custom_blob": {
            "case": idx,
            "marker": f"plan-{idx}",
        },
    }


def test_plan_randomized_load_preserves_custom_payload_and_quarantine(tmp_path):
    rng = random.Random(0)
    for idx in range(30):
        payload = _random_plan_payload(rng, idx)
        path = tmp_path / f"plan-{idx}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_plan(
            path,
            allow_unsafe_coerce=bool(payload.get("version", 0) > 7),
        )
        assert loaded.get("custom_blob") == payload["custom_blob"]

        reasons = loaded.get("_unsafe_load_reasons", [])
        if payload["version"] > 7:
            assert "future_schema_version" in reasons

        mismatches = loaded.get("_load_quarantine", {}).get("container_type_mismatches", {})
        if not isinstance(payload["queue_order"], list):
            assert mismatches.get("queue_order") == payload["queue_order"]
        if not isinstance(payload["skipped"], dict):
            assert mismatches.get("skipped") == payload["skipped"]


def test_plan_randomized_unsafe_payloads_cannot_auto_save(tmp_path):
    rng = random.Random(1)
    reasons_pool = [
        "future_schema_version",
        "normalized_malformed_sections",
        "legacy_payload_recovered",
    ]
    for idx in range(20):
        plan = empty_plan()
        reasons = rng.sample(reasons_pool, k=rng.randint(1, len(reasons_pool)))
        plan["_unsafe_load_reasons"] = reasons
        path = tmp_path / f"unsafe-plan-{idx}.json"

        with pytest.raises(PersistenceSafetyError):
            save_plan(plan, path)

        save_plan(plan, path, allow_unsafe_coerce=True)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert "_unsafe_load_reasons" not in persisted
