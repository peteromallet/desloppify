"""Direct coverage tests for the update-skill command module."""

from __future__ import annotations

import argparse
import errno
from pathlib import Path

import pytest

import desloppify.app.commands.update_skill.cmd as update_skill_cmd_mod
from desloppify.base.exception_sets import CommandError


def test_update_skill_helper_functions_cover_frontmatter_resolution_and_replace() -> None:
    content = (
        "<!-- desloppify-begin -->\n"
        "<!-- version -->\n"
        "---\n"
        "name: skill\n"
        "---\n"
        "body\n"
    )
    reordered = update_skill_cmd_mod._ensure_frontmatter_first(content)
    assert reordered.startswith("---\nname: skill\n---\n")
    assert "<!-- desloppify-begin -->" in reordered

    section = update_skill_cmd_mod._build_section("skill body\n", "overlay body\n")
    assert section == "skill body\n\noverlay body\n"

    replaced = update_skill_cmd_mod._replace_section(
        f"prefix\n\n{update_skill_cmd_mod.SKILL_BEGIN}\nold\n{update_skill_cmd_mod.SKILL_END}\n",
        "new section\n",
    )
    assert "prefix" in replaced
    assert "new section" in replaced
    assert "old" not in replaced


def test_resolve_interface_prefers_explicit_then_install_metadata(monkeypatch) -> None:
    assert update_skill_cmd_mod.resolve_interface("CoDeX") == "codex"

    install = update_skill_cmd_mod.SkillInstall(
        rel_path=".claude/skills/desloppify/SKILL.md",
        version=5,
        overlay="windsurf",
        stale=False,
    )
    assert update_skill_cmd_mod.resolve_interface(None, install=install) == "windsurf"

    inferred = update_skill_cmd_mod.SkillInstall(
        rel_path=".cursor/rules/desloppify.md",
        version=5,
        overlay=None,
        stale=False,
    )
    monkeypatch.setattr(update_skill_cmd_mod, "find_installed_skill", lambda: inferred)
    assert update_skill_cmd_mod.resolve_interface() == "cursor"


def test_update_installed_skill_handles_download_and_shared_file_write(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    skill_content = (
        "<!-- desloppify-begin -->\n"
        "<!-- desloppify-skill-version: 5 -->\n"
        "---\n"
        "name: desloppify\n"
        "---\n"
        "body\n"
        "<!-- desloppify-end -->\n"
    )
    overlay_content = "overlay text\n"
    writes: list[tuple[Path, str]] = []
    target = tmp_path / ".agents" / "skills" / "desloppify" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("prefix only", encoding="utf-8")

    monkeypatch.setattr(
        update_skill_cmd_mod,
        "_download",
        lambda filename: skill_content if filename == "SKILL.md" else overlay_content,
    )
    monkeypatch.setattr(update_skill_cmd_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "safe_write_text",
        lambda path, text: writes.append((path, text)) or path.write_text(text, encoding="utf-8"),
    )
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)

    assert update_skill_cmd_mod.update_installed_skill("codex") is True
    assert writes and writes[-1][0] == target
    written = target.read_text(encoding="utf-8")
    assert written.startswith("---\nname: desloppify\n---\n")
    assert "overlay text" in written
    out = capsys.readouterr().out
    assert "Updated .agents/skills/desloppify/SKILL.md" in out


def test_cmd_update_skill_handles_missing_and_unknown_interfaces(monkeypatch, capsys) -> None:
    monkeypatch.setattr(update_skill_cmd_mod, "resolve_interface", lambda _explicit=None: None)
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface=None))
    out = capsys.readouterr().out
    assert "No installed skill document found." in out

    monkeypatch.setattr(
        update_skill_cmd_mod,
        "resolve_interface",
        lambda _explicit=None: "unknown_thing",
    )
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface=None))
    out = capsys.readouterr().out
    assert "Unknown interface 'unknown_thing'." in out


@pytest.mark.parametrize("operation", ["mkdir", "read_text", "write"])
@pytest.mark.parametrize("interface", ["copilot", "windsurf"])
def test_update_skill_reports_filesystem_errors(
    monkeypatch, tmp_path: Path, capsys, operation: str, interface: str,
) -> None:
    target = tmp_path / update_skill_cmd_mod.SKILL_TARGETS[interface][0]
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "# Existing instructions\n"
    target.write_text(original, encoding="utf-8")
    error = PermissionError(errno.EACCES, "Permission denied", str(target))

    def fail(*args, **kwargs):
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(update_skill_cmd_mod, "get_project_root", lambda: tmp_path)
        patch.setattr(
            update_skill_cmd_mod, "_download",
            lambda _: "<!-- desloppify-skill-version: 7 -->\n",
        )
        if operation == "write":
            patch.setattr(update_skill_cmd_mod, "safe_write_text", fail)
        else:
            patch.setattr(Path, operation, fail)

        with pytest.raises(CommandError) as caught:
            update_skill_cmd_mod.update_installed_skill(interface)

    assert caught.value.__cause__ is error
    message = caught.value.message
    assert str(target) in message
    assert "DESLOPPIFY_ROOT" in message
    assert ("desloppify setup --interface copilot" in message) == (interface == "copilot")
    output = capsys.readouterr().out
    assert f"Project skill target: {target}" in output
    assert "Updated" not in output
    assert target.read_text(encoding="utf-8") == original


def test_update_skill_cli_exits_cleanly_on_permission_error(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    import desloppify.app.commands.update_skill as update_skill_mod
    import desloppify.cli as cli_mod

    def fail(_path, _content):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr("sys.argv", ["desloppify", "update-skill", "copilot"])
    monkeypatch.setattr(update_skill_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        update_skill_mod, "_download",
        lambda _: "<!-- desloppify-skill-version: 7 -->\n",
    )
    monkeypatch.setattr(update_skill_mod, "safe_write_text", fail)
    with pytest.raises(SystemExit) as caught:
        cli_mod.main()
    assert caught.value.code != 0
    stderr = capsys.readouterr().err
    assert "Permission denied" in stderr
    assert str(tmp_path / ".github" / "copilot-instructions.md") in stderr
    assert "desloppify setup --interface copilot" in stderr
    assert "Traceback" not in stderr


def test_copilot_project_install_preserves_existing_instructions(
    monkeypatch, tmp_path: Path,
) -> None:
    target = tmp_path / ".github" / "copilot-instructions.md"
    target.parent.mkdir()
    target.write_text("# Project instructions\n", encoding="utf-8")
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    monkeypatch.setattr(
        update_skill_cmd_mod, "_download",
        lambda _: "<!-- desloppify-skill-version: 7 -->\n",
    )

    assert update_skill_cmd_mod.update_installed_skill("copilot")
    content = target.read_text(encoding="utf-8")
    assert content.startswith("# Project instructions\n")
    assert "desloppify-skill-version" in content
