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


def _make_args(**overrides) -> SimpleNamespace:
    defaults = {"force_review_rerun": False, "dimensions": None}
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


# -- review_rerun_preflight (gate logic) --------------------------------------


_BUILD_WQ = "desloppify.app.commands.review.preflight.build_work_queue"


def _wq_result(items: list[dict]) -> dict:
    return {
        "items": items,
        "total": len(items),
        "tier_counts": {},
        "requested_tier": None,
        "selected_tier": None,
        "fallback_reason": None,
        "available_tiers": [],
        "grouped": {},
    }


def test_blocked_when_open_objective_items(capsys):
    """Preflight blocks when open objective findings exist."""
    state = _state_with_prior_review()
    items = [
        {"id": f"f{i}", "summary": f"Finding {i}"} for i in range(3)
    ]
    with patch(_BUILD_WQ, return_value=_wq_result(items)):
        with pytest.raises(SystemExit) as exc:
            review_rerun_preflight(state, _make_args())
        assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "objective: 3" in err or "3 open objective finding(s)" in err
    assert "--force-review-rerun" in err


def test_blocked_message_is_concise(capsys):
    """Blocked message does not dump individual finding IDs."""
    state = _state_with_prior_review()
    items = [
        {"id": f"f{i}", "summary": f"Finding {i}"} for i in range(8)
    ]
    with patch(_BUILD_WQ, return_value=_wq_result(items)):
        with pytest.raises(SystemExit):
            review_rerun_preflight(state, _make_args())

    err = capsys.readouterr().err
    assert "objective: 8" in err or "8 open objective finding(s)" in err
    # Should NOT dump individual finding IDs
    assert "f0" not in err
    assert "f7" not in err


def test_allowed_when_queue_empty():
    """Preflight passes silently when no open objective items remain."""
    state = _state_with_prior_review()
    with patch(_BUILD_WQ, return_value=_wq_result([])):
        # Should not raise
        review_rerun_preflight(state, _make_args())


def test_force_review_rerun_bypasses_check(capsys):
    """--force-review-rerun skips the queue check entirely."""
    args = _make_args(force_review_rerun=True)
    # No mock needed — build_work_queue should never be called
    review_rerun_preflight({}, args)

    out = capsys.readouterr().out
    assert "--force-review-rerun" in out
    assert "bypassing" in out


def test_force_review_rerun_does_not_call_build_work_queue():
    """Ensure --force-review-rerun never invokes build_work_queue."""
    args = _make_args(force_review_rerun=True)
    with patch(_BUILD_WQ, side_effect=AssertionError("should not be called")):
        review_rerun_preflight({}, args)


def test_no_prior_review_skips_gate():
    """First review run (no subjective scores) skips the gate entirely."""
    state = {}
    with patch(_BUILD_WQ, side_effect=AssertionError("should not be called")):
        review_rerun_preflight(state, _make_args())


def test_all_zero_subjective_scores_skips_gate():
    """When all subjective scores are 0, this is still a first run."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 0},
            "logic_clarity": {"score": 0},
        }
    }
    with patch(_BUILD_WQ, side_effect=AssertionError("should not be called")):
        review_rerun_preflight(state, _make_args())


def test_prior_subjective_scores_enforces_gate(capsys):
    """When a dimension has a nonzero score, the gate is active."""
    state = _state_with_prior_review()
    items = [{"id": "f1", "summary": "Finding 1"}]
    with patch(_BUILD_WQ, return_value=_wq_result(items)):
        with pytest.raises(SystemExit) as exc:
            review_rerun_preflight(state, _make_args())
        assert exc.value.code == 1

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
    with patch(_BUILD_WQ, return_value=_wq_result([])):
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
    with patch(_BUILD_WQ, return_value=_wq_result([])):
        review_rerun_preflight(
            state, _make_args(), state_file="/tmp/state.json", save_fn=save_fn
        )
    save_fn.assert_not_called()


def test_blocked_message_no_tip_without_dimensions_flag(capsys):
    """Without --dimensions, the Tip line does not appear."""
    state = _state_with_prior_review()
    items = [{"id": "f1", "summary": "Finding 1"}]
    with patch(_BUILD_WQ, return_value=_wq_result(items)):
        with pytest.raises(SystemExit):
            review_rerun_preflight(state, _make_args())

    err = capsys.readouterr().err
    assert "Tip:" not in err


def test_blocked_message_no_tip_when_all_targeted_are_scored(capsys):
    """--dimensions targeting only scored dims: no Tip line (no unscored to suggest)."""
    state = _state_with_prior_review()
    items = [{"id": "f1", "summary": "Finding 1"}]
    args = _make_args(dimensions="naming_quality,logic_clarity")
    with patch(_BUILD_WQ, return_value=_wq_result(items)):
        with pytest.raises(SystemExit):
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
    # build_work_queue should not be called — gate skipped
    with patch(_BUILD_WQ, side_effect=AssertionError("should not be called")):
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
    items = [{"id": "f1", "summary": "Finding 1"}]
    with patch(_BUILD_WQ, return_value=_wq_result(items)):
        with pytest.raises(SystemExit) as exc:
            review_rerun_preflight(state, args)
        assert exc.value.code == 1

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
    items = [{"id": "f1", "summary": "Finding 1"}]
    with patch(_BUILD_WQ, return_value=_wq_result(items)):
        with pytest.raises(SystemExit):
            review_rerun_preflight(state, args)

    err = capsys.readouterr().err
    assert "naming_quality" in err
    assert "design_coherence" in err
    # Should suggest targeting only the unscored dimension
    assert "--dimensions logic_clarity" in err


def test_no_dimensions_flag_blocks_on_any_scored(capsys):
    """Without --dimensions, any nonzero score triggers the gate."""
    state = {
        "subjective_assessments": {
            "naming_quality": {"score": 82.0},
            "logic_clarity": {"score": 0},
        }
    }
    items = [{"id": "f1", "summary": "Finding 1"}]
    with patch(_BUILD_WQ, return_value=_wq_result(items)):
        with pytest.raises(SystemExit):
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
                "refresh_reason": "review_finding_fixed",
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
                "refresh_reason": "mechanical_findings_changed",
            },
            "logic_clarity": {
                "score": 74.0,
                "needs_review_refresh": True,
                "stale_since": "2025-02-01T00:00:00+00:00",
                "refresh_reason": "review_finding_wontfix",
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
                "refresh_reason": "review_finding_fixed",
                "stale_since": "2025-01-01T00:00:00+00:00",
            },
            "logic_clarity": {
                "score": 74.0,
                "needs_review_refresh": True,
                "stale_since": "2025-02-01T00:00:00+00:00",
                "refresh_reason": "mechanical_findings_changed",
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


_PREFLIGHT = "desloppify.app.commands.review.entrypoint.review_rerun_preflight"
_RUNTIME = "desloppify.app.commands.review.entrypoint.command_runtime"
_LANG = "desloppify.app.commands.review.entrypoint.resolve_lang"


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
    rt.state = {}
    rt.config = {}
    return rt


def test_prepare_calls_preflight():
    """Default (prepare) mode invokes preflight."""
    from desloppify.app.commands.review.entrypoint import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.entrypoint.do_prepare"),
    ):
        cmd_review(_review_args())
        mock_pf.assert_called_once()


def test_run_batches_calls_preflight():
    """--run-batches mode invokes preflight."""
    from desloppify.app.commands.review.entrypoint import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.entrypoint._do_run_batches"),
    ):
        cmd_review(_review_args(run_batches=True))
        mock_pf.assert_called_once()


def test_external_start_calls_preflight():
    """--external-start mode invokes preflight."""
    from desloppify.app.commands.review.entrypoint import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.entrypoint.do_external_start"),
    ):
        cmd_review(_review_args(external_start=True))
        mock_pf.assert_called_once()


def test_import_calls_preflight():
    """--import invokes preflight before importing."""
    from desloppify.app.commands.review.entrypoint import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.entrypoint.do_import"),
    ):
        cmd_review(_review_args(import_file="findings.json"))
        mock_pf.assert_called_once()


def test_validate_import_skips_preflight():
    """--validate-import does not invoke preflight."""
    from desloppify.app.commands.review.entrypoint import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.entrypoint.do_validate_import"),
    ):
        cmd_review(_review_args(validate_import_file="findings.json"))
        mock_pf.assert_not_called()


def test_external_submit_calls_preflight():
    """--external-submit invokes preflight before submitting."""
    from desloppify.app.commands.review.entrypoint import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.entrypoint.do_external_submit"),
    ):
        cmd_review(_review_args(
            external_submit=True,
            import_file="out.json",
            session_id="ext_123",
        ))
        mock_pf.assert_called_once()


def test_merge_skips_preflight():
    """--merge does not invoke preflight."""
    from desloppify.app.commands.review.entrypoint import cmd_review

    with (
        patch(_PREFLIGHT) as mock_pf,
        patch(_RUNTIME, return_value=_mock_runtime()),
        patch(_LANG, return_value=MagicMock(name="python")),
        patch("desloppify.app.commands.review.merge.do_merge"),
    ):
        cmd_review(_review_args(merge=True))
        mock_pf.assert_not_called()
