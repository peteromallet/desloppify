"""Direct coverage tests for step parser internals."""

from __future__ import annotations

import desloppify.engine._plan.step_parser as parser_mod


def test_flush_step_appends_detail_and_resets_state() -> None:
    steps: list[dict] = []
    current = {"title": "Do thing"}

    next_current, detail_lines = parser_mod._flush_step(
        steps=steps,
        current=current,
        detail_lines=["line one", "line two"],
    )

    assert next_current is None
    assert detail_lines == []
    assert steps == [{"title": "Do thing", "detail": "line one\nline two"}]


def test_consume_indented_line_parses_refs_and_detail_lines() -> None:
    step = {"title": "Demo"}
    detail_lines: list[str] = []

    parser_mod._consume_indented_line("   Refs: a, b , c", current=step, detail_lines=detail_lines)
    parser_mod._consume_indented_line("   additional detail", current=step, detail_lines=detail_lines)

    assert step["issue_refs"] == ["a", "b", "c"]
    assert detail_lines == ["additional detail"]


def test_format_step_lines_handles_dict_and_invalid_values() -> None:
    lines = parser_mod._format_step_lines(
        1,
        {"title": "Task", "done": True, "detail": "a\nb", "issue_refs": ["x"]},
    )
    assert lines == [
        "1. [x] Task",
        "   a",
        "   b",
        "   Refs: x",
        "",
    ]

    assert parser_mod._format_step_lines(2, 123) == [""]


def test_parse_steps_file_ignores_noise_before_first_header() -> None:
    parsed = parser_mod.parse_steps_file(
        "\n".join(
            [
                "noise line",
                "  still noise",
                "1. Real step",
                "   detail",
                "unindented ignored",
            ]
        )
    )

    assert parsed == [{"title": "Real step", "detail": "detail"}]
