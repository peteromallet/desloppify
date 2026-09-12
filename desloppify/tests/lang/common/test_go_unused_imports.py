"""Regression tests for Go source unused-import detection.

Go's in-code package identifier is defined by the dependency's ``package``
clause, not the last import-path segment. These tests cover the false
positives that heuristic mismatch previously produced -- blank imports, dot
imports, versioned module paths, and hyphenated/otherwise-invalid path
segments -- plus confirmation that genuinely unused and aliased imports are
still detected correctly.
"""

from __future__ import annotations

import textwrap


def _detect(tmp_path, contents: str):
    from desloppify.languages._framework.treesitter.analysis.unused_imports import (
        detect_unused_imports,
    )
    from desloppify.languages._framework.treesitter.specs.compiled import GO_SPEC

    script = tmp_path / "main.go"
    script.write_text(textwrap.dedent(contents).lstrip())
    return detect_unused_imports([str(script)], GO_SPEC)


def test_go_blank_import_is_never_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            _ "github.com/joho/godotenv/autoload"
        )

        func main() {}
        """,
    )

    assert findings == []


def test_go_dot_import_is_never_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            . "fmt"
        )

        func main() {
            Println("hi")
        }
        """,
    )

    assert findings == []


def test_go_gopkg_in_versioned_path_uses_package_name(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            "gopkg.in/yaml.v3"
        )

        func main() {
            yaml.Unmarshal(nil, nil)
        }
        """,
    )

    assert findings == []


def test_go_modules_major_version_suffix_uses_package_name(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            "math/rand/v2"
        )

        func main() {
            rand.N(10)
        }
        """,
    )

    assert findings == []


def test_go_modules_double_digit_major_version_suffix_uses_package_name(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            "github.com/go-playground/validator/v10"
        )

        func main() {
            validator.New()
        }
        """,
    )

    assert findings == []


def test_go_hyphenated_repo_name_is_not_reported(tmp_path):
    """Package name ("anthropic") differs from the repo/dir name and the
    path base contains a hyphen, which can never be a valid Go identifier.
    Since the real name can't be resolved from the path alone, this must
    not be reported -- even though it's actually used below.
    """
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            "github.com/anthropics/anthropic-sdk-go"
        )

        func main() {
            var _ anthropic.MessageParam
        }
        """,
    )

    assert findings == []


def test_go_hyphenated_repo_name_still_not_reported_when_actually_unused(tmp_path):
    """Same as above, but the import is genuinely unused. Because the
    identifier can't be confidently derived from the path, we must stay
    silent rather than guess -- a false negative here is far cheaper than
    a false positive.
    """
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            "github.com/anthropics/anthropic-sdk-go"
        )

        func main() {}
        """,
    )

    assert findings == []


def test_go_aliased_import_uses_alias_name(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            myyaml "gopkg.in/yaml.v2"
        )

        func main() {
            myyaml.Unmarshal(nil, nil)
        }
        """,
    )

    assert findings == []


def test_go_unused_aliased_import_is_still_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            unusedpkg "fmt"
        )

        func main() {}
        """,
    )

    assert [entry["name"] for entry in findings] == ["unusedpkg"]


def test_go_genuinely_unused_plain_import_is_still_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            "os"
        )

        func main() {}
        """,
    )

    assert [entry["name"] for entry in findings] == ["os"]


def test_go_used_plain_import_is_not_flagged(tmp_path):
    findings = _detect(
        tmp_path,
        """
        package main

        import (
            "fmt"
        )

        func main() {
            fmt.Println("hi")
        }
        """,
    )

    assert findings == []
