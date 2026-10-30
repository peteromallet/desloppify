"""Kotlin-specific behaviour of the tree-sitter unused import detector."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from desloppify.languages._framework.treesitter.analysis.unused_imports import (  # noqa: E402
    detect_unused_imports,
)
from desloppify.languages._framework.treesitter.specs.compiled import KOTLIN_SPEC  # noqa: E402


def _unused(tmp_path: Path, source: str) -> list[str]:
    path = tmp_path / "Sample.kt"
    path.write_text(source, encoding="utf-8")
    return sorted(entry["name"] for entry in detect_unused_imports([str(path)], KOTLIN_SPEC))


def test_operator_convention_imports_count_as_used(tmp_path: Path) -> None:
    source = """package p

import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import com.acme.contains
import com.acme.component1
import com.acme.component2
import com.acme.plus

fun f(items: Set<Int>) {
    var count by mutableStateOf(0)
    val (a, b) = Pair(1, 2)
    if (count in items) count = a + b
}
"""
    assert _unused(tmp_path, source) == []


def test_operator_imports_without_matching_syntax_are_unused(tmp_path: Path) -> None:
    source = """package p

import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue

fun f() {
    val count = 1
}
"""
    assert _unused(tmp_path, source) == ["getValue", "setValue"]


def test_set_value_needs_a_var_delegate(tmp_path: Path) -> None:
    source = """package p

import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue

fun f(state: State<Int>) {
    val count by state
}
"""
    assert _unused(tmp_path, source) == ["setValue"]


def test_backticked_alias_and_wildcard_imports(tmp_path: Path) -> None:
    source = """package p

import org.mockito.Mockito.`when`
import com.acme.LongName as Short
import com.acme.Unused as AlsoUnused
import com.acme.model.*

fun f() {
    `when`(Short.make()).thenReturn(null)
}
"""
    assert _unused(tmp_path, source) == ["AlsoUnused"]


def test_plain_unused_import_is_still_reported(tmp_path: Path) -> None:
    source = """package p

import com.acme.BuriedGem
import com.acme.Used

fun f(u: Used) = u
"""
    assert _unused(tmp_path, source) == ["BuriedGem"]
