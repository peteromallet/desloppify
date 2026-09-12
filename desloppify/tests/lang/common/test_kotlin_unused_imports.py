"""Regression tests for Kotlin unused import detection.

Kotlin resolves some imports by convention rather than by name, so the imported
symbol never appears in the file body. Flagging those as unused is actively
harmful: removing them breaks compilation.
"""

from __future__ import annotations

import textwrap


def _detect(tmp_path, contents: str, name: str = "Screen.kt"):
    from desloppify.languages._framework.treesitter.analysis.unused_imports import (
        detect_unused_imports,
    )
    from desloppify.languages._framework.treesitter.specs.compiled import KOTLIN_SPEC

    source = tmp_path / name
    source.write_text(textwrap.dedent(contents).lstrip())
    return detect_unused_imports([str(source)], KOTLIN_SPEC)


def _names(findings) -> set[str]:
    return {f["name"] for f in findings}


def test_delegation_imports_are_not_flagged_when_by_is_used(tmp_path):
    """`var x by remember { ... }` needs getValue/setValue even though it never names them."""
    findings = _detect(
        tmp_path,
        """
        package com.example

        import androidx.compose.runtime.Composable
        import androidx.compose.runtime.getValue
        import androidx.compose.runtime.mutableStateOf
        import androidx.compose.runtime.remember
        import androidx.compose.runtime.setValue

        @Composable
        fun Screen() {
            var expanded by remember { mutableStateOf(false) }
            if (expanded) {
                expanded = false
            }
        }
        """,
    )

    assert _names(findings) == set()


def test_delegation_imports_are_flagged_without_by(tmp_path):
    """No delegation in the file means the operator imports really are dead."""
    findings = _detect(
        tmp_path,
        """
        package com.example

        import androidx.compose.runtime.Composable
        import androidx.compose.runtime.getValue
        import androidx.compose.runtime.setValue

        @Composable
        fun Screen() {
            Text("static")
        }
        """,
    )

    assert _names(findings) == {"getValue", "setValue"}


def test_identifier_ending_in_by_does_not_mask_dead_delegation_imports(tmp_path):
    """`nearby` / `standby.set(...)` must not be mistaken for the `by` keyword."""
    findings = _detect(
        tmp_path,
        """
        package com.example

        import androidx.compose.runtime.getValue

        fun render(nearby: String) {
            println(nearby)
        }
        """,
    )

    assert _names(findings) == {"getValue"}


def test_component_imports_are_not_flagged_with_destructuring(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package com.example

        import com.example.geo.component1
        import com.example.geo.component2

        fun render(point: GeoPoint) {
            val (lat, lon) = point
            println("$lat $lon")
        }
        """,
    )

    assert _names(findings) == set()


def test_genuinely_unused_import_is_still_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package com.example

        import androidx.compose.foundation.background
        import androidx.compose.runtime.Composable

        @Composable
        fun Screen() {
            Text("hello")
        }
        """,
    )

    assert _names(findings) == {"background"}
