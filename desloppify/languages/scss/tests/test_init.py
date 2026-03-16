"""Sanity tests for SCSS language plugin."""

from __future__ import annotations

from desloppify.languages import get_lang


def test_config_name():
    cfg = get_lang("scss")
    assert cfg.name == "scss"


def test_config_extensions():
    cfg = get_lang("scss")
    assert ".scss" in cfg.extensions
    assert ".sass" in cfg.extensions


def test_detect_markers():
    cfg = get_lang("scss")
    assert "_scss" in cfg.detect_markers
    assert ".stylelintrc" in cfg.detect_markers


def test_detect_commands_non_empty():
    cfg = get_lang("scss")
    assert cfg.detect_commands


def test_has_stylelint_phase():
    cfg = get_lang("scss")
    labels = {p.label for p in cfg.phases}
    assert "stylelint" in labels


def test_exclusions():
    cfg = get_lang("scss")
    assert "node_modules" in cfg.exclusions
    assert "vendor" in cfg.exclusions


def test_command_has_no_placeholder():
    """Guard against {file_path} — the runner does not substitute placeholders."""
    cfg = get_lang("scss")
    detect_fn = cfg.detect_commands["stylelint_issue"]
    freevars = detect_fn.__code__.co_freevars
    cmd = detect_fn.__closure__[freevars.index("cmd")].cell_contents
    assert "{file_path}" not in cmd


def test_parsing():
    """Verify that stylelint unix output is correctly parsed by the gnu parser."""
    from pathlib import Path
    from desloppify.languages._framework.generic_parts.parsers import parse_gnu

    output = "path/to/file.scss:10:5: Unexpected empty block (block-no-empty)\n"
    output += "another/file.sass:20: Unexpected trailing whitespace (no-eol-whitespace)\n"

    entries = parse_gnu(output, Path("."))

    assert len(entries) == 2
    assert entries[0]["file"] == "path/to/file.scss"
    assert entries[0]["line"] == 10
    assert entries[0]["message"] == "Unexpected empty block (block-no-empty)"

    assert entries[1]["file"] == "another/file.sass"
    assert entries[1]["line"] == 20
    assert entries[1]["message"] == "Unexpected trailing whitespace (no-eol-whitespace)"
