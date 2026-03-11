"""Tests for plan step parser/formatter helpers."""

from __future__ import annotations

from desloppify.engine._plan.step_parser import (
    format_steps,
    normalize_step,
    parse_steps_file,
    step_summary,
)


def test_parse_steps_file_parses_detail_and_refs() -> None:
    parsed = parse_steps_file(
        "\n".join(
            [
                "1. First task",
                "   Add detail line one.",
                "   Add detail line two.",
                "   Refs: issue-1, issue-2",
                "",
                "2. Second task",
                "   Refs: issue-3",
            ]
        )
    )

    assert len(parsed) == 2
    assert parsed[0]["title"] == "First task"
    assert parsed[0]["detail"] == "Add detail line one.\nAdd detail line two."
    assert parsed[0]["issue_refs"] == ["issue-1", "issue-2"]
    assert parsed[1]["title"] == "Second task"
    assert parsed[1]["issue_refs"] == ["issue-3"]


def test_format_steps_renders_done_detail_and_refs() -> None:
    rendered = format_steps(
        [
            {"title": "Do thing", "done": True, "detail": "line a\nline b", "issue_refs": ["x", "y"]},
            {"title": "Second step"},
        ]
    )

    assert "1. [x] Do thing" in rendered
    assert "   line a" in rendered
    assert "   line b" in rendered
    assert "   Refs: x, y" in rendered
    assert "2. Second step" in rendered


def test_normalize_step_and_summary_handle_structured_steps() -> None:
    assert normalize_step({"title": "world"}) == {"title": "world"}
    assert step_summary({"title": "world"}) == "world"
