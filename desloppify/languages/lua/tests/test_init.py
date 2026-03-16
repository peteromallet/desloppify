"""Sanity tests for the Lua language plugin.

These tests verify that the generic_lang() registration in
desloppify/languages/lua/__init__.py produces a valid LangConfig
and that its luacheck integration is wired correctly.

None of these tests require luacheck to be installed; they exercise
the plugin metadata and the pure-Python parser in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.languages import get_lang
from desloppify.languages._framework.generic_parts.parsers import parse_gnu


@pytest.fixture(scope="module")
def cfg():
    """Return the registered LangConfig for Lua.

    Scoped to the module so the plugin is loaded once across all tests
    in this file; generic_lang() is idempotent but the round-trip through
    the registry adds a small cost on repeated calls.
    """
    return get_lang("lua")


def test_config_name(cfg):
    """Plugin must register under the canonical 'lua' key."""
    assert cfg.name == "lua"


@pytest.mark.parametrize("ext", [".lua"])
def test_config_extensions(cfg, ext):
    """All expected Lua file extensions must be present."""
    assert ext in cfg.extensions


def test_detect_commands_non_empty(cfg):
    """At least one detect command must be registered (luacheck_warning)."""
    assert cfg.detect_commands, "expected at least one detect command"


def test_has_luacheck_phase(cfg):
    """A phase labelled 'luacheck' must be present in the plugin's phase list."""
    labels = {p.label for p in cfg.phases}
    assert "luacheck" in labels, f"luacheck phase missing; found: {labels}"


def test_command_has_no_placeholder(cfg):
    """The luacheck command must not contain a {file_path} template placeholder.

    run_tool_result() passes the command to resolve_command_argv() which does
    NOT perform string substitution — a leftover placeholder would be passed
    verbatim to the shell and produce zero results silently.

    Closure inspection is used so the test does not depend on string-matching
    the source code; it reads the *actual* value captured at registration time.
    """
    detect_fn = cfg.detect_commands["luacheck_warning"]
    freevars = detect_fn.__code__.co_freevars
    cmd: str = detect_fn.__closure__[freevars.index("cmd")].cell_contents
    assert "{file_path}" not in cmd, (
        f"command contains {{file_path}} placeholder which will not be substituted: {cmd!r}"
    )


def test_parsing_gnu_format():
    """Verify that luacheck --formatter=plain output is parsed correctly.

    luacheck plain format emits ``./path/to/file.lua:line:col: message``.
    The ``./`` prefix and column number must both be handled without error
    by parse_gnu(), which is the parser registered for fmt='gnu'.

    Two representative lines are used:
    - a warning (W code) with line+col
    - an error (E code) with line+col

    The summary line ("Total: N warnings / N errors in N files") must be
    silently ignored since it does not match the file:line pattern.
    """
    output = (
        "./src/main.lua:10:5: (W111) setting non-standard global variable 'x'\n"
        "./lib/utils.lua:20:1: (E011) expected '=' near 'end'\n"
        "Total: 1 warning / 1 error in 2 files\n"  # must be ignored
    )
    entries = parse_gnu(output, Path("."))

    assert len(entries) == 2, f"expected 2 parsed entries, got {len(entries)}: {entries}"

    assert entries[0]["file"] == "./src/main.lua"
    assert entries[0]["line"] == 10
    assert "(W111)" in entries[0]["message"]

    assert entries[1]["file"] == "./lib/utils.lua"
    assert entries[1]["line"] == 20
    assert "(E011)" in entries[1]["message"]
