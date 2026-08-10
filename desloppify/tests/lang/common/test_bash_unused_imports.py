"""Regression tests for Bash source import detection."""

from __future__ import annotations

import textwrap


def _detect(tmp_path, contents: str, libraries: dict[str, str] | None = None):
    from desloppify.languages._framework.treesitter.analysis.unused_imports import (
        detect_unused_imports,
    )
    from desloppify.languages._framework.treesitter.specs.scripting import BASH_SPEC

    for lib_name, lib_contents in (libraries or {}).items():
        (tmp_path / lib_name).write_text(textwrap.dedent(lib_contents).lstrip())
    script = tmp_path / "script.sh"
    script.write_text(textwrap.dedent(contents).lstrip())
    return detect_unused_imports([str(script)], BASH_SPEC)


_LIB_ACCEPTANCE = """
    #!/usr/bin/env bash
    API=${API:-http://localhost:8080}
    export TOKEN="abc"
    declare -r LIMIT=5
    function legacy_helper {
      local inner=1
      echo "$inner"
    }
    require_server() {
      curl -fsS "$API/health" >/dev/null
    }
"""


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


def test_bash_source_calling_library_function_is_not_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        set -euo pipefail
        cd "$(dirname "$0")"
        source ./lib-acceptance.sh
        require_server
        """,
        libraries={"lib-acceptance.sh": _LIB_ACCEPTANCE},
    )

    assert findings == []


def test_bash_source_using_function_keyword_definition_is_not_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        source ./lib-acceptance.sh
        legacy_helper
        """,
        libraries={"lib-acceptance.sh": _LIB_ACCEPTANCE},
    )

    assert findings == []


def test_bash_source_using_library_variable_is_not_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        source ./lib-acceptance.sh
        curl -fsS "$API/workflows" >/dev/null
        """,
        libraries={"lib-acceptance.sh": _LIB_ACCEPTANCE},
    )

    assert findings == []


def test_bash_source_using_exported_variable_is_not_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        source ./lib-acceptance.sh
        echo "token: ${TOKEN}"
        """,
        libraries={"lib-acceptance.sh": _LIB_ACCEPTANCE},
    )

    assert findings == []


def test_bash_source_with_no_library_symbol_used_is_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        source ./lib-acceptance.sh
        echo body
        """,
        libraries={"lib-acceptance.sh": _LIB_ACCEPTANCE},
    )

    assert [entry["name"] for entry in findings] == ["lib-acceptance"]


def test_bash_source_local_variable_in_library_function_is_not_usage(tmp_path):
    findings = _detect(
        tmp_path,
        """
        #!/bin/bash
        source ./lib-acceptance.sh
        inner=2
        echo "$inner"
        """,
        libraries={"lib-acceptance.sh": _LIB_ACCEPTANCE},
    )

    assert [entry["name"] for entry in findings] == ["lib-acceptance"]
