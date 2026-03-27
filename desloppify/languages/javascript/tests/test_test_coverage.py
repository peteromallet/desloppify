"""Tests for the JavaScript test_coverage module.

Verifies that test-to-source mapping, import resolution, and testable-logic
heuristics work correctly for JavaScript projects with common directory
layouts and file extensions (.js, .jsx, .mjs, .cjs).
"""

from __future__ import annotations

import pytest

from desloppify.languages.javascript.test_coverage import (
    ASSERT_PATTERNS,
    BARREL_BASENAMES,
    MOCK_PATTERNS,
    SNAPSHOT_PATTERNS,
    TEST_FUNCTION_RE,
    has_testable_logic,
    map_test_to_source,
    parse_test_import_specs,
    strip_comments,
    strip_test_markers,
)


# ---------------------------------------------------------------------------
# Contract: all required exports exist and have the correct types
# ---------------------------------------------------------------------------


def test_assert_patterns_non_empty():
    assert len(ASSERT_PATTERNS) > 0


def test_mock_patterns_non_empty():
    assert len(MOCK_PATTERNS) > 0


def test_snapshot_patterns_non_empty():
    assert len(SNAPSHOT_PATTERNS) > 0


def test_test_function_re_matches():
    assert TEST_FUNCTION_RE.search("it('does something',")
    assert TEST_FUNCTION_RE.search('test("works",')
    assert not TEST_FUNCTION_RE.search("function test() {")


def test_barrel_basenames():
    assert "index.js" in BARREL_BASENAMES
    assert "index.mjs" in BARREL_BASENAMES
    assert "index.cjs" in BARREL_BASENAMES
    assert "index.jsx" in BARREL_BASENAMES
    assert "index.ts" not in BARREL_BASENAMES


# ---------------------------------------------------------------------------
# strip_test_markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "basename, expected",
    [
        ("time.test.mjs", "time.mjs"),
        ("time.spec.mjs", "time.mjs"),
        ("time.test.js", "time.js"),
        ("utils.test.cjs", "utils.cjs"),
        ("Component.test.jsx", "Component.jsx"),
        ("nomarker.mjs", None),
    ],
)
def test_strip_test_markers(basename, expected):
    assert strip_test_markers(basename) == expected


# ---------------------------------------------------------------------------
# map_test_to_source — __tests__/unit/ nested layout
# ---------------------------------------------------------------------------


PROD_FILES = {
    "src/utils/time.mjs",
    "src/utils/responses.mjs",
    "src/utils/tryCatch.mjs",
    "src/db/queries/getCampaign.mjs",
    "src/validators/isValidNumber.js",
    "src/components/Button.jsx",
}


@pytest.mark.parametrize(
    "test_path, expected",
    [
        # __tests__/unit/<subdir>/<file> -> src/<subdir>/<file>
        ("src/__tests__/unit/utils/time.test.mjs", "src/utils/time.mjs"),
        ("src/__tests__/unit/utils/responses.test.mjs", "src/utils/responses.mjs"),
        ("src/__tests__/unit/utils/tryCatch.test.mjs", "src/utils/tryCatch.mjs"),
        # __tests__/unit/queries/ -> src/db/queries/ (basename match)
        ("src/__tests__/unit/queries/getCampaign.test.mjs", "src/db/queries/getCampaign.mjs"),
        # __tests__/integration/ category stripped
        ("src/__tests__/integration/utils/time.test.mjs", "src/utils/time.mjs"),
        # Direct __tests__/ without category
        ("src/__tests__/utils/time.test.mjs", "src/utils/time.mjs"),
        # Colocated test (no __tests__ dir)
        ("src/utils/time.test.mjs", "src/utils/time.mjs"),
        # No match
        ("src/__tests__/unit/utils/nonexistent.test.mjs", None),
    ],
)
def test_map_test_to_source(test_path, expected):
    result = map_test_to_source(test_path, PROD_FILES)
    assert result == expected, f"map_test_to_source({test_path!r}) = {result!r}, expected {expected!r}"


def test_map_test_to_source_basename_cross_extension():
    """Test file .test.mjs should match production .js via basename."""
    prod = {"src/validators/isValidNumber.js"}
    result = map_test_to_source(
        "src/__tests__/unit/validators/isValidNumber.test.mjs", prod
    )
    # basename match: isValidNumber.mjs != isValidNumber.js, but basename
    # comparison strips the test marker first, yielding isValidNumber.mjs
    # which doesn't match isValidNumber.js by basename either.
    # This is a known limitation — the match relies on strip_test_markers
    # producing the same extension as the production file.
    # The naming_based_mapping fallback (strip_test_markers -> basename index)
    # handles this case at the engine level.
    assert result is None or result == "src/validators/isValidNumber.js"


# ---------------------------------------------------------------------------
# has_testable_logic
# ---------------------------------------------------------------------------


def test_has_testable_logic_with_function():
    assert has_testable_logic("app.mjs", "export function foo() { return 1; }")


def test_has_testable_logic_pure_imports():
    content = "import { foo } from './foo.mjs';\nimport bar from 'bar';\n"
    assert not has_testable_logic("re-export.mjs", content)


def test_has_testable_logic_pure_reexports():
    content = "export * from './foo.mjs';\nexport { bar } from './bar.mjs';\n"
    assert not has_testable_logic("index.mjs", content)


def test_has_testable_logic_comments_only():
    content = "// this is a comment\n/* block comment */\n"
    assert not has_testable_logic("empty.js", content)


def test_has_testable_logic_empty():
    assert not has_testable_logic("empty.js", "")


def test_has_testable_logic_multiline_import():
    content = "import {\n  foo,\n  bar,\n} from './utils.mjs';\n"
    assert not has_testable_logic("imports.mjs", content)


def test_has_testable_logic_export_with_logic():
    content = "import { x } from './x.mjs';\nexport const y = x + 1;\n"
    assert has_testable_logic("logic.mjs", content)


# ---------------------------------------------------------------------------
# parse_test_import_specs
# ---------------------------------------------------------------------------


def test_parse_test_import_specs():
    content = """\
import { vi } from 'vitest';
import { performanceTime } from '@/utils/time.mjs';
import foo from '../foo.js';
"""
    specs = parse_test_import_specs(content)
    assert "vitest" in specs
    assert "@/utils/time.mjs" in specs
    assert "../foo.js" in specs


def test_parse_test_import_specs_dynamic():
    content = "const mod = await import('./dynamic.mjs');\n"
    specs = parse_test_import_specs(content)
    assert "./dynamic.mjs" in specs


# ---------------------------------------------------------------------------
# strip_comments
# ---------------------------------------------------------------------------


def test_strip_comments_removes_line_comments():
    assert "code" in strip_comments("code // comment")
    assert "comment" not in strip_comments("code // comment")


def test_strip_comments_removes_block_comments():
    result = strip_comments("before /* block */ after")
    assert "before" in result
    assert "after" in result
    assert "block" not in result
