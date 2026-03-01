"""Tests for centralized print_score_update() helper."""

from __future__ import annotations

from desloppify.app.commands.helpers.score_update import print_score_update
from desloppify.state import ScoreSnapshot


def _make_state(
    overall: float = 70.0,
    objective: float = 65.0,
    strict: float = 60.0,
    verified: float = 55.0,
) -> dict:
    """Build a minimal state dict with embedded scores."""
    return {
        "findings": {},
        "stats": {},
        "overall_score": overall,
        "objective_score": objective,
        "strict_score": strict,
        "verified_strict_score": verified,
    }


def test_print_score_update_shows_all_four_scores(capsys: object) -> None:
    state = _make_state()
    prev = ScoreSnapshot(overall=70.0, objective=65.0, strict=60.0, verified=55.0)
    print_score_update(state, prev)
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "overall" in out
    assert "objective" in out
    assert "strict" in out
    assert "verified" in out
    assert "70.0/100" in out
    assert "65.0/100" in out
    assert "60.0/100" in out
    assert "55.0/100" in out


def test_print_score_update_shows_positive_delta(capsys: object) -> None:
    state = _make_state(overall=75.0, objective=70.0, strict=65.0, verified=60.0)
    prev = ScoreSnapshot(overall=70.0, objective=65.0, strict=60.0, verified=55.0)
    print_score_update(state, prev)
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "+5.0" in out


def test_print_score_update_shows_negative_delta(capsys: object) -> None:
    state = _make_state(overall=65.0, objective=60.0, strict=55.0, verified=50.0)
    prev = ScoreSnapshot(overall=70.0, objective=65.0, strict=60.0, verified=55.0)
    print_score_update(state, prev)
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "-5.0" in out


def test_print_score_update_unavailable_scores(capsys: object) -> None:
    state = {"findings": {}, "stats": {}}
    prev = ScoreSnapshot(overall=None, objective=None, strict=None, verified=None)
    print_score_update(state, prev)
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "unavailable" in out


def test_print_score_update_custom_label(capsys: object) -> None:
    state = _make_state()
    prev = ScoreSnapshot(overall=70.0, objective=65.0, strict=60.0, verified=55.0)
    print_score_update(state, prev, label="Updated")
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Updated:" in out
