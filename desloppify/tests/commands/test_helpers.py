"""Tests for command helper modules: rendering, state, subjective."""

from __future__ import annotations

from types import SimpleNamespace

from desloppify.app.commands.helpers.rendering import (
    print_agent_plan,
    print_ranked_actions,
    print_replacement_groups,
)
from desloppify.app.commands.helpers.state import require_completed_scan, state_path
from desloppify.app.commands.helpers.subjective import print_subjective_followup

# ── rendering.py: print_agent_plan ────────────────────────────────────


def test_print_agent_plan_empty_steps(capsys):
    """Empty step list prints nothing."""
    print_agent_plan([])
    assert capsys.readouterr().out == ""


def test_print_agent_plan_numbered_steps(capsys):
    """Steps are printed numbered starting from 1."""
    print_agent_plan(["do alpha", "do beta"])
    out = capsys.readouterr().out
    assert "1. do alpha" in out
    assert "2. do beta" in out


def test_print_agent_plan_includes_header(capsys):
    """The header is printed before steps."""
    print_agent_plan(["step one"], header="  MY HEADER:")
    out = capsys.readouterr().out
    assert "MY HEADER:" in out


def test_print_agent_plan_next_command(capsys):
    """When next_command is supplied it appears in the output."""
    print_agent_plan(["step"], next_command="desloppify next")
    out = capsys.readouterr().out
    assert "desloppify next" in out


def test_print_agent_plan_no_next_command(capsys):
    """When next_command is omitted, 'Next command' line is absent."""
    print_agent_plan(["step"])
    out = capsys.readouterr().out
    assert "Next command" not in out


# ── rendering.py: print_replacement_groups ────────────────────────────


def test_print_replacement_groups_empty(capsys):
    """Empty groups dict prints nothing."""
    print_replacement_groups({}, title="Replacements")
    assert capsys.readouterr().out == ""


def test_print_replacement_groups_shows_title(capsys):
    """Non-empty groups prints the title."""
    groups = {"/a/b.py": [("old_name", "new_name")]}
    print_replacement_groups(groups, title="Renames:", rel_fn=lambda p: p)
    out = capsys.readouterr().out
    assert "Renames:" in out


def test_print_replacement_groups_shows_arrow(capsys):
    """Replacements show old → new."""
    groups = {"/a/b.py": [("foo", "bar")]}
    print_replacement_groups(groups, title="Changes:", rel_fn=lambda p: p)
    out = capsys.readouterr().out
    # The arrow character
    assert "foo" in out
    assert "bar" in out
    assert "\u2192" in out  # →


def test_print_replacement_groups_sorted_by_filepath(capsys):
    """Files appear in sorted order."""
    groups = {
        "/z/z.py": [("a", "b")],
        "/a/a.py": [("c", "d")],
    }
    print_replacement_groups(groups, title="T:", rel_fn=lambda p: p)
    out = capsys.readouterr().out
    pos_a = out.index("/a/a.py")
    pos_z = out.index("/z/z.py")
    assert pos_a < pos_z


# ── rendering.py: print_ranked_actions ────────────────────────────────


def test_print_ranked_actions_empty(capsys):
    """Empty actions list returns False."""
    assert print_ranked_actions([]) is False
    assert capsys.readouterr().out == ""


def test_print_ranked_actions_zero_count_excluded(capsys):
    """Actions with count=0 are excluded."""
    actions = [{"detector": "smells", "count": 0, "impact": 5.0}]
    assert print_ranked_actions(actions) is False


def test_print_ranked_actions_returns_true(capsys):
    """Non-empty actions return True and print output."""
    actions = [{"detector": "smells", "count": 3, "impact": 5.0, "command": "fix"}]
    assert print_ranked_actions(actions) is True
    out = capsys.readouterr().out
    assert "smells" in out
    assert "3 open" in out


def test_print_ranked_actions_sorted_by_impact(capsys):
    """Higher impact actions appear first."""
    actions = [
        {"detector": "low", "count": 1, "impact": 1.0, "priority": 1},
        {"detector": "high", "count": 1, "impact": 10.0, "priority": 2},
    ]
    print_ranked_actions(actions, limit=10)
    out = capsys.readouterr().out
    pos_high = out.index("high")
    pos_low = out.index("low")
    assert pos_high < pos_low


def test_print_ranked_actions_respects_limit(capsys):
    """Only 'limit' actions are shown."""
    actions = [
        {"detector": f"d{i}", "count": 1, "impact": float(10 - i)}
        for i in range(5)
    ]
    print_ranked_actions(actions, limit=2)
    out = capsys.readouterr().out
    assert "d0" in out
    assert "d1" in out
    assert "d2" not in out


def test_print_ranked_actions_tiebreak_by_count(capsys):
    """Same impact uses count as secondary sort (descending)."""
    actions = [
        {"detector": "few", "count": 1, "impact": 5.0, "priority": 1},
        {"detector": "many", "count": 10, "impact": 5.0, "priority": 2},
    ]
    print_ranked_actions(actions, limit=10)
    out = capsys.readouterr().out
    assert out.index("many") < out.index("few")


# ── state.py: state_path ─────────────────────────────────────────────


def test_state_path_from_explicit_state_arg():
    """Explicit --state argument is used directly."""
    args = SimpleNamespace(state="/custom/path.json", lang=None)
    result = state_path(args)
    assert result is not None
    assert str(result) == "/custom/path.json"


def test_state_path_from_lang_arg():
    """--lang argument produces .desloppify/state-{lang}.json."""
    args = SimpleNamespace(state=None, lang="python")
    result = state_path(args)
    assert result is not None
    assert result.name == "state-python.json"
    assert ".desloppify" in str(result)


def test_state_path_no_args_with_auto_detect(monkeypatch):
    """When neither --state nor --lang is set, auto_detect_lang_name is called."""
    args = SimpleNamespace(state=None, lang=None)
    monkeypatch.setattr(
        "desloppify.app.commands.helpers.state.auto_detect_lang_name",
        lambda _: "typescript",
    )
    # Disable the sole-state-file fallback so the test exercises auto-detect.
    monkeypatch.setattr(
        "desloppify.app.commands.helpers.state._sole_existing_lang_state_file",
        lambda: None,
    )
    result = state_path(args)
    assert result is not None
    assert "state-typescript.json" in str(result)


def test_state_path_returns_none_when_nothing_detected(monkeypatch):
    """When auto-detection fails and no fallback state file exists, returns None."""
    args = SimpleNamespace(state=None, lang=None)
    monkeypatch.setattr(
        "desloppify.app.commands.helpers.state.auto_detect_lang_name",
        lambda _: None,
    )
    monkeypatch.setattr(
        "desloppify.app.commands.helpers.state._sole_existing_lang_state_file",
        lambda: None,
    )
    result = state_path(args)
    assert result is None


# ── state.py: require_completed_scan ──────────────────────────────────


def test_require_completed_scan_with_last_scan():
    """Returns True when state has a last_scan entry."""
    assert require_completed_scan({"last_scan": "2026-01-01"}) is True


def test_require_completed_scan_without_last_scan(capsys):
    """Returns False and prints warning when no last_scan."""
    assert require_completed_scan({}) is False
    out = capsys.readouterr().out
    assert "No scans yet" in out


def test_require_completed_scan_none_last_scan(capsys):
    """Falsy last_scan returns False."""
    assert require_completed_scan({"last_scan": None}) is False


# ── subjective.py: print_subjective_followup ──────────────────────────


def _make_followup(
    *,
    low_assessed: bool = False,
    threshold_label: str = "60",
    rendered: str = "dim1, dim2",
    command: str = "desloppify review",
    integrity_lines: list[tuple[str, str]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        low_assessed=low_assessed,
        threshold_label=threshold_label,
        rendered=rendered,
        command=command,
        integrity_lines=integrity_lines or [],
    )


def test_subjective_followup_nothing_to_show(capsys):
    """When nothing is low and no integrity lines, returns False."""
    followup = _make_followup()
    assert print_subjective_followup(followup) is False
    assert capsys.readouterr().out == ""


def test_subjective_followup_low_assessed(capsys):
    """When low_assessed is truthy, prints quality warning and command."""
    followup = _make_followup(low_assessed=True, rendered="naming, complexity")
    assert print_subjective_followup(followup) is True
    out = capsys.readouterr().out
    assert "Subjective quality" in out
    assert "naming, complexity" in out
    assert "desloppify review" in out


def test_subjective_followup_integrity_lines(capsys):
    """Integrity lines are printed when present."""
    followup = _make_followup(
        integrity_lines=[("yellow", "Check naming conventions")]
    )
    assert print_subjective_followup(followup) is True
    out = capsys.readouterr().out
    assert "Check naming conventions" in out


def test_subjective_followup_both(capsys):
    """Low assessed + integrity lines both appear."""
    followup = _make_followup(
        low_assessed=True,
        integrity_lines=[("dim", "integrity note")],
    )
    assert print_subjective_followup(followup) is True
    out = capsys.readouterr().out
    assert "Subjective quality" in out
    assert "integrity note" in out


def test_subjective_followup_leading_newline(capsys):
    """leading_newline=True adds a newline prefix to first line."""
    followup = _make_followup(low_assessed=True)
    print_subjective_followup(followup, leading_newline=True)
    out = capsys.readouterr().out
    assert out.startswith("\n") or "\n  Subjective" in out


def test_subjective_followup_threshold_label(capsys):
    """Threshold label is embedded in the quality warning."""
    followup = _make_followup(low_assessed=True, threshold_label="75")
    print_subjective_followup(followup)
    out = capsys.readouterr().out
    assert "<75%" in out
