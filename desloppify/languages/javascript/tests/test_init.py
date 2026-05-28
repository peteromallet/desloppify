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

from desloppify.languages import get_lang
from desloppify.languages._framework.generic_parts.parsers import parse_eslint
from desloppify.languages._framework.treesitter import is_available as ts_available

requires_treesitter = pytest.mark.skipif(
    not ts_available(), reason="tree-sitter-language-pack not installed"
)


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


@requires_treesitter
def test_dep_graph_treats_astro_frontmatter_as_importer(cfg, tmp_path, set_project_root):
    """JS modules imported only from .astro frontmatter must not be orphans.

    Regression for a false-positive class on Astro projects: the page/component
    `.astro` files weren't in the JS plugin's enumerated extensions, so any
    .js module they imported showed `importer_count == 0` and tripped the
    orphaned-file detector. With ``frameworks=True`` on the plugin and the
    framework-extensions wiring in the shared graph builder, the importer
    edge is now recorded.
    """
    del set_project_root  # PROJECT_ROOT scoped to tmp_path

    src = tmp_path / "src"
    src.mkdir()
    config = src / "config.js"
    config.write_text("export const LIST_UUID = 'xyz';\n", encoding="utf-8")

    pages = src / "pages"
    pages.mkdir()
    (pages / "index.astro").write_text(
        "---\nimport { LIST_UUID } from '../config.js';\n---\n<html />\n",
        encoding="utf-8",
    )

    graph = cfg.build_dep_graph(tmp_path)
    config_key = str(config.resolve())
    astro_key = str((pages / "index.astro").resolve())

    assert config_key in graph, (
        f"config.js missing from graph; keys: {sorted(graph)[:5]}…"
    )
    assert graph[config_key]["importer_count"] >= 1
    assert astro_key in graph[config_key]["importers"]
    # The .astro file itself is not a graph node — it must not appear as
    # an orphan in JS plugin reports.
    assert astro_key not in graph


@requires_treesitter
def test_dep_graph_treats_mjs_config_as_importer(cfg, tmp_path, set_project_root):
    """.mjs config files (e.g. astro.config.mjs, vite.config.mjs) must register
    as importers of the .js modules they pull in.

    .mjs IS in the JS plugin's extension list, so this should "just work" —
    but covering it explicitly guards against regressions in how the
    tree-sitter pass handles ESM-only files.
    """
    del set_project_root

    src = tmp_path / "src"
    src.mkdir()
    helper = src / "helper.js"
    helper.write_text("export const ok = true;\n", encoding="utf-8")
    (tmp_path / "tool.config.mjs").write_text(
        "import { ok } from './src/helper.js';\nexport default { ok };\n",
        encoding="utf-8",
    )

    graph = cfg.build_dep_graph(tmp_path)
    helper_key = str(helper.resolve())
    mjs_key = str((tmp_path / "tool.config.mjs").resolve())

    assert helper_key in graph
    assert mjs_key in graph[helper_key]["importers"]


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
