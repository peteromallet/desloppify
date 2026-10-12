"""Tests for next-command terminal render helpers using realistic data and capsys."""

from __future__ import annotations

import desloppify.app.commands.next.render as render_mod
import desloppify.app.commands.next.render_support as support_mod
from desloppify.engine.plan_triage import (
    triage_manual_stage_command,
    triage_run_stages_command,
)

# ---------------------------------------------------------------------------
# Helpers — realistic work-queue items
# ---------------------------------------------------------------------------

def _issue_item(
    *,
    id: str = "smells::src/util.py::long_fn",
    summary: str = "Function exceeds 50 lines",
    detector: str = "smells",
    confidence: str = "high",
    file: str = "src/util.py",
    detail: dict | None = None,
    primary_command: str = "",
    **extra,
) -> dict:
    base = {
        "id": id,
        "summary": summary,
        "detector": detector,
        "confidence": confidence,
        "file": file,
        "detail": detail or {},
        "primary_command": primary_command,
    }
    base.update(extra)
    return base


def _cluster_item(
    *,
    id: str = "auto/dead-code",
    summary: str = "Remove dead code across 5 files",
    member_count: int = 5,
    action_type: str = "auto_fix",
    members: list[dict] | None = None,
    primary_command: str = "desloppify autofix dead_code --dry-run",
    **extra,
) -> dict:
    base = {
        "id": id,
        "kind": "cluster",
        "summary": summary,
        "member_count": member_count,
        "action_type": action_type,
        "members": members or [],
        "primary_command": primary_command,
    }
    base.update(extra)
    return base


def _workflow_stage_item(
    *,
    id: str = "triage::observe",
    summary: str = "Observe patterns in review work items",
    stage_name: str = "observe",
    is_blocked: bool = False,
    blocked_by: list[str] | None = None,
    primary_command: str = "desloppify plan triage --run-stages --runner codex --only-stages observe",
    detail: dict | None = None,
    **extra,
) -> dict:
    base = {
        "id": id,
        "kind": "workflow_stage",
        "summary": summary,
        "stage_name": stage_name,
        "is_blocked": is_blocked,
        "blocked_by": blocked_by or [],
        "primary_command": primary_command,
        "detail": detail or {},
    }
    base.update(extra)
    return base


def _workflow_action_item(
    *,
    id: str = "workflow::create-plan",
    summary: str = "Create a living plan",
    primary_command: str = "desloppify plan create",
    **extra,
) -> dict:
    base = {
        "id": id,
        "kind": "workflow_action",
        "summary": summary,
        "primary_command": primary_command,
    }
    base.update(extra)
    return base


def _subjective_item(
    *,
    id: str = "review::readability",
    summary: str = "Re-review readability dimension",
    kind: str = "subjective_dimension",
    confidence: str = "low",
    primary_command: str = "desloppify review --prepare",
    detail: dict | None = None,
    **extra,
) -> dict:
    base = {
        "id": id,
        "kind": kind,
        "summary": summary,
        "confidence": confidence,
        "primary_command": primary_command,
        "detail": detail or {"dimension_name": "readability", "strict_score": 72.0},
    }
    base.update(extra)
    return base


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences for easier assertions."""
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in _strip_ansi(text).splitlines() if line.strip()]


def _commands_in_output(text: str) -> list[str]:
    commands: list[str] = []
    for line in _normalized_lines(text):
        idx = line.find("desloppify ")
        if idx >= 0:
            commands.append(line[idx:])
    return commands


# ---------------------------------------------------------------------------
# _item_label
# ---------------------------------------------------------------------------

def test_item_label_single_item_no_queue_pos() -> None:
    item: dict = {"summary": "x"}
    assert render_mod._item_label(item, 0, 1) == "  Next item"


def test_item_label_single_item_with_queue_pos() -> None:
    item: dict = {"summary": "x", "queue_position": 3}
    label = render_mod._item_label(item, 0, 1)
    assert "#3" in label
    assert "Next item" in label


def test_item_label_multiple_items_with_queue_pos() -> None:
    item: dict = {"summary": "x", "queue_position": 5}
    label = render_mod._item_label(item, 2, 4)
    assert "#5" in label


def test_item_label_multiple_items_no_queue_pos() -> None:
    item: dict = {"summary": "x"}
    label = render_mod._item_label(item, 1, 3)
    assert "[2/3]" in label


# ---------------------------------------------------------------------------
# Single issue item rendering
# ---------------------------------------------------------------------------

def test_render_single_issue_item_basic(monkeypatch, capsys) -> None:
    """A single issue item prints confidence, separator, summary, file, and ID."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(
        summary="Function `parse` is 80 lines long",
        file="src/parser.py",
        detail={"lines": [10, 45], "suggestion": "Split into smaller helpers."},
    )

    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Next item" in out
    assert "(high confidence)" in out
    assert "Function `parse` is 80 lines long" in out
    assert "File: src/parser.py" in out
    assert "Lines: 10, 45" in out
    assert "Suggestion: Split into smaller helpers." in out


def test_render_single_issue_detail_string(monkeypatch, capsys) -> None:
    """When detail is a plain string, it should be treated as a suggestion."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(detail="Just a string suggestion")
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Suggestion: Just a string suggestion" in out


def test_render_single_issue_with_plan_description(monkeypatch, capsys) -> None:
    """Plan description is shown when present."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(plan_description="Merge into shared helper")
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Merge into shared helper" in out


def test_render_single_issue_with_plan_cluster_and_steps(monkeypatch, capsys) -> None:
    """Plan cluster info and action steps shown for single-item render."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(
        plan_cluster={
            "name": "import-cleanup",
            "description": "Clean up imports",
            "total_items": 8,
            "action_steps": ["Remove unused imports", "Sort remaining"],
        },
    )
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Cluster: import-cleanup" in out
    assert "Clean up imports" in out
    assert "8 items" in out
    assert "1. Remove unused imports" in out
    assert "2. Sort remaining" in out


def test_render_single_issue_with_category_and_importers(monkeypatch, capsys) -> None:
    """Category and importers are shown when present in detail."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(detail={"category": "complexity", "importers": 3})
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Category: complexity" in out
    assert "Active importers: 3" in out


# ---------------------------------------------------------------------------
# Auto-fix type and batch hint
# ---------------------------------------------------------------------------

def test_render_auto_fix_type_label(monkeypatch, capsys) -> None:
    """An auto-fixable item shows the Type: Auto-fixable label."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(
        primary_command='desloppify plan resolve "unused_import::a" --note "done" --confirm',
        detector="unused_import",
        action_type="auto_fix",
    )
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Type: Auto-fixable" in out


def test_render_auto_fix_batch_hint(monkeypatch, capsys) -> None:
    """When there are multiple similar auto-fixable issues, a batch hint is shown."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(
        primary_command="desloppify autofix unused-imports --dry-run",
        detector="unused",
    )
    issues_scoped = {
        "unused::a.py::x": {"detector": "unused", "status": "open"},
        "unused::b.py::y": {"detector": "unused", "status": "open"},
        "unused::c.py::z": {"detector": "unused", "status": "open"},
    }
    render_mod.render_terminal_items(
        [item], {}, issues_scoped, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Auto-fixable: 3 similar issues" in out


def test_render_review_type_label(monkeypatch, capsys) -> None:
    """A review item shows the design review type label."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(detector="review", summary="Review naming")
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Design review" in out


# ---------------------------------------------------------------------------
# Cluster item rendering
# ---------------------------------------------------------------------------

def test_render_cluster_item_output(monkeypatch, capsys) -> None:
    """Cluster items print type label, member count, summary, sample, and commands."""
    monkeypatch.setattr(support_mod, "colorize", lambda t, _s: t)

    members = [
        {"id": "dead::a.py::f1", "file": "src/a.py"},
        {"id": "dead::b.py::f2", "file": "src/b.py"},
    ]
    item = _cluster_item(members=members, member_count=2)
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    commands = _commands_in_output(out)
    expected = support_mod.cluster_action_commands(item["id"])
    assert "Auto-fixable batch" in out
    assert "2 issues" in out
    assert "Remove dead code" in out
    assert "src/a.py" in out
    for command in expected.values():
        assert command in commands


def test_render_optional_cluster_shows_skip(monkeypatch, capsys) -> None:
    """Optional clusters show a Skip command."""
    monkeypatch.setattr(support_mod, "colorize", lambda t, _s: t)

    item = _cluster_item(cluster_optional=True)
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    commands = _commands_in_output(out)
    expected = support_mod.cluster_action_commands(item["id"])
    assert "optional" in out
    assert expected["skip"] in commands


# ---------------------------------------------------------------------------
# Workflow stage and action rendering
# ---------------------------------------------------------------------------

def test_render_workflow_stage_unblocked(monkeypatch, capsys) -> None:
    """An unblocked workflow stage shows the stage name and action."""
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _workflow_stage_item(
        detail={
            "runner_commands": [
                {
                    "label": "Codex",
                    "command": "desloppify plan triage --run-stages --runner codex --only-stages observe",
                },
                {
                    "label": "Claude",
                    "command": "desloppify plan triage --run-stages --runner claude --only-stages observe",
                },
            ],
            "manual_fallback": 'desloppify plan triage --stage observe --report "analysis of themes and root causes..."',
        },
    )
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    commands = _commands_in_output(out)
    runner_commands = [entry["command"] for entry in item["detail"]["runner_commands"]]
    manual_fallback = item["detail"]["manual_fallback"]
    assert "Planning: observe" in out
    assert item["primary_command"] in commands
    for command in runner_commands:
        assert command in commands
    assert manual_fallback in commands
    assert "[blocked]" not in out


def test_render_workflow_stage_blocked(monkeypatch, capsys) -> None:
    """A blocked workflow stage shows blocked-by info and next step hint."""
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _workflow_stage_item(
        id="triage::organize",
        stage_name="organize",
        is_blocked=True,
        blocked_by=["triage::observe"],
    )
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    commands = _commands_in_output(out)
    dep_name = "observe"
    expected_next = triage_run_stages_command(only_stages=dep_name)
    expected_alt = triage_run_stages_command(runner="claude", only_stages=dep_name)
    expected_manual = triage_manual_stage_command(dep_name)
    assert "[blocked]" in out
    assert "Blocked by: observe" in out
    assert expected_next in commands
    assert expected_alt in commands
    assert expected_manual in commands


def test_render_workflow_stage_with_review_issues(monkeypatch, capsys) -> None:
    """A workflow stage with total_review_issues shows the count."""
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _workflow_stage_item(detail={"total_review_issues": 12})
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "12 review work items" in out


def test_render_workflow_action(monkeypatch, capsys) -> None:
    """Workflow action items print a simple card with summary and command."""
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _workflow_action_item()
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    commands = _commands_in_output(out)
    assert "Create execution plan" in out
    assert "Create a living plan" in out
    assert item["primary_command"] in commands


# ---------------------------------------------------------------------------
# Subjective dimension rendering
# ---------------------------------------------------------------------------

def test_render_subjective_dimension(monkeypatch, capsys) -> None:
    """Subjective dimension items show dimension name, score, and re-review note."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _subjective_item()
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Dimension: readability" in out
    assert "Score: 72.0%" in out
    assert "re-review scores what it finds" in out


def test_render_subjective_dimension_explain_mode(monkeypatch, capsys) -> None:
    """In explain mode, subjective items show policy explanation."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _subjective_item(explain={"policy": "subjective items are deprioritized"})
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=True,
    )
    out = capsys.readouterr().out
    assert "subjective items are deprioritized" in out


# ---------------------------------------------------------------------------
# Explain mode for regular items
# ---------------------------------------------------------------------------

def test_render_explain_mode_shows_ranking_info(monkeypatch, capsys) -> None:
    """Explain mode shows confidence, count, and ID in the explain line."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(
        id="smells::src/a.py::fn",
        confidence="high",
        detail={"count": 5},
    )
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=True,
    )
    out = capsys.readouterr().out
    assert "explain:" in out
    assert "confidence=high" in out
    assert "count=5" in out
    assert "id=smells::src/a.py::fn" in out


# ---------------------------------------------------------------------------
# Grouped output
# ---------------------------------------------------------------------------

def test_render_grouped_output(monkeypatch, capsys) -> None:
    """Group mode delegates to render_grouped and prints grouped output."""
    monkeypatch.setattr(support_mod, "colorize", lambda t, _s: t)
    # Stub group_queue_items to return a simple grouping
    monkeypatch.setattr(
        support_mod, "group_queue_items",
        lambda items, group: {"smells": items},
    )

    items = [
        _issue_item(id="smells::a", summary="Issue A", confidence="high"),
        _issue_item(id="smells::b", summary="Issue B", confidence="low"),
    ]
    render_mod.render_terminal_items(
        items, {}, {}, group="detector", explain=False,
    )
    out = capsys.readouterr().out
    assert "smells (2)" in out
    assert "Issue A" in out
    assert "Issue B" in out


# ---------------------------------------------------------------------------
# Cluster drill-in (compact rendering for follow-up items)
# ---------------------------------------------------------------------------

def test_cluster_drill_in_first_full_rest_compact(monkeypatch, capsys) -> None:
    """With active_cluster, first item is full, rest are compact one-liners."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)
    monkeypatch.setattr(support_mod, "colorize", lambda t, _s: t)

    items = [
        _issue_item(id="smells::a.py::f1", summary="First issue", file="src/a.py"),
        _issue_item(id="smells::b.py::f2", summary="Second issue", file="src/b.py"),
        _issue_item(id="smells::c.py::f3", summary="Third issue", file="src/c.py"),
    ]
    plan = {
        "active_cluster": "import-cleanup",
        "clusters": {"import-cleanup": {"issue_ids": ["smells::a.py::f1", "smells::b.py::f2", "smells::c.py::f3"]}},
    }

    render_mod.render_terminal_items(
        items, {}, {}, group="item", explain=False, plan=plan,
    )
    out = capsys.readouterr().out

    # Focus header
    assert "Cluster: import-cleanup" in out
    # First item is full — has confidence and file
    assert "(high confidence)" in out
    assert "File: src/a.py" in out
    # Compact items show index labels
    assert "[2/3]" in out
    assert "[3/3]" in out
    assert "Second issue" in out
    assert "Third issue" in out


# ---------------------------------------------------------------------------
# Plan note
# ---------------------------------------------------------------------------

def test_render_plan_note_shown(monkeypatch, capsys) -> None:
    """A plan_note on an item is printed."""
    monkeypatch.setattr(render_mod, "read_code_snippet", lambda *a, **k: None)
    monkeypatch.setattr(render_mod, "colorize", lambda t, _s: t)

    item = _issue_item(plan_note="Handle edge case first")
    render_mod.render_terminal_items(
        [item], {}, {}, group="item", explain=False,
    )
    out = capsys.readouterr().out
    assert "Note: Handle edge case first" in out
