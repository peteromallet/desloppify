"""Tests for the `setup` command."""

from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

import pytest

import desloppify.app.commands.registry as registry_mod
import desloppify.app.commands.setup.cmd as setup_cmd_mod
from desloppify.app.skill_docs import SKILL_VERSION
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
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".config" / "agents").mkdir(parents=True)
    (tmp_path / ".config" / "opencode").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args())

    claude_target = tmp_path / ".claude" / "skills" / "desloppify" / "SKILL.md"
    codex_target = tmp_path / ".codex" / "AGENTS.md"
    gemini_target = tmp_path / ".gemini" / "skills" / "desloppify" / "SKILL.md"
    assert claude_target.is_file()
    assert codex_target.is_file()
    assert gemini_target.is_file()
    assert "desloppify-skill-version" in claude_target.read_text(encoding="utf-8")
    assert "<!-- desloppify-overlay: claude -->" in claude_target.read_text(encoding="utf-8")
    assert "<!-- desloppify-overlay: codex -->" in codex_target.read_text(encoding="utf-8")
    assert "<!-- desloppify-overlay: gemini -->" in gemini_target.read_text(encoding="utf-8")


def test_global_single_interface_installs_only_requested_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".codex").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args(interface="claude"))

    assert (tmp_path / ".claude" / "skills" / "desloppify" / "SKILL.md").is_file()
    assert not (tmp_path / ".codex" / "AGENTS.md").exists()


def test_global_setup_skips_missing_tool_dirs_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".claude").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args())

    out = capsys.readouterr().out
    assert (tmp_path / ".claude" / "skills" / "desloppify" / "SKILL.md").is_file()
    # At least some tools should be reported as skipped
    assert "Skipping" in out


def test_global_setup_errors_when_requested_tool_dir_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with pytest.raises(CommandError, match=r"not found"):
        setup_cmd_mod.cmd_setup(_setup_args(interface="claude"))


def test_global_setup_errors_when_no_supported_tools_detected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with pytest.raises(CommandError, match="No supported AI tools detected"):
        setup_cmd_mod.cmd_setup(_setup_args())


def test_codex_global_setup_uses_section_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Codex uses a shared AGENTS.md — section-replace must preserve other content."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    agents_md = codex_dir / "AGENTS.md"
    agents_md.write_text("# My custom instructions\n\nKeep this content.\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args(interface="codex"))

    content = agents_md.read_text(encoding="utf-8")
    assert "My custom instructions" in content
    assert "desloppify-skill-version" in content
    assert "<!-- desloppify-overlay: codex -->" in content


def test_global_setup_skips_current_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Setup should skip files already at current version."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    skill_path = claude_dir / "skills" / "desloppify" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        f"<!-- desloppify-skill-version: {SKILL_VERSION} -->\ncurrent content\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args(interface="claude"))

    out = capsys.readouterr().out
    assert "up to date" in out.lower()
    # Content should NOT have been overwritten
    assert "current content" in skill_path.read_text(encoding="utf-8")


def test_global_setup_updates_stale_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Setup should overwrite files at an older version."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    skill_path = claude_dir / "skills" / "desloppify" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "<!-- desloppify-skill-version: 1 -->\nold content\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args(interface="claude"))

    out = capsys.readouterr().out
    assert "updated" in out.lower()
    content = skill_path.read_text(encoding="utf-8")
    assert "old content" not in content
    assert f"desloppify-skill-version: {SKILL_VERSION}" in content


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
        "AMP.md",
        "DROID.md",
        "COPILOT.md",
        "OPENCODE.md",
        "ROVODEV.md",
    ):
        text = resource_dir.joinpath(filename).read_text(encoding="utf-8")
        assert text.strip()


def test_rovodev_global_setup_writes_dedicated_skill_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Rovo Dev install should write a dedicated SKILL.md under ~/.rovodev."""
    (tmp_path / ".rovodev").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    setup_cmd_mod.cmd_setup(_setup_args(interface="rovodev"))

    target = tmp_path / ".rovodev" / "skills" / "desloppify" / "SKILL.md"
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert "desloppify-skill-version" in content
    assert "<!-- desloppify-overlay: rovodev -->" in content


def test_setup_parser_accepts_rovodev_choice() -> None:
    parser = create_parser()
    args = parser.parse_args(["setup", "--interface", "rovodev"])
    assert args.interface == "rovodev"
