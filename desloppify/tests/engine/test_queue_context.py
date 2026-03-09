"""Tests for QueueContext dataclass and queue_context() factory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from desloppify.engine._work_queue.context import (
    queue_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_state(**overrides) -> dict:
    state: dict = {"issues": {}, "scan_count": 5}
    state.update(overrides)
    return state


def _state_with_issues(*issues: dict) -> dict:
    return {
        "issues": {f["id"]: f for f in issues},
        "scan_count": 5,
    }


def _issue(fid: str, detector: str = "unused", file: str = "src/a.ts") -> dict:
    return {
        "id": fid,
        "detector": detector,
        "status": "open",
        "file": file,
        "tier": 1,
        "confidence": "high",
        "summary": "test",
        "detail": {},
    }


# ---------------------------------------------------------------------------
# Factory: plan resolution
# ---------------------------------------------------------------------------

class TestQueueContextPlanResolution:
    def test_explicit_plan_used_as_is(self):
        """Explicit plan dict is used without loading from disk."""
        plan = {"queue_order": ["f1"], "skipped": {}}
        ctx = queue_context(_minimal_state(), plan=plan)
        assert ctx.plan is plan
        assert ctx.plan_load_status.degraded is False

    def test_explicit_none_plan(self):
        """Explicit plan=None produces None plan."""
        ctx = queue_context(_minimal_state(), plan=None)
        assert ctx.plan is None
        assert ctx.plan_load_status.degraded is False

    def test_auto_load_plan_from_disk(self):
        """Default sentinel triggers load_plan()."""
        fake_plan = {"queue_order": ["f1"]}
        with patch(
            "desloppify.engine.plan.has_living_plan",
            return_value=True,
        ), patch(
            "desloppify.engine.plan.load_plan",
            return_value=fake_plan,
        ):
            ctx = queue_context(_minimal_state())
        assert ctx.plan is fake_plan
        assert ctx.plan_load_status.degraded is False
        assert ctx.plan_load_status.error_kind is None

    def test_auto_load_plan_handles_failure(self):
        """When load_plan() raises, plan is None."""
        with patch(
            "desloppify.engine.plan.has_living_plan",
            return_value=True,
        ), patch(
            "desloppify.engine.plan.load_plan",
            side_effect=OSError("no plan file"),
        ):
            ctx = queue_context(_minimal_state())
        assert ctx.plan is None
        assert ctx.plan_load_status.degraded is True
        assert ctx.plan_load_status.error_kind == "OSError"

    def test_auto_load_without_plan_file_not_degraded(self):
        """Missing living plan is not treated as degraded mode."""
        with patch(
            "desloppify.engine.plan.has_living_plan",
            return_value=False,
        ):
            ctx = queue_context(_minimal_state())
        assert ctx.plan is None
        assert ctx.plan_load_status.degraded is False
        assert ctx.plan_load_status.error_kind is None


# ---------------------------------------------------------------------------
# Factory: target_strict resolution
# ---------------------------------------------------------------------------

class TestQueueContextTargetStrict:
    def test_explicit_target_strict(self):
        """Explicit target_strict wins over config."""
        ctx = queue_context(
            _minimal_state(),
            plan=None,
            target_strict=80.0,
            config={"target_strict_score": 90.0},
        )
        assert ctx.target_strict == 80.0

    def test_target_strict_from_config(self):
        """target_strict derived from config when not explicit."""
        ctx = queue_context(
            _minimal_state(),
            plan=None,
            config={"target_strict_score": 88.0},
        )
        assert ctx.target_strict == 88.0

    def test_target_strict_fallback(self):
        """Without explicit or config, falls back to 95.0."""
        ctx = queue_context(_minimal_state(), plan=None)
        assert ctx.target_strict == 95.0

    def test_target_strict_fallback_no_key_in_config(self):
        """Config dict without target_strict_score key uses fallback."""
        ctx = queue_context(_minimal_state(), plan=None, config={})
        assert ctx.target_strict == 95.0


# ---------------------------------------------------------------------------
# Factory: policy resolution
# ---------------------------------------------------------------------------

class TestQueueContextPolicy:
    def test_policy_computed_with_resolved_params(self):
        """Policy uses the resolved plan and target_strict."""
        state = _state_with_issues(_issue("f1"))
        plan = {"skipped": {"f1": {"kind": "temporary"}}}
        ctx = queue_context(state, plan=plan, target_strict=80.0)
        # f1 is skipped by plan, so objective_count should be 0
        assert ctx.policy.objective_count == 0
        assert ctx.policy.has_objective_backlog is False

    def test_policy_counts_objective_issues(self):
        """Policy correctly counts open objective issues."""
        state = _state_with_issues(
            _issue("f1"),
            _issue("f2"),
        )
        ctx = queue_context(state, plan=None)
        assert ctx.policy.objective_count == 2
        assert ctx.policy.has_objective_backlog is True

    def test_policy_excludes_subjective_detectors(self):
        """Issues from subjective detectors don't count as objective."""
        state = _state_with_issues(
            _issue("f1", detector="unused"),
            _issue("f2", detector="review"),
        )
        ctx = queue_context(state, plan=None)
        assert ctx.policy.objective_count == 1


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

class TestQueueContextImmutability:
    def test_frozen(self):
        """QueueContext is frozen — attributes cannot be changed."""
        ctx = queue_context(_minimal_state(), plan=None)
        with pytest.raises(AttributeError):
            ctx.plan = {"new": "plan"}  # type: ignore[misc]
        with pytest.raises(AttributeError):
            ctx.target_strict = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration: context flows through build_work_queue
# ---------------------------------------------------------------------------

class TestQueueContextIntegration:
    def test_build_work_queue_uses_context_plan(self):
        """build_work_queue uses context.plan when context is provided."""
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state = _state_with_issues(_issue("f1"))
        plan = {
            "queue_order": ["f1"],
            "skipped": {},
        }
        ctx = queue_context(state, plan=plan)

        # Pass context with plan, but don't set plan on options
        result = build_work_queue(
            state,
            options=QueueBuildOptions(
                count=None,
                context=ctx,
            ),
        )
        # f1 should have plan metadata since context.plan was used
        items = result["items"]
        assert len(items) >= 1
        # The item should exist (plan was applied)
        ids = {item["id"] for item in items}
        assert "f1" in ids

    def test_build_work_queue_lifecycle_filter_uses_pipeline_items(self):
        """Lifecycle filter operates on pipeline items, not raw state.

        The queue no longer computes SubjectiveVisibility policy during
        build — lifecycle gating is done by _apply_lifecycle_filter on
        the items that survived prior pipeline stages.
        """
        from desloppify.engine._work_queue.core import (
            QueueBuildOptions,
            build_work_queue,
        )

        state = _minimal_state()
        ctx = queue_context(state, plan=None)

        # Should succeed without needing to compute policy
        result = build_work_queue(
            state,
            options=QueueBuildOptions(context=ctx),
        )
        assert isinstance(result["items"], list)
