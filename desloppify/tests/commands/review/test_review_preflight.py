"""Tests for the review-rerun preflight gate (issue #157)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from desloppify.app.commands.review.helpers import parse_dimensions
from desloppify.app.commands.review.preflight import (
    _scored_dimensions,
    clear_stale_subjective_entries,
    review_rerun_preflight,
)
from desloppify.base.exception_sets import CommandError


def _make_args(**overrides) -> SimpleNamespace:
    defaults = {
        "force_review_rerun": False,
        "dimensions": None,
        "run_batches": False,
        "external_start": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _state_with_prior_review() -> dict:
    """State that has a prior subjective review (nonzero dimension scores)."""
    return {
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
            "logic_clarity": {"score": 90.0},
        },
    }


def _review_issue(*, issue_id: str, dimension: str, status: str = "open") -> dict:
    return {
        "id": issue_id,
        "detector": "review",
        "status": status,
        "file": ".",
        "suppressed": False,
        "detail": {"dimension": dimension},
    }


def _concern_issue(*, issue_id: str, dimension: str, status: str = "open") -> dict:
    return {
        "id": issue_id,
        "detector": "concerns",
        "status": status,
        "file": ".",
        "suppressed": False,
        "detail": {"dimension": dimension},
    }


def _objective_issue(
    *,
    issue_id: str,
    detector: str = "smells",
    dimension: str,
    status: str = "open",
) -> dict:
    return {
        "id": issue_id,
        "detector": detector,
        "status": status,
        "file": ".",
        "suppressed": False,
        "detail": {"dimension": dimension},
    }


# -- review_rerun_preflight (gate logic) --------------------------------------


_QUEUE_CONTEXT = "desloppify.app.commands.review.preflight.queue_context"


def _mock_policy(objective_count: int = 0) -> SimpleNamespace:
    """Create a mock SubjectiveVisibility policy with the given objective count."""
    return SimpleNamespace(
        has_objective_backlog=objective_count > 0,
        objective_count=objective_count,
    )


def _mock_queue_context(
    objective_count: int = 0,
    *,
    execution_count: int | None = None,
) -> SimpleNamespace:
    """Create a mock QueueContext with the given objective count."""
    snapshot = SimpleNamespace(
        objective_in_scope_count=objective_count,
        planned_objective_count=objective_count,
        objective_execution_count=execution_count if execution_count is not None else objective_count,
        all_postflight_review_items=(),
    )
    return SimpleNamespace(
        plan=None,
        target_strict=95.0,
        policy=_mock_policy(objective_count),
        snapshot=snapshot,
    )


def _mock_queue_context_with_reviews(
    *,
    objective_count: int = 0,
    execution_count: int | None = None,
    review_dims: tuple[str, ...] = (),
) -> SimpleNamespace:
    items = tuple(
        {
            "kind": "issue",
            "detector": "review",
            "detail": {"dimension": dimension},
        }
        for dimension in review_dims
    )
    snapshot = SimpleNamespace(
        objective_in_scope_count=objective_count,
        planned_objective_count=objective_count,
        objective_execution_count=execution_count if execution_count is not None else objective_count,
        all_postflight_review_items=items,
    )
    return SimpleNamespace(
        plan=None,
        target_strict=95.0,
        policy=_mock_policy(objective_count),
        snapshot=snapshot,
    )


def test_blocked_when_open_objective_items(capsys):
    """Preflight blocks when open objective issues exist."""
    state = _state_with_prior_review()
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=3)):
        with pytest.raises(CommandError) as exc:
            review_rerun_preflight(state, _make_args())
        assert exc.value.exit_code == 1

    err = capsys.readouterr().err
    assert "Open objective issue(s): 3" in err
    assert "--force-review-rerun" in err


def test_subjective_review_backlog_blocks_preflight(capsys):
    """Open review findings in scored dimensions block rerun preflight."""
    state = _state_with_prior_review()
    state["work_items"] = {
        "review::naming": _review_issue(
            issue_id="review::naming",
            dimension="naming_quality",
        )
    }
    with patch(
        _QUEUE_CONTEXT,
        return_value=_mock_queue_context_with_reviews(review_dims=("naming_quality",)),
    ):
        with pytest.raises(CommandError) as exc:
            review_rerun_preflight(state, _make_args())
        assert exc.value.exit_code == 1

    err = capsys.readouterr().err
    assert "Open subjective queue item(s): 1" in err


def test_subjective_concerns_backlog_blocks_preflight(capsys):
    """Open concerns findings in scored dimensions block rerun preflight."""
    state = _state_with_prior_review()
    state["work_items"] = {
        "concerns::naming": _concern_issue(
            issue_id="concerns::naming",
            dimension="naming_quality",
        )
    }
    with patch(
        _QUEUE_CONTEXT,
        return_value=_mock_queue_context_with_reviews(review_dims=("naming_quality",)),
    ):
        with pytest.raises(CommandError) as exc:
            review_rerun_preflight(state, _make_args())
        assert exc.value.exit_code == 1

    err = capsys.readouterr().err
    assert "Open subjective queue item(s): 1" in err


def test_subjective_review_backlog_is_dimension_filtered():
    """Rerun targeting one scored dimension ignores review backlog in others."""
    state = _state_with_prior_review()
    state["work_items"] = {
        "review::logic": _review_issue(
            issue_id="review::logic",
            dimension="logic_clarity",
        )
    }
    args = _make_args(dimensions="naming_quality")
    with patch(
        _QUEUE_CONTEXT,
        return_value=_mock_queue_context_with_reviews(review_dims=("logic_clarity",)),
    ):
        review_rerun_preflight(state, args)


def test_subjective_assessment_queue_items_do_not_block_targeted_rerun():
    """Visible rerun actions should not fall back to objective backlog counts."""
    state = _state_with_prior_review()
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=0)):
        review_rerun_preflight(state, _make_args(dimensions="naming_quality"))


def test_targeted_dimension_does_not_block_own_preparation():
    """A dimension targeted by --dimensions should not block its own review."""
    state = {
        "subjective_assessments": {
            "mid_level_elegance": {"score": 50.0},
        }
    }
    args = _make_args(dimensions="mid_level_elegance")
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=0)):
        # Should NOT raise — the targeted dimension is the work, not backlog
        review_rerun_preflight(state, args)


def test_blocked_message_is_concise(capsys):
    """Blocked message does not dump individual issue IDs."""
    state = _state_with_prior_review()
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=8)):
        with pytest.raises(CommandError):
            review_rerun_preflight(state, _make_args())

    err = capsys.readouterr().err
    assert "Open objective issue(s): 8" in err


def test_allowed_when_queue_empty():
    """Preflight passes silently when no open objective items remain."""
    state = _state_with_prior_review()
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=0)):
        # Should not raise
        review_rerun_preflight(state, _make_args())


def test_phase_parked_objective_items_do_not_block(capsys):
    """Objective items parked behind a phase gate should not block review reruns."""
    state = _state_with_prior_review()
    # 12 planned objective items, but 0 in current execution phase
    ctx = _mock_queue_context(objective_count=12, execution_count=0)
    with patch(_QUEUE_CONTEXT, return_value=ctx):
        # Should NOT raise — items are not actionable right now
        review_rerun_preflight(state, _make_args())

    # No error output about blocking
    err = capsys.readouterr().err
    assert "Blocked" not in err


def test_force_review_rerun_bypasses_check(capsys):
    """--force-review-rerun skips the queue check entirely."""
    args = _make_args(force_review_rerun=True)
    # No mock needed — build_work_queue should never be called
    review_rerun_preflight({}, args)

    out = capsys.readouterr().out
    assert "--force-review-rerun" in out
    assert "bypassing" in out


def test_no_prior_review_skips_gate():
    """First review run (no subjective scores) skips the gate entirely."""
    state = {}
    review_rerun_preflight(state, _make_args())


def test_all_zero_subjective_scores_skips_gate():
    """When all subjective scores are 0, this is still a first run."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 0},
            "logic_clarity": {"score": 0},
        }
    }
    review_rerun_preflight(state, _make_args())


def test_prior_subjective_scores_enforces_gate(capsys):
    """When a dimension has a nonzero score, the gate is active."""
    state = _state_with_prior_review()
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=1)):
        with pytest.raises(CommandError) as exc:
            review_rerun_preflight(state, _make_args())
        assert exc.value.exit_code == 1

    err = capsys.readouterr().err
    assert "Scored dimensions:" in err
    assert "logic_clarity" in err
    assert "naming_quality" in err
    assert "--force-review-rerun" in err


def test_clears_stale_on_gate_pass():
    """After gate passes, stale markers are cleared and state is saved."""
    state = {
        "subjective_assessments": {
            "naming_quality": {
                "score": 82.0,
                "needs_review_refresh": True,
                "refresh_reason": "x",
                "stale_since": "2025-01-01T00:00:00+00:00",
            },
        },
    }
    save_fn = MagicMock()
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=0)):
        review_rerun_preflight(
            state, _make_args(), state_file="/tmp/state.json", save_fn=save_fn
        )
    save_fn.assert_called_once_with(state, "/tmp/state.json")
    assert "needs_review_refresh" not in state["subjective_assessments"]["naming_quality"]


def test_force_review_rerun_still_clears_stale():
    """--force-review-rerun bypasses the gate but still clears stale markers."""
    state = {
        "subjective_assessments": {
            "naming_quality": {
                "score": 82.0,
                "needs_review_refresh": True,
                "refresh_reason": "x",
                "stale_since": "2025-01-01T00:00:00+00:00",
            },
        },
    }
    save_fn = MagicMock()
    review_rerun_preflight(
        state,
        _make_args(force_review_rerun=True),
        state_file="/tmp/state.json",
        save_fn=save_fn,
    )
    save_fn.assert_called_once()
    assert "needs_review_refresh" not in state["subjective_assessments"]["naming_quality"]


def test_no_stale_markers_skips_save():
    """When nothing is stale, save_fn is not called."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
        },
    }
    save_fn = MagicMock()
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=0)):
        review_rerun_preflight(
            state, _make_args(), state_file="/tmp/state.json", save_fn=save_fn
        )
    save_fn.assert_not_called()


def test_blocked_message_no_tip_without_dimensions_flag(capsys):
    """Without --dimensions, the Tip line does not appear."""
    state = _state_with_prior_review()
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=1)):
        with pytest.raises(CommandError):
            review_rerun_preflight(state, _make_args())

    err = capsys.readouterr().err
    assert "Tip:" not in err


def test_blocked_message_no_tip_when_all_targeted_are_scored(capsys):
    """--dimensions targeting only scored dims: no Tip line (no unscored to suggest)."""
    state = _state_with_prior_review()
    args = _make_args(dimensions="naming_quality,logic_clarity")
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=1)):
        with pytest.raises(CommandError):
            review_rerun_preflight(state, args)

    err = capsys.readouterr().err
    assert "Tip:" not in err
    assert "Resolve open items" in err


# -- per-dimension targeting via --dimensions ----------------------------------


def test_targeting_only_unscored_dims_skips_gate():
    """--dimensions targeting only unscored dimensions bypasses the gate."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
            "logic_clarity": {"score": 0},
        }
    }
    args = _make_args(dimensions="logic_clarity")
    # Gate skipped — no scored dims targeted
    review_rerun_preflight(state, args)


def test_run_batches_uses_prepared_query_dimensions_for_gate():
    """run-batches should honor prepared review dimensions from query.json."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
            "dependency_health": {"score": 0.0},
        }
    }
    args = _make_args(run_batches=True)
    prepared_query = {
        "command": "review",
        "mode": "holistic",
        "dimensions": ["dependency_health"],
        "investigation_batches": [{"name": "dependency_health"}],
    }
    from desloppify.app.commands.helpers.query import QueryLoadResult
    mock_result = QueryLoadResult(ok=True, payload=prepared_query)
    with (
        patch("desloppify.app.commands.review.preflight.load_query_result", return_value=mock_result),
        patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=3)),
    ):
        review_rerun_preflight(state, args)


def test_targeting_scored_dim_enforces_gate(capsys):
    """--dimensions targeting a scored dimension triggers the gate."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
            "logic_clarity": {"score": 0},
        }
    }
    args = _make_args(dimensions="naming_quality")
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=1)):
        with pytest.raises(CommandError) as exc:
            review_rerun_preflight(state, args)
        assert exc.value.exit_code == 1

    err = capsys.readouterr().err
    assert "naming_quality" in err


def test_targeting_mix_of_scored_and_unscored_blocks_and_suggests(capsys):
    """--dimensions with a mix blocks, and suggests the unscored subset."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
            "logic_clarity": {"score": 0},
            "design_coherence": {"score": 90.0},
        }
    }
    args = _make_args(dimensions="naming_quality,logic_clarity,design_coherence")
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=1)):
        with pytest.raises(CommandError):
            review_rerun_preflight(state, args)

    err = capsys.readouterr().err
    assert "naming_quality" in err
    assert "design_coherence" in err
    # Should suggest targeting only the unscored dimension
    assert "--dimensions logic_clarity" in err


def test_targeted_rerun_blocks_on_any_objective_backlog(capsys):
    """Targeted reruns remain blocked while any in-scope objective backlog exists."""
    state = _state_with_prior_review()
    args = _make_args(dimensions="naming_quality")
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=3)):
        with pytest.raises(CommandError) as exc:
            review_rerun_preflight(state, args)
        assert exc.value.exit_code == 1

    err = capsys.readouterr().err
    assert "Open objective issue(s): 3" in err


def test_no_dimensions_flag_blocks_on_any_scored(capsys):
    """Without --dimensions, any nonzero score triggers the gate."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
            "logic_clarity": {"score": 0},
        }
    }
    with patch(_QUEUE_CONTEXT, return_value=_mock_queue_context(objective_count=1)):
        with pytest.raises(CommandError):
            review_rerun_preflight(state, _make_args())


# -- parse_dimensions ----------------------------------------------------------


def test_parse_dimensions_comma_separated():
    args = SimpleNamespace(dimensions="naming_quality,logic_clarity")
    assert parse_dimensions(args) == {"naming_quality", "logic_clarity"}


def test_parse_dimensions_strips_whitespace():
    args = SimpleNamespace(dimensions=" naming_quality , logic_clarity ")
    assert parse_dimensions(args) == {"naming_quality", "logic_clarity"}


def test_parse_dimensions_none():
    args = SimpleNamespace(dimensions=None)
    assert parse_dimensions(args) is None


def test_parse_dimensions_empty_string():
    args = SimpleNamespace(dimensions="")
    assert parse_dimensions(args) is None


def test_parse_dimensions_whitespace_only():
    args = SimpleNamespace(dimensions="   ")
    assert parse_dimensions(args) is None


def test_parse_dimensions_trailing_comma():
    args = SimpleNamespace(dimensions="naming_quality,")
    assert parse_dimensions(args) == {"naming_quality"}


def test_parse_dimensions_missing_attr():
    args = SimpleNamespace()
    assert parse_dimensions(args) is None


# -- _scored_dimensions --------------------------------------------------------


def test_scored_dimensions_empty_state():
    assert _scored_dimensions({}) == []


def test_scored_dimensions_all_zero():
    state = {"subjective_assessments": {"nq": {"score": 0}}}
    assert _scored_dimensions(state) == []


def test_scored_dimensions_nonzero_dict():
    state = {"subjective_assessments": {"nq": {"score": 82.0}, "lc": {"score": 0}}}
    assert _scored_dimensions(state) == ["nq"]


def test_scored_dimensions_legacy_numeric():
    state = {"subjective_assessments": {"nq": 95.0}}
    assert _scored_dimensions(state) == ["nq"]


def test_scored_dimensions_legacy_numeric_zero():
    state = {"subjective_assessments": {"nq": 0}}
    assert _scored_dimensions(state) == []


def test_scored_dimensions_multiple():
    state = {"subjective_assessments": {
        "nq": {"score": 82.0},
        "lc": {"score": 90.0},
        "dc": {"score": 0},
    }}
    assert _scored_dimensions(state) == ["lc", "nq"]


# -- clear_stale_subjective_entries --------------------------------------------


def test_clears_stale_entries():
    """Stale markers are removed; dimension keys returned."""
    state = {
        "subjective_assessments": {
            "naming_quality": {
                "score": 82.0,
                "needs_review_refresh": True,
                "refresh_reason": "review_issue_fixed",
                "stale_since": "2025-01-01T00:00:00+00:00",
            },
            "logic_clarity": {
                "score": 90.0,
            },
        }
    }
    cleared = clear_stale_subjective_entries(state)
    assert cleared == ["naming_quality"]

    nq = state["subjective_assessments"]["naming_quality"]
    assert "needs_review_refresh" not in nq
    assert "stale_since" not in nq
    assert "refresh_reason" not in nq
    # Score is preserved
    assert nq["score"] == 82.0

    # Non-stale dimension untouched
    lc = state["subjective_assessments"]["logic_clarity"]
    assert lc == {"score": 90.0}


def test_clears_multiple_stale_entries():
    state = {
        "subjective_assessments": {
            "naming_quality": {
                "score": 82.0,
                "needs_review_refresh": True,
                "stale_since": "2025-01-01T00:00:00+00:00",
                "refresh_reason": "mechanical_issues_changed",
            },
            "logic_clarity": {
                "score": 74.0,
                "needs_review_refresh": True,
                "stale_since": "2025-02-01T00:00:00+00:00",
                "refresh_reason": "review_issue_wontfix",
            },
        }
    }
    cleared = clear_stale_subjective_entries(state)
    assert sorted(cleared) == ["logic_clarity", "naming_quality"]


def test_no_stale_entries_returns_empty():
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 100.0},
        }
    }
    cleared = clear_stale_subjective_entries(state)
    assert cleared == []


def test_empty_assessments():
    cleared = clear_stale_subjective_entries({})
    assert cleared == []


def test_non_dict_assessment_skipped():
    """Legacy numeric-only assessments are not cleared."""
    state = {
        "subjective_assessments": {
            "naming_quality": 95.0,
        }
    }
    cleared = clear_stale_subjective_entries(state)
    assert cleared == []
    # Value unchanged
    assert state["subjective_assessments"]["naming_quality"] == 95.0


def test_clears_only_targeted_dimensions():
    """When dimensions is provided, only those are cleared."""
    state = {
        "subjective_assessments": {
            "naming_quality": {
                "score": 82.0,
                "needs_review_refresh": True,
                "refresh_reason": "review_issue_fixed",
                "stale_since": "2025-01-01T00:00:00+00:00",
            },
            "logic_clarity": {
                "score": 74.0,
                "needs_review_refresh": True,
                "stale_since": "2025-02-01T00:00:00+00:00",
                "refresh_reason": "mechanical_issues_changed",
            },
        }
    }
    cleared = clear_stale_subjective_entries(state, dimensions={"naming_quality"})
    assert cleared == ["naming_quality"]

    # naming_quality was cleared
    nq = state["subjective_assessments"]["naming_quality"]
    assert "needs_review_refresh" not in nq

    # logic_clarity was NOT cleared
    lc = state["subjective_assessments"]["logic_clarity"]
    assert lc["needs_review_refresh"] is True
    assert lc["stale_since"] == "2025-02-01T00:00:00+00:00"


def test_clears_all_when_dimensions_is_none():
    """When dimensions is None, all stale entries are cleared."""
    state = {
        "subjective_assessments": {
            "naming_quality": {
                "score": 82.0,
                "needs_review_refresh": True,
                "refresh_reason": "x",
                "stale_since": "2025-01-01T00:00:00+00:00",
            },
            "logic_clarity": {
                "score": 74.0,
                "needs_review_refresh": True,
                "refresh_reason": "y",
                "stale_since": "2025-02-01T00:00:00+00:00",
            },
        }
    }
    cleared = clear_stale_subjective_entries(state, dimensions=None)
    assert sorted(cleared) == ["logic_clarity", "naming_quality"]


# -- Mode gating via mock-based dispatch (entrypoint) --------------------------
#
# These tests call cmd_review with patched dependencies and verify that
# review_rerun_preflight is (or is not) invoked depending on the mode.


_PREFLIGHT = "desloppify.app.commands.review.cmd.review_rerun_preflight"
_RUNTIME = "desloppify.app.commands.review.cmd.command_runtime"
_LANG = "desloppify.app.commands.review.cmd.resolve_lang"


def _review_args(**overrides) -> SimpleNamespace:
    """Build a minimal review args namespace for cmd_review."""
    defaults = {
        "path": ".",
        "lang": "python",
        "force_review_rerun": False,
        "dimensions": None,
        "merge": False,
        "run_batches": False,
        "external_start": False,
        "external_submit": False,
        "import_file": None,
        "validate_import_file": None,
        "session_id": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_runtime():
    """Return a mock command_runtime result."""
    rt = MagicMock()
    rt.state_path = "/tmp/state.json"
    rt.state = {"last_scan": "2024-01-01T00:00:00"}
    rt.config = {}
    return rt


def test_prepare_calls_preflight():
    """Default (prepare) mode invokes preflight."""
    from desloppify.app.commands.review.cmd import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.cmd.do_prepare"),
    ):
        cmd_review(_review_args())
        mock_pf.assert_called_once()


def test_run_batches_calls_preflight():
    """--run-batches mode invokes preflight."""
    from desloppify.app.commands.review.cmd import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.cmd.do_run_batches"),
    ):
        cmd_review(_review_args(run_batches=True))
        mock_pf.assert_called_once()


def test_external_start_calls_preflight():
    """--external-start mode invokes preflight."""
    from desloppify.app.commands.review.cmd import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.cmd.do_external_start"),
    ):
        cmd_review(_review_args(external_start=True))
        mock_pf.assert_called_once()


def test_import_skips_preflight():
    """--import skips preflight (import is a resolution step that drains backlog)."""
    from desloppify.app.commands.review.cmd import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.cmd.do_import"),
    ):
        cmd_review(_review_args(import_file="issues.json"))
        mock_pf.assert_not_called()


def test_validate_import_skips_preflight():
    """--validate-import does not invoke preflight."""
    from desloppify.app.commands.review.cmd import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.cmd.do_validate_import"),
    ):
        cmd_review(_review_args(validate_import_file="issues.json"))
        mock_pf.assert_not_called()


def test_external_submit_skips_preflight():
    """--external-submit skips preflight (submit is a resolution step that drains backlog)."""
    from desloppify.app.commands.review.cmd import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.cmd.do_external_submit"),
    ):
        cmd_review(_review_args(
            external_submit=True,
            import_file="out.json",
            session_id="ext_123",
        ))
        mock_pf.assert_not_called()


def test_merge_skips_preflight():
    """--merge does not invoke preflight."""
    from desloppify.app.commands.review.cmd import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.merge.do_merge"),
    ):
        cmd_review(_review_args(merge=True))
        mock_pf.assert_not_called()
