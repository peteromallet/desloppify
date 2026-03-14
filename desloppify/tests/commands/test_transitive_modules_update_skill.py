"""Update-skill transitive module tests."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

from desloppify.app.commands.update_skill import (
    _build_section,
    _replace_section,
    cmd_update_skill,
    resolve_interface,
    update_installed_skill,
)


def _install(
    rel_path: str,
    *,
    interface: str | None,
    overlay: str | None,
    scope: str = "project",
    source_kind: str = "legacy_project",
    canonical: bool = False,
    version: int = 1,
    stale: bool = False,
):
    from desloppify.app.skill_docs import SkillInstall

    return SkillInstall(
        rel_path=rel_path,
        absolute_path=Path("C:/fake") / rel_path.replace("~/", ""),
        interface=interface,
        scope=scope,
        source_kind=source_kind,
        canonical=canonical,
        version=version,
        overlay=overlay,
        stale=stale,
    )


class TestBuildSection:
    def test_skill_only(self):
        result = _build_section("skill content", None)
        assert result == "skill content\n"

    def test_skill_with_overlay(self):
        result = _build_section("skill content", "overlay content")
        assert result == "skill content\n\noverlay content\n"

    def test_strips_trailing_whitespace(self):
        result = _build_section("skill  \n\n", "overlay  \n\n")
        assert result == "skill\n\noverlay\n"


class TestReplaceSection:
    def test_appends_when_no_markers(self):
        result = _replace_section("existing content", "new section")
        assert "existing content" in result
        assert "new section" in result

    def test_replaces_between_markers(self):
        from desloppify.app.skill_docs import SKILL_BEGIN, SKILL_END
        content = f"before\n{SKILL_BEGIN}\nold content\n{SKILL_END}\nafter"
        result = _replace_section(content, "new section")
        assert "old content" not in result
        assert "new section" in result
        assert "before" in result
        assert "after" in result

    def test_handles_empty_before(self):
        from desloppify.app.skill_docs import SKILL_BEGIN, SKILL_END
        content = f"{SKILL_BEGIN}\nold\n{SKILL_END}\nafter"
        result = _replace_section(content, "new")
        assert "new" in result
        assert "after" in result

    def test_handles_empty_after(self):
        from desloppify.app.skill_docs import SKILL_BEGIN, SKILL_END
        content = f"before\n{SKILL_BEGIN}\nold\n{SKILL_END}"
        result = _replace_section(content, "new")
        assert "new" in result
        assert "before" in result


class TestResolveInterface:
    def test_explicit_value(self):
        assert resolve_interface("Claude") == "claude"
        assert resolve_interface("CURSOR") == "cursor"

    def test_none_with_no_install(self):
        with patch(
            "desloppify.app.commands.update_skill.find_installed_skills",
            return_value=[],
        ):
            assert resolve_interface(None) is None

    def test_from_install_overlay(self):
        install = _install(".claude/skills/desloppify/SKILL.md", interface="claude", overlay="claude")
        result = resolve_interface(None, install=install)
        assert result == "claude"

    def test_from_install_path_match(self):
        install = _install(".claude/skills/desloppify/SKILL.md", interface="claude", overlay=None)
        result = resolve_interface(None, install=install)
        assert result == "claude"

    def test_from_install_path_match_opencode(self):
        install = _install(".opencode/skills/desloppify/SKILL.md", interface="opencode", overlay=None)
        result = resolve_interface(None, install=install)
        assert result == "opencode"

    def test_from_install_no_match(self):
        install = _install("unknown/path.md", interface=None, overlay=None)
        result = resolve_interface(None, install=install)
        assert result is None


class TestCmdUpdateSkill:
    @patch("desloppify.app.commands.update_skill.update_installed_skill")
    @patch("desloppify.app.commands.update_skill.resolve_interface", return_value="claude")
    def test_valid_interface(self, _mock_resolve, mock_update):
        args = argparse.Namespace(interface="claude", scope="auto")
        cmd_update_skill(args)
        mock_update.assert_called_once_with("claude", "auto")

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill.resolve_interface", return_value=None)
    @patch("desloppify.app.commands.update_skill.find_installed_skills", return_value=[])
    def test_no_interface_found(self, _mock_installs, _mock_resolve, _mock_colorize, capsys):
        args = argparse.Namespace(interface=None, scope="auto")
        cmd_update_skill(args)
        out = capsys.readouterr().out
        assert "No installed skill document found" in out

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill.find_installed_skills", return_value=[])
    def test_unknown_interface(self, _mock_installs, _mock_colorize, capsys):
        args = argparse.Namespace(interface="unknown_thing", scope="auto")
        cmd_update_skill(args)
        out = capsys.readouterr().out
        assert "Unknown interface" in out


class TestUpdateInstalledSkill:
    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill._download")
    def test_download_failure(self, mock_download, _mock_colorize, capsys):
        import urllib.error
        mock_download.side_effect = urllib.error.URLError("no network")
        result = update_installed_skill("claude")
        assert result is False
        out = capsys.readouterr().out
        assert "Download failed" in out

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill._download")
    def test_bad_content(self, mock_download, _mock_colorize, capsys):
        mock_download.return_value = "random html garbage"
        result = update_installed_skill("claude")
        assert result is False
        out = capsys.readouterr().out
        assert "doesn't look like a skill document" in out

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill._download")
    def test_successful_dedicated_install(self, mock_download, _mock_colorize, capsys, tmp_path):
        skill_content = "# Skill\n<!-- desloppify-skill-version: 1 -->\nContent"
        mock_download.side_effect = lambda f: {
            "SKILL.md": skill_content,
            "CLAUDE.md": "overlay",
        }[f]

        with patch(
            "desloppify.app.commands.update_skill.get_project_root",
            return_value=tmp_path,
        ), patch(
            "desloppify.app.commands.update_skill._get_home_path",
            return_value=tmp_path,
        ):
            result = update_installed_skill("claude")

        assert result is True
        written = (tmp_path / ".claude" / "skills" / "desloppify" / "SKILL.md").read_text()
        assert "desloppify-skill-version" in written
        out = capsys.readouterr().out
        assert "Updated" in out

    @patch("desloppify.app.commands.update_skill.colorize", side_effect=lambda t, _c: t)
    @patch("desloppify.app.commands.update_skill._download")
    def test_successful_shared_install(self, mock_download, _mock_colorize, capsys, tmp_path):
        """Non-dedicated install (e.g. windsurf) replaces section in existing file."""
        skill_content = "# Skill\n<!-- desloppify-skill-version: 1 -->\nContent"
        mock_download.side_effect = lambda f: {
            "SKILL.md": skill_content,
            "WINDSURF.md": "windsurf overlay",
        }[f]

        # Pre-create the target file with some existing content
        agents_file = tmp_path / "AGENTS.md"
        agents_file.write_text("# My Project\nExisting content.\n")

        with patch(
            "desloppify.app.commands.update_skill.get_project_root",
            return_value=tmp_path,
        ):
            result = update_installed_skill("windsurf")

        assert result is True
        written = agents_file.read_text()
        assert "Existing content" in written
        assert "desloppify-skill-version" in written
