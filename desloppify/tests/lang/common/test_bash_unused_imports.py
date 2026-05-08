"""Regression tests for the BASH_SPEC import_query predicate.

The bash import query previously matched every (command, argument) pair as
an "import", causing every shell flag to be reported as an unused import:
    set -euo pipefail        →  Unused import: pipefail
    curl -fsS https://...    →  Unused import: -fsS
    find . -name '*.tmp'     →  Unused import: -name

The fix adds a `(#match? @_cmd "^(source|\\.)$")` predicate INSIDE the
(command ...) pattern so only `source <path>` and `. <path>` directives
are captured. These tests pin both halves of the contract: real source
imports must still be detected, and shell flags must not.
"""

from __future__ import annotations

import textwrap


def _detect(tmp_path, contents: str):
    from desloppify.languages._framework.treesitter.analysis.unused_imports import (
        detect_unused_imports,
    )
    from desloppify.languages._framework.treesitter.specs.scripting import BASH_SPEC

    script = tmp_path / "script.sh"
    script.write_text(textwrap.dedent(contents).lstrip())
    return detect_unused_imports([str(script)], BASH_SPEC)


def test_bash_shell_flags_are_not_imports(tmp_path):
    """`set -euo pipefail`, `curl -fsS ...`, etc. must produce zero findings.

    Without the #match? predicate, every command argument was flagged.
    """
    findings = _detect(tmp_path, """
        #!/bin/bash
        set -euo pipefail
        curl -fsS https://example.com >/dev/null
        find . -name '*.tmp' -delete
        cut -d: -f2 /etc/passwd
    """)
    assert findings == [], (
        f"shell flags should not be unused imports, got: {findings}"
    )


def test_bash_unused_source_directive_is_flagged(tmp_path):
    """`source ./helpers.sh` whose basename does not appear elsewhere is unused."""
    findings = _detect(tmp_path, """
        #!/bin/bash
        source ./helpers.sh
        echo body
    """)
    names = [f["name"] for f in findings]
    assert "helpers" in names, f"expected unused 'helpers', got {findings}"


def test_bash_unused_dot_source_directive_is_flagged(tmp_path):
    """The POSIX `.` form is equivalent to `source` and must be filtered too."""
    findings = _detect(tmp_path, """
        #!/bin/bash
        . ./extras.sh
        echo body
    """)
    names = [f["name"] for f in findings]
    assert "extras" in names, f"expected unused 'extras', got {findings}"


def test_bash_used_source_directive_is_not_flagged(tmp_path):
    """If the sourced file's basename is referenced later, do not flag it."""
    findings = _detect(tmp_path, """
        #!/bin/bash
        source ./helpers.sh
        helpers
    """)
    assert findings == [], (
        f"used source should not be flagged, got: {findings}"
    )
