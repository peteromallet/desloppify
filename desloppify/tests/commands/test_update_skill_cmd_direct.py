"""Direct coverage tests for the update-skill command module."""

from __future__ import annotations

import argparse
from pathlib import Path

import desloppify.app.commands.update_skill.cmd as update_skill_cmd_mod


def _install(
    rel_path: str,
    *,
    interface: str | None,
    overlay: str | None,
    scope: str = "project",
    source_kind: str = "legacy_project",
    canonical: bool = False,
    version: int = 5,
    stale: bool = False,
) -> update_skill_cmd_mod.SkillInstall:
    return update_skill_cmd_mod.SkillInstall(
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


def test_update_skill_helper_functions_cover_frontmatter_resolution_and_replace() -> None:
    assert update_skill_cmd_mod._RAW_BASE == "https://raw.githubusercontent.com/cpjet64/desloppify/main/docs"

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

    install = _install(
        ".claude/skills/desloppify/SKILL.md",
        interface="claude",
        overlay="windsurf",
    )
    assert update_skill_cmd_mod.resolve_interface(None, install=install) == "windsurf"

    inferred = _install(
        ".cursor/rules/desloppify.md",
        interface="cursor",
        overlay=None,
    )
    monkeypatch.setattr(update_skill_cmd_mod, "find_installed_skills", lambda: [inferred])
    assert update_skill_cmd_mod.resolve_interface() == "cursor"


def test_update_installed_skill_handles_download_and_shared_file_write(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    skill_content = (
        "<!-- desloppify-begin -->\n"
        f"<!-- desloppify-skill-version: {update_skill_cmd_mod.SKILL_VERSION} -->\n"
        "---\n"
        "name: desloppify\n"
        "---\n"
        "body\n"
        "<!-- desloppify-end -->\n"
    )
    overlay_content = "overlay text\n"
    writes: list[tuple[Path, str]] = []
    target = tmp_path / ".codex" / "skills" / "desloppify" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("prefix only", encoding="utf-8")

    monkeypatch.setattr(
        update_skill_cmd_mod,
        "_download",
        lambda filename: skill_content if filename == "SKILL.md" else overlay_content,
    )
    monkeypatch.setattr(update_skill_cmd_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(update_skill_cmd_mod, "_get_home_path", lambda: tmp_path)
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
    assert "Updated .codex/skills/desloppify/SKILL.md" in out
    assert (
        f"(v{update_skill_cmd_mod.SKILL_VERSION}, tool expects v{update_skill_cmd_mod.SKILL_VERSION})"
        in out
    )


def test_cmd_update_skill_handles_missing_and_ambiguous_installs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "find_installed_skills",
        lambda: [],
    )
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "resolve_interface",
        lambda _explicit=None, installs=None: None,
    )
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface=None, scope="auto"))
    out = capsys.readouterr().out
    assert "No installed skill document found." in out

    monkeypatch.setattr(
        update_skill_cmd_mod,
        "find_installed_skills",
        lambda: [
            _install("~/.codex/skills/desloppify/SKILL.md", interface="codex", overlay="codex", scope="user", source_kind="canonical_user", canonical=True),
            _install("~/.claude/skills/desloppify/SKILL.md", interface="claude", overlay="claude", scope="user", source_kind="canonical_user", canonical=True),
        ],
    )
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "resolve_interface",
        lambda _explicit=None, installs=None: None,
    )
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface=None, scope="auto"))
    out = capsys.readouterr().out
    assert "Multiple installed skill documents were detected." in out


def test_cmd_update_skill_handles_unknown_interface(monkeypatch, capsys) -> None:
    monkeypatch.setattr(update_skill_cmd_mod, "find_installed_skills", lambda: [])
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface="unknown_thing", scope="auto"))
    out = capsys.readouterr().out
    assert "Unknown interface 'unknown_thing'." in out
