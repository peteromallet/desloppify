"""Direct tests for review parser group builder."""

from __future__ import annotations

import argparse

import desloppify.app.cli_support.parser_groups_admin_review as review_group_mod


def test_add_review_parser_registers_review_command_with_core_flags() -> None:
    parser = argparse.ArgumentParser(prog="desloppify")
    sub = parser.add_subparsers(dest="command")

    review_group_mod._add_review_parser(sub)

    args = parser.parse_args(["review", "--prepare", "--runner", "codex"])
    assert args.command == "review"
    assert args.prepare is True
    assert args.runner == "codex"


def test_add_review_parser_accepts_opencode_runner() -> None:
    parser = argparse.ArgumentParser(prog="desloppify")
    sub = parser.add_subparsers(dest="command")

    review_group_mod._add_review_parser(sub)

    args = parser.parse_args(["review", "--prepare", "--runner", "opencode"])
    assert args.command == "review"
    assert args.prepare is True
    assert args.runner == "opencode"


def test_add_review_parser_invokes_each_option_group_builder_once(monkeypatch) -> None:
    parser = argparse.ArgumentParser(prog="desloppify")
    sub = parser.add_subparsers(dest="command")
    calls: list[str] = []

    monkeypatch.setattr(
        review_group_mod,
        "_add_core_options",
        lambda p: calls.append("core"),
    )
    monkeypatch.setattr(
        review_group_mod,
        "_add_external_review_options",
        lambda p: calls.append("external"),
    )
    monkeypatch.setattr(
        review_group_mod,
        "_add_batch_execution_options",
        lambda p: calls.append("batch"),
    )
    monkeypatch.setattr(
        review_group_mod,
        "_add_trust_options",
        lambda p: calls.append("trust"),
    )
    monkeypatch.setattr(
        review_group_mod,
        "_add_postprocessing_options",
        lambda p: calls.append("post"),
    )

    review_group_mod._add_review_parser(sub)
    assert calls == ["core", "external", "batch", "trust", "post"]
    assert len(calls) == 5
    assert calls[0] == "core"
    assert calls[-1] == "post"
    assert "external" in calls
    assert "trust" in calls
