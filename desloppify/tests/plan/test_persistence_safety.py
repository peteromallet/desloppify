"""Safety-focused tests for plan persistence behavior."""

from __future__ import annotations

import json

import pytest

from desloppify.base.exception_sets import PersistenceSafetyError
from desloppify.engine.plan import empty_plan, load_plan, save_plan


class TestPlanLoadSafety:
    def test_missing_file_returns_empty_plan(self, tmp_path):
        loaded = load_plan(tmp_path / "missing-plan.json")
        assert loaded["queue_order"] == []
        assert loaded["version"] == 7

    def test_corrupt_plan_raises_and_writes_quarantine_snapshot(self, tmp_path):
        p = tmp_path / "plan.json"
        p.write_text("{not json")

        with pytest.raises(PersistenceSafetyError) as exc_info:
            load_plan(p)
        assert "DLP_PERSISTENCE_PLAN_PARSE_FAILED" in str(exc_info.value)
        assert list(tmp_path.glob("plan.quarantine.*.json"))

    def test_future_version_requires_explicit_unsafe_override(self, tmp_path):
        p = tmp_path / "plan.json"
        p.write_text(
            json.dumps(
                {
                    "version": 999,
                    "created": "2026-01-01T00:00:00+00:00",
                    "updated": "2026-01-01T00:00:00+00:00",
                    "queue_order": [],
                    "skipped": {},
                }
            )
        )

        with pytest.raises(PersistenceSafetyError) as exc_info:
            load_plan(p)
        assert "DLP_PERSISTENCE_PLAN_FUTURE_VERSION" in str(exc_info.value)

        loaded = load_plan(p, allow_unsafe_coerce=True)
        assert loaded["version"] == 7
        assert "future_schema_version" in loaded.get("_unsafe_load_reasons", [])

    def test_container_mismatch_is_preserved_in_quarantine_bucket(self, tmp_path):
        p = tmp_path / "plan.json"
        p.write_text(
            json.dumps(
                {
                    "version": 7,
                    "created": "2026-01-01T00:00:00+00:00",
                    "updated": "2026-01-01T00:00:00+00:00",
                    "queue_order": {"not": "a-list"},
                    "skipped": {},
                }
            )
        )
        loaded = load_plan(p)
        assert loaded["queue_order"] == []
        mismatch = loaded.get("_load_quarantine", {}).get("container_type_mismatches", {})
        assert mismatch.get("queue_order") == {"not": "a-list"}
        assert "normalized_malformed_sections" in loaded.get("_unsafe_load_reasons", [])


class TestPlanSaveSafety:
    def test_save_blocks_unsafe_payload_without_override(self, tmp_path):
        p = tmp_path / "plan.json"
        plan = empty_plan()
        plan["_unsafe_load_reasons"] = ["future_schema_version"]
        with pytest.raises(PersistenceSafetyError) as exc_info:
            save_plan(plan, p)
        assert "DLP_PERSISTENCE_PLAN_UNSAFE_SAVE_BLOCKED" in str(exc_info.value)

    def test_save_allows_unsafe_payload_with_override(self, tmp_path):
        p = tmp_path / "plan.json"
        plan = empty_plan()
        plan["_unsafe_load_reasons"] = ["future_schema_version"]
        save_plan(plan, p, allow_unsafe_coerce=True)
        loaded = json.loads(p.read_text())
        assert "_unsafe_load_reasons" not in loaded
