"""Sanity tests for the JavaScript language plugin.

These tests verify that the generic_lang() registration in
desloppify/languages/javascript/__init__.py produces a valid LangConfig
and that its ESLint integration is wired correctly.

None of these tests require ESLint or Node.js to be installed; they exercise
the plugin metadata and the pure-Python parser in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.languages import get_lang
from desloppify.languages._framework.generic_parts.parsers import parse_eslint


@pytest.fixture(scope="module")
def cfg():
    """Return the registered LangConfig for JavaScript.

    Scoped to the module so the plugin is loaded once across all tests
    in this file; generic_lang() is idempotent but the round-trip through
    the registry adds a small cost on repeated calls.
    """
    return get_lang("javascript")


def test_config_name(cfg):
    """Plugin must register under the canonical 'javascript' key."""
    assert cfg.name == "javascript"


@pytest.mark.parametrize("ext", [".js", ".jsx", ".mjs", ".cjs"])
def test_config_extensions(cfg, ext):
    """All expected JavaScript file extensions must be present."""
    assert ext in cfg.extensions


def test_detect_markers(cfg):
    """plugin.json must be listed as a detect marker."""
    assert "package.json" in cfg.detect_markers


def test_detect_commands_non_empty(cfg):
    """At least one detect command must be registered (eslint_warning)."""
    assert cfg.detect_commands, "expected at least one detect command"


def test_has_eslint_phase(cfg):
    """A phase labelled 'ESLint' must be present in the plugin's phase list."""
    labels = {p.label for p in cfg.phases}
    assert "ESLint" in labels, f"ESLint phase missing; found: {labels}"


def test_exclusions(cfg):
    """node_modules and dist must be in the exclusions list."""
    assert "node_modules" in cfg.exclusions
    assert "dist" in cfg.exclusions


def test_command_has_no_placeholder(cfg):
    """The eslint command must not contain a {file_path} template placeholder.

    run_tool_result() passes the command to resolve_command_argv() which does
    NOT perform string substitution — a leftover placeholder would be passed
    verbatim to the shell and produce zero results silently.

    Closure inspection is used so the test does not depend on string-matching
    the source code; it reads the *actual* value captured at registration time.
    """
    detect_fn = cfg.detect_commands["eslint_warning"]
    freevars = detect_fn.__code__.co_freevars
    cmd: str = detect_fn.__closure__[freevars.index("cmd")].cell_contents
    assert "{file_path}" not in cmd, (
        f"command contains {{file_path}} placeholder which will not be substituted: {cmd!r}"
    )


def test_fix_cmd_registered(cfg):
    """JavaScript supports autofix — at least one fixer must be registered."""
    assert cfg.fixers, "expected at least one fixer (fix_cmd) to be registered for JavaScript"


def test_zone_rules_classify_test_markers(cfg):
    """JS plugin should classify common test markers into the test zone."""
    files = [
        "src/foo.test.js",
        "src/bar.spec.jsx",
        "src/__tests__/baz.js",
        "src/app.js",
    ]
    zone_map = FileZoneMap(files, cfg.zone_rules)
    assert zone_map.get("src/foo.test.js") == Zone.TEST
    assert zone_map.get("src/bar.spec.jsx") == Zone.TEST
    assert zone_map.get("src/__tests__/baz.js") == Zone.TEST
    assert zone_map.get("src/app.js") == Zone.PRODUCTION


def test_parsing_eslint_format():
    """Verify that ESLint JSON output is parsed correctly.

    ESLint JSON format emits a list of file objects, each with a ``filePath``
    and a ``messages`` list containing ``line`` and ``message`` fields.

    Two representative entries are used — one warning and one unused-variable
    notice — and the summary-less JSON must be handled without error.
    """
    output = (
        '[{"filePath": "/project/src/app.js", '
        '"messages": [{"line": 5, "message": "Unexpected var."}]}, '
        '{"filePath": "/project/lib/utils.js", '
        '"messages": [{"line": 12, "message": "\'x\' is defined but never used."}]}]'
    )
    entries = parse_eslint(output, Path("."))

    assert len(entries) == 2, f"expected 2 parsed entries, got {len(entries)}: {entries}"

    assert entries[0]["file"] == "/project/src/app.js"
    assert entries[0]["line"] == 5
    assert "Unexpected var" in entries[0]["message"]

    assert entries[1]["file"] == "/project/lib/utils.js"
    assert entries[1]["line"] == 12
    assert "defined but never used" in entries[1]["message"]
