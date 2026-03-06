"""Tests for plan commit-log command handlers using realistic plan data."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import desloppify.app.commands.plan.commit_log_handlers as commit_log_mod


# ---------------------------------------------------------------------------
# Helpers — realistic plan/state builders
# ---------------------------------------------------------------------------

def _git_context(
    *,
    available: bool = True,
    branch: str = "feat/cleanup",
    head_sha: str = "abc1234567890",
    has_uncommitted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        available=available, branch=branch, head_sha=head_sha,
        has_uncommitted=has_uncommitted,
    )


def _base_plan(
    *,
    uncommitted: list[str] | None = None,
    commit_log: list[dict] | None = None,
    queue_order: list[str] | None = None,
) -> dict:
    return {
        "uncommitted_issues": list(uncommitted or []),
        "commit_log": list(commit_log or []),
        "queue_order": queue_order or [],
        "execution_log": [],
    }


def _record_args(
    *,
    sha: str | None = None,
    branch: str | None = None,
    note: str | None = None,
    only: list[str] | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(sha=sha, branch=branch, note=note, only=only)


def _history_args(*, top: int = 10) -> argparse.Namespace:
    return argparse.Namespace(top=top)


# ---------------------------------------------------------------------------
# cmd_commit_log_dispatch
# ---------------------------------------------------------------------------

def test_dispatch_warns_when_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {"commit_tracking_enabled": False})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod.cmd_commit_log_dispatch(argparse.Namespace(commit_log_action=None))

    out = capsys.readouterr().out
    assert "Commit tracking is disabled" in out


def test_dispatch_no_action_shows_status(monkeypatch, capsys) -> None:
    plan = _base_plan(uncommitted=["smells::a.py::fn"])
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {})
    monkeypatch.setattr(commit_log_mod, "load_plan", lambda *a, **kw: plan)
    monkeypatch.setattr(commit_log_mod, "command_runtime", lambda args: SimpleNamespace(state={}, config={}, state_path=None))
    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod.cmd_commit_log_dispatch(argparse.Namespace(commit_log_action=None))

    out = capsys.readouterr().out
    assert "Commit Tracking Status" in out
    assert "Uncommitted:  1 issue(s)" in out
    assert "smells::a.py::fn" in out


def test_dispatch_routes_record_action(monkeypatch, capsys) -> None:
    """Dispatch with action='record' routes to the record handler."""
    plan = _base_plan(uncommitted=["smells::a.py::fn"])
    saved: list[dict] = []

    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {})
    monkeypatch.setattr(commit_log_mod, "load_plan", lambda *a, **kw: plan)
    monkeypatch.setattr(commit_log_mod, "command_runtime", lambda args: SimpleNamespace(state={}, config={}, state_path=None))
    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "save_plan", lambda *a, **kw: saved.append(a[0]))
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    args = argparse.Namespace(
        commit_log_action="record", sha=None, branch=None, note=None, only=None,
    )
    commit_log_mod.cmd_commit_log_dispatch(args)

    out = capsys.readouterr().out
    assert "Recorded commit" in out
    assert saved


# ---------------------------------------------------------------------------
# _cmd_commit_log_status
# ---------------------------------------------------------------------------

def test_status_shows_git_info(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    plan = _base_plan(uncommitted=["a::b", "c::d"])
    commit_log_mod._cmd_commit_log_status(plan)

    out = capsys.readouterr().out
    assert "Branch:  feat/cleanup" in out
    assert "HEAD:    abc1234567890" in out
    assert "Uncommitted:  2 issue(s)" in out


def test_status_git_not_available(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context(available=False))
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_status(_base_plan())

    out = capsys.readouterr().out
    assert "Git: not available" in out


def test_status_shows_pr_number(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {"commit_pr": 42})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_status(_base_plan())

    out = capsys.readouterr().out
    assert "PR:      #42" in out


def test_status_shows_committed_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    plan = _base_plan(commit_log=[
        {"sha": "aaa", "issue_ids": ["x::1", "x::2"]},
        {"sha": "bbb", "issue_ids": ["y::1"]},
    ])
    commit_log_mod._cmd_commit_log_status(plan)

    out = capsys.readouterr().out
    assert "Committed:    3 issue(s) in 2 commit(s)" in out


def test_status_empty_shows_hint(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_status(_base_plan())

    out = capsys.readouterr().out
    assert "No commit tracking data yet" in out


# ---------------------------------------------------------------------------
# _cmd_commit_log_record — plan mutation
# ---------------------------------------------------------------------------

def test_record_all_uncommitted(monkeypatch, capsys) -> None:
    """Record without --only moves all uncommitted issues to commit_log."""
    plan = _base_plan(uncommitted=["a::1", "b::2", "c::3"])
    saved: list[dict] = []

    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "save_plan", lambda *a, **kw: saved.append(a[0]))
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {"commit_pr": 0})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_record(_record_args(), plan)

    out = capsys.readouterr().out
    assert "Recorded commit" in out
    assert "3 issue(s)" in out

    # Plan was actually mutated by record_commit
    assert len(plan["commit_log"]) == 1
    assert plan["uncommitted_issues"] == []
    assert set(plan["commit_log"][0]["issue_ids"]) == {"a::1", "b::2", "c::3"}


def test_record_with_only_filter(monkeypatch, capsys) -> None:
    """Record with --only only records matching issues."""
    plan = _base_plan(uncommitted=["smells::a.py::fn", "unused::b.py::x", "smells::c.py::g"])
    saved: list[dict] = []

    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "save_plan", lambda *a, **kw: saved.append(a[0]))
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {"commit_pr": 0})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_record(
        _record_args(only=["smells::*"]), plan,
    )

    out = capsys.readouterr().out
    assert "2 issue(s)" in out

    # Verify plan mutation: only smells issues recorded
    assert plan["uncommitted_issues"] == ["unused::b.py::x"]
    assert len(plan["commit_log"]) == 1
    assert set(plan["commit_log"][0]["issue_ids"]) == {"smells::a.py::fn", "smells::c.py::g"}


def test_record_no_uncommitted_warns(monkeypatch, capsys) -> None:
    """Record with empty uncommitted list prints a warning."""
    plan = _base_plan()

    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_record(_record_args(), plan)

    out = capsys.readouterr().out
    assert "No uncommitted issues" in out
    assert plan["commit_log"] == []


def test_record_only_no_match_warns(monkeypatch, capsys) -> None:
    """Record with --only that matches nothing prints a warning."""
    plan = _base_plan(uncommitted=["smells::a.py::fn"])

    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_record(
        _record_args(only=["nonexistent::*"]), plan,
    )

    out = capsys.readouterr().out
    assert "No uncommitted issues match" in out
    assert plan["commit_log"] == []


def test_record_explicit_sha_and_branch(monkeypatch, capsys) -> None:
    """Explicit --sha and --branch override git detection."""
    plan = _base_plan(uncommitted=["a::1"])
    saved: list[dict] = []

    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context(available=False))
    monkeypatch.setattr(commit_log_mod, "save_plan", lambda *a, **kw: saved.append(a[0]))
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {"commit_pr": 0})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_record(
        _record_args(sha="deadbeef", branch="manual-branch"), plan,
    )

    assert plan["commit_log"][0]["sha"] == "deadbeef"
    assert plan["commit_log"][0]["branch"] == "manual-branch"


def test_record_appends_execution_log(monkeypatch, capsys) -> None:
    """Record appends an entry to the execution log via append_log_entry."""
    plan = _base_plan(uncommitted=["a::1"])

    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "save_plan", lambda *a, **kw: None)
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {"commit_pr": 0})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_record(_record_args(note="first fix"), plan)

    log = plan.get("execution_log", [])
    assert len(log) == 1
    assert log[0]["action"] == "commit_record"
    assert log[0]["note"] == "first fix"
    assert "a::1" in log[0]["issue_ids"]


def test_record_with_note_shows_note(monkeypatch, capsys) -> None:
    plan = _base_plan(uncommitted=["a::1"])

    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context())
    monkeypatch.setattr(commit_log_mod, "save_plan", lambda *a, **kw: None)
    monkeypatch.setattr(commit_log_mod, "load_config", lambda: {"commit_pr": 0})
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_record(_record_args(note="import cleanup"), plan)

    out = capsys.readouterr().out
    assert "Note: import cleanup" in out


def test_record_no_git_no_sha_warns(monkeypatch, capsys) -> None:
    """Without git and without --sha, record warns and does nothing."""
    plan = _base_plan(uncommitted=["a::1"])

    monkeypatch.setattr(commit_log_mod, "detect_git_context", lambda: _git_context(available=False))
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_record(_record_args(), plan)

    out = capsys.readouterr().out
    assert "Cannot detect HEAD" in out
    assert plan["commit_log"] == []


# ---------------------------------------------------------------------------
# _cmd_commit_log_history
# ---------------------------------------------------------------------------

def test_history_empty(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    commit_log_mod._cmd_commit_log_history(_history_args(), _base_plan())

    out = capsys.readouterr().out
    assert "No commits recorded yet" in out


def test_history_shows_records(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    plan = _base_plan(commit_log=[
        {
            "sha": "abc1234567890",
            "branch": "feat/cleanup",
            "issue_ids": ["smells::a.py::fn", "unused::b.py::x"],
            "note": "first batch",
            "recorded_at": "2026-03-04T10:00:00Z",
        },
        {
            "sha": "def5678901234",
            "branch": "feat/cleanup",
            "issue_ids": ["smells::c.py::g"],
            "note": "",
            "recorded_at": "2026-03-04T11:00:00Z",
        },
    ])
    commit_log_mod._cmd_commit_log_history(_history_args(), plan)

    out = capsys.readouterr().out
    assert "Commit History" in out
    assert "abc1234" in out
    assert "(feat/cleanup)" in out
    assert "2 issue(s)" in out
    assert "smells::a.py::fn" in out
    assert "Note: first batch" in out
    assert "def5678" in out
    assert "1 issue(s)" in out


def test_history_top_limits(monkeypatch, capsys) -> None:
    """--top limits how many records are shown."""
    monkeypatch.setattr(commit_log_mod, "colorize", lambda t, _s: t)

    records = [
        {"sha": f"sha{i:010d}", "branch": "main", "issue_ids": [f"x::{i}"], "note": "", "recorded_at": ""}
        for i in range(5)
    ]
    plan = _base_plan(commit_log=records)
    commit_log_mod._cmd_commit_log_history(_history_args(top=2), plan)

    out = capsys.readouterr().out
    # Only last 2 shown (SHAs truncated to 7 chars)
    lines = out.strip().split("\n")
    # Should contain records for index 3 and 4, not 0-2
    # SHAs are "sha0000000003" -> "sha0000" (7 chars), etc.
    issue_lines = [l for l in lines if "x::" in l]
    assert len(issue_lines) == 2
    assert "x::4" in out
    assert "x::3" in out
    assert "x::0" not in out


# ---------------------------------------------------------------------------
# _cmd_commit_log_pr — PR body generation
# ---------------------------------------------------------------------------

def test_pr_body_no_commits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "state_mod", SimpleNamespace(
        load_state=lambda: {"issues": {}},
    ))

    commit_log_mod._cmd_commit_log_pr(_base_plan())

    out = capsys.readouterr().out
    assert "No commits recorded yet" in out


def test_pr_body_with_commits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_log_mod, "state_mod", SimpleNamespace(
        load_state=lambda: {
            "issues": {
                "smells::a.py::fn": {"summary": "Long function in parser"},
            },
        },
    ))

    plan = _base_plan(commit_log=[
        {
            "sha": "abc1234567890",
            "branch": "main",
            "issue_ids": ["smells::a.py::fn"],
            "note": "cleanup",
            "recorded_at": "2026-03-04T10:00:00Z",
        },
    ])
    commit_log_mod._cmd_commit_log_pr(plan)

    out = capsys.readouterr().out
    assert "## Code Health Improvements" in out
    assert "**abc1234**" in out
    assert "cleanup" in out
    assert "smells::a.py::fn" in out
    assert "Long function in parser" in out
    assert "1 issue resolved across 1 commit" in out


def test_pr_body_state_load_failure(monkeypatch, capsys) -> None:
    """If load_state fails, PR body still renders with empty state."""
    monkeypatch.setattr(commit_log_mod, "state_mod", SimpleNamespace(
        load_state=lambda: (_ for _ in ()).throw(OSError("no state")),
    ))

    plan = _base_plan(commit_log=[
        {"sha": "aaa", "issue_ids": ["x::1"], "note": "", "recorded_at": ""},
    ])
    commit_log_mod._cmd_commit_log_pr(plan)

    out = capsys.readouterr().out
    assert "## Code Health Improvements" in out
    assert "x::1" in out
