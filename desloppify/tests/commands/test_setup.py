"""Tests for the bundled offline `setup` command."""

from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

import pytest

import desloppify.app.commands.registry as registry_mod
import desloppify.app.commands.setup.cmd as setup_cmd_mod
from desloppify.base.exception_sets import CommandError
from desloppify.cli import create_parser


def _setup_args(*, interface: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(interface=interface)


def test_setup_parser_and_registry_are_wired() -> None:
    parser = create_parser()
    args = parser.parse_args(["setup", "--interface", "claude"])
    assert args.command == "setup"
    assert args.interface == "claude"

    handlers = registry_mod.get_command_handlers()
    assert handlers["setup"] is setup_cmd_mod.cmd_setup


def test_global_install_writes_supported_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args())

    claude_target = tmp_path / ".claude" / "skills" / "desloppify" / "SKILL.md"
    cursor_target = tmp_path / ".cursor" / "rules" / "desloppify.md"
    assert claude_target.is_file()
    assert cursor_target.is_file()
    assert "desloppify-skill-version" in claude_target.read_text(encoding="utf-8")
    assert "<!-- desloppify-overlay: claude -->" in claude_target.read_text(encoding="utf-8")
    assert "<!-- desloppify-overlay: cursor -->" in cursor_target.read_text(encoding="utf-8")


def test_global_single_interface_installs_only_requested_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args(interface="claude"))

    assert (tmp_path / ".claude" / "skills" / "desloppify" / "SKILL.md").is_file()
    assert not (tmp_path / ".cursor" / "rules" / "desloppify.md").exists()


def test_global_setup_skips_missing_tool_dirs_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".claude").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args())

    out = capsys.readouterr().out
    assert "Installed global skill files:" in out
    assert "Skipping cursor (~/.cursor not found)" in out
    assert (tmp_path / ".claude" / "skills" / "desloppify" / "SKILL.md").is_file()
    assert not (tmp_path / ".cursor" / "rules" / "desloppify.md").exists()


def test_global_setup_errors_when_requested_tool_dir_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with pytest.raises(CommandError, match=r"~/.cursor/ not found"):
        setup_cmd_mod.cmd_setup(_setup_args(interface="cursor"))


def test_global_setup_errors_when_no_supported_tools_detected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with pytest.raises(CommandError, match="No supported AI tools detected"):
        setup_cmd_mod.cmd_setup(_setup_args())


def test_codex_global_setup_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args(interface="codex"))

    out = capsys.readouterr().out
    assert "Codex global skill path is not yet confirmed" in out
    assert not any(tmp_path.iterdir())


def test_bundled_resources_are_readable() -> None:
    resource_dir = files("desloppify.data.global")
    for filename in (
        "SKILL.md",
        "CLAUDE.md",
        "CURSOR.md",
        "CODEX.md",
        "WINDSURF.md",
        "GEMINI.md",
        "HERMES.md",
    ):
        text = resource_dir.joinpath(filename).read_text(encoding="utf-8")
        assert text.strip()
