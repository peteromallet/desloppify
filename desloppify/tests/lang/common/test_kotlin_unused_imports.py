"""Kotlin operators can reference imported extensions without naming them."""

from __future__ import annotations

import textwrap

import pytest

from desloppify.languages._framework.treesitter.analysis.unused_imports import (
    detect_unused_imports,
)
from desloppify.languages._framework.treesitter.specs.compiled import KOTLIN_SPEC


def _detect(tmp_path, contents: str, suffix: str = ".kt"):
    source = tmp_path / f"example{suffix}"
    source.write_text(textwrap.dedent(contents).lstrip())
    return detect_unused_imports([str(source)], KOTLIN_SPEC)


@pytest.mark.parametrize("suffix", [".kt", ".kts"])
@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("getValue", "val state by source"),
        ("getValue", "var state by source"),
        ("setValue", "var state by source"),
        ("provideDelegate", "val state by source"),
        ("get", "val selected = devices[name]"),
        ("get", "fun configure() { devices[name] += value }"),
        ("set", "fun configure() { devices[name] = value }"),
        ("set", "fun configure() { devices[name] += value }"),
        ("set", "fun configure() { devices[name]++ }"),
        ("invoke", "fun configure() { devices { create(name) } }"),
        ("invoke", "fun configure() { callback() }"),
        ("assign", "fun configure() { options.target = value }"),
    ],
)
def test_operator_syntax_keeps_potentially_used_imports(tmp_path, suffix, name, body):
    assert _detect(tmp_path, f"import extensions.{name}\n{body}\n", suffix) == []


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("getValue", "val state = source"),
        ("getValue", "class Proxy : Contract by source"),
        ("setValue", "val state by source"),
        ("provideDelegate", "val state = source"),
        ("get", "val selected = devices"),
        ("get", "fun configure() { devices[name] = value }"),
        ("set", "val selected = devices"),
        ("set", "val selected = devices[name]"),
        ("invoke", "val callback = source"),
        ("assign", "val target = value"),
        ("getValue", 'val example = "val state by source"'),
        ("getValue", "// var state by source\nval state = source"),
        ("invoke", 'val example = "callback()"'),
        ("assign", 'val example = "target = value"'),
    ],
)
def test_operator_import_without_matching_syntax_is_unused(tmp_path, name, body):
    findings = _detect(tmp_path, f"import extensions.{name}\n{body}\n")
    assert [entry["name"] for entry in findings] == [name]


def test_ordinary_unused_imports_still_reported_with_delegates(tmp_path):
    findings = _detect(tmp_path, """
        import extensions.getValue
        import extensions.setValue
        import ui.Text
        import ui.WindowWidthSizeClass
        var state by source
    """)
    assert [entry["name"] for entry in findings] == ["Text", "WindowWidthSizeClass"]


def test_operator_import_renamed_to_nonoperator_is_unused(tmp_path):
    findings = _detect(tmp_path, """
        import extensions.getValue as read
        val state by source
    """)
    assert [entry["name"] for entry in findings] == ["read"]


def test_import_renamed_to_operator_can_be_implicitly_used(tmp_path):
    assert _detect(tmp_path, """
        import extensions.invoke as getValue
        val state by source
    """) == []


def test_explicit_operator_call_still_counts(tmp_path):
    assert _detect(tmp_path, """
        import extensions.getValue
        val state = source.getValue(owner, property)
    """) == []
