"""Regression tests for Bash source import detection."""

from __future__ import annotations

import textwrap

import pytest

from desloppify.languages._framework.treesitter import is_available

pytestmark = pytest.mark.skipif(
    not is_available(), reason="tree-sitter-language-pack not installed"
)


def _detect(tmp_path, contents: str):
    from desloppify.languages._framework.treesitter.analysis.unused_imports import (
        detect_unused_imports,
    )
    from desloppify.languages._framework.treesitter.specs.scripting import BASH_SPEC

    script = tmp_path / "script.sh"
    script.write_text(textwrap.dedent(contents).lstrip())
    return detect_unused_imports([str(script)], BASH_SPEC)


def test_bash_shell_flags_are_not_imports(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        set -euo pipefail
        curl -fsS https://example.com >/dev/null
        find . -name '*.tmp' -delete
        cut -d: -f2 /etc/passwd
        """,
    )

    assert findings == []


def test_bash_unused_source_directive_is_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        source ./helpers.sh
        echo body
        """,
    )

    assert [entry["name"] for entry in findings] == ["helpers"]


def test_bash_unused_dot_source_directive_is_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        . ./extras.sh
        echo body
        """,
    )

    assert [entry["name"] for entry in findings] == ["extras"]


def test_bash_source_extra_arguments_are_not_imports(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        source ./helpers.sh foo bar
        . ./extras.sh arg
        echo body
        """,
    )

    names = {entry["name"] for entry in findings}
    assert names == {"extras", "helpers"}
    assert "foo" not in names
    assert "bar" not in names
    assert "arg" not in names


def test_bash_used_source_directive_is_not_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        source ./helpers.sh
        helpers
        """,
    )

    assert findings == []
