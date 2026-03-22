"""Tests for desloppify.languages.typescript.fixers — all fixer modules.

Covers: __init__, common, imports, vars, logs, params, if_chain, useeffect.
"""

import textwrap

from desloppify.languages.typescript.fixers import __all__
from desloppify.languages.typescript.fixers.fixer_io import apply_fixer
from desloppify.languages.typescript.fixers.if_chain import (
    fix_empty_if_chain,
)
from desloppify.languages.typescript.fixers.imports import fix_unused_imports
from desloppify.languages.typescript.fixers.logs import fix_debug_logs
from desloppify.languages.typescript.fixers.params import (
    _is_param_context,
    fix_unused_params,
)
from desloppify.languages.typescript.fixers.syntax_scan import (
    collapse_blank_lines,
    extract_body_between_braces,
    find_balanced_end,
)
from desloppify.languages.typescript.fixers.useeffect import fix_dead_useeffect
from desloppify.languages.typescript.fixers.vars import fix_unused_vars

# =====================================================================
# __init__.py — verify lazy fixer loader
# =====================================================================


class TestFixerInit:
    """Tests for the fixers __init__.py loader."""

    def test_all_exports_present(self):
        """__all__ lists all expected fixer functions."""
        expected = [
            "fix_debug_logs",
            "fix_unused_imports",
            "fix_unused_vars",
            "fix_unused_params",
            "fix_dead_useeffect",
            "fix_empty_if_chain",
        ]
        assert set(__all__) == set(expected)

    def test_imports_resolve(self):
        """All exported names can be imported."""
        for fn in [
            fix_debug_logs,
            fix_unused_imports,
            fix_unused_vars,
            fix_unused_params,
            fix_dead_useeffect,
            fix_empty_if_chain,
        ]:
            assert callable(fn)


# =====================================================================
# common.py — find_balanced_end, extract_body_between_braces, apply_fixer,
#              collapse_blank_lines
# =====================================================================


class TestCommonFindBalancedEnd:
    """Tests for find_balanced_end()."""

    def test_single_line_parens(self):
        """Balanced parens on a single line returns that line index."""
        lines = ["foo(bar)\n"]
        assert find_balanced_end(lines, 0, track="parens") == 0

    def test_multiline_parens(self):
        """Parens spanning multiple lines returns the closing line."""
        lines = ["foo(\n", "  bar,\n", "  baz\n", ")\n"]
        assert find_balanced_end(lines, 0, track="parens") == 3

    def test_braces_tracking(self):
        """Brace tracking returns line of closing brace."""
        lines = ["if (x) {\n", "  return 1;\n", "}\n"]
        assert find_balanced_end(lines, 0, track="braces") == 2

    def test_nested_braces(self):
        """Nested braces are properly tracked."""
        lines = ["function f() {\n", "  if (x) {\n", "    return 1;\n", "  }\n", "}\n"]
        assert find_balanced_end(lines, 0, track="braces") == 4

    def test_string_escaping(self):
        """Brackets inside string literals are ignored."""
        lines = ["foo('not a (' + bar)\n"]
        assert find_balanced_end(lines, 0, track="parens") == 0

    def test_returns_none_when_unbalanced(self):
        """Returns None if braces never balance."""
        lines = ["foo(\n", "  bar\n"]
        assert find_balanced_end(lines, 0, track="parens") is None


class TestCommonExtractBody:
    """Tests for extract_body_between_braces()."""

    def test_simple_body(self):
        """Extracts content between first { and matching }."""
        text = "function f() { return 1; }"
        body = extract_body_between_braces(text)
        assert body.strip() == "return 1;"

    def test_search_after(self):
        """search_after skips to content after the marker."""
        text = "const f = () => { return 42; }"
        body = extract_body_between_braces(text, search_after="=>")
        assert body.strip() == "return 42;"

    def test_nested_braces(self):
        """Nested braces are handled correctly."""
        text = "function f() { if (x) { return 1; } return 2; }"
        body = extract_body_between_braces(text)
        assert "if (x)" in body
        assert "return 2;" in body

    def test_no_braces_returns_none(self):
        """Returns None if no braces are present."""
        assert extract_body_between_braces("no braces here") is None

    def test_search_after_not_found_returns_none(self):
        """Returns None if search_after marker not found."""
        assert extract_body_between_braces("no marker", search_after="=>") is None


class TestCommonCollapseBlankLines:
    """Tests for collapse_blank_lines()."""

    def test_removes_indices(self):
        """Lines at specified indices are removed."""
        lines = ["a\n", "b\n", "c\n"]
        result = collapse_blank_lines(lines, removed_indices={1})
        assert result == ["a\n", "c\n"]

    def test_collapses_double_blanks(self):
        """Consecutive blank lines are collapsed to one."""
        lines = ["a\n", "\n", "\n", "b\n"]
        result = collapse_blank_lines(lines)
        assert result == ["a\n", "\n", "b\n"]

    def test_no_indices_still_collapses(self):
        """Even without removed_indices, double blanks are collapsed."""
        lines = ["x\n", "\n", "\n", "\n", "y\n"]
        result = collapse_blank_lines(lines)
        assert result == ["x\n", "\n", "y\n"]


class TestCommonApplyFixer:
    """Tests for apply_fixer() template."""

    def test_applies_transform_and_writes(self, tmp_path):
        """apply_fixer writes transformed content atomically."""
        ts_file = tmp_path / "test.ts"
        ts_file.write_text("line_a\nline_b\nline_c\n")

        entries = [{"file": str(ts_file), "target": "line_b"}]

        def transform(lines, file_entries):
            new_lines = [line for line in lines if "line_b" not in line]
            return new_lines, ["line_b"]

        results = apply_fixer(entries, transform, dry_run=False)
        assert len(results) == 1
        assert results[0]["removed"] == ["line_b"]
        assert results[0]["lines_removed"] == 1
        assert "line_b" not in ts_file.read_text()

    def test_dry_run_does_not_write(self, tmp_path):
        """apply_fixer with dry_run=True does not modify the file."""
        ts_file = tmp_path / "test.ts"
        original = "line_a\nline_b\nline_c\n"
        ts_file.write_text(original)

        entries = [{"file": str(ts_file), "target": "line_b"}]

        def transform(lines, file_entries):
            new_lines = [line for line in lines if "line_b" not in line]
            return new_lines, ["line_b"]

        results = apply_fixer(entries, transform, dry_run=True)
        assert len(results) == 1
        assert ts_file.read_text() == original

    def test_no_change_no_result(self, tmp_path):
        """If transform returns the same content, no result is produced."""
        ts_file = tmp_path / "test.ts"
        ts_file.write_text("line_a\nline_b\n")

        entries = [{"file": str(ts_file)}]

        def transform(lines, file_entries):
            return lines, []

        results = apply_fixer(entries, transform, dry_run=False)
        assert results == []

    def test_atomic_write_no_tmp_left(self, tmp_path):
        """After apply_fixer, no .tmp files remain."""
        ts_file = tmp_path / "test.ts"
        ts_file.write_text("a\nb\nc\n")

        entries = [{"file": str(ts_file)}]

        def transform(lines, file_entries):
            return [line for line in lines if "b" not in line], ["b"]

        apply_fixer(entries, transform, dry_run=False)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


# =====================================================================
# imports.py — fix_unused_imports
# =====================================================================


class TestFixUnusedImports:
    """Tests for fix_unused_imports()."""

    def test_remove_entire_import(self, tmp_path):
        """An entirely unused import statement is removed."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            import { unused } from './utils';
            import { used } from './helpers';

            console.log(used);
        """)
        )
        entries = [
            {"file": str(ts_file), "name": "unused", "line": 1, "category": "imports"},
        ]
        result = fix_unused_imports(entries, dry_run=False)
        assert len(result.entries) == 1
        content = ts_file.read_text()
        assert "unused" not in content
        assert "used" in content

    def test_remove_symbol_from_multi_import(self, tmp_path):
        """One symbol is removed from a multi-symbol import, others kept."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            import { alpha, beta, gamma } from './lib';

            console.log(alpha, gamma);
        """)
        )
        entries = [
            {"file": str(ts_file), "name": "beta", "line": 1, "category": "imports"},
        ]
        _ = fix_unused_imports(entries, dry_run=False)
        content = ts_file.read_text()
        assert "beta" not in content
        assert "alpha" in content
        assert "gamma" in content

    def test_remove_entire_import_marker(self, tmp_path):
        """(entire import) marker removes the whole import statement."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            import React from 'react';
            import { useState } from 'react';

            useState();
        """)
        )
        entries = [
            {
                "file": str(ts_file),
                "name": "(entire import)",
                "line": 1,
                "category": "imports",
            },
        ]
        _ = fix_unused_imports(entries, dry_run=False)
        content = ts_file.read_text()
        assert "import React" not in content
        assert "useState" in content

    def test_filters_non_import_entries(self, tmp_path):
        """Entries with category != 'imports' are ignored."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("import { x } from './x';\n")
        entries = [
            {"file": str(ts_file), "name": "x", "line": 1, "category": "vars"},
        ]
        result = fix_unused_imports(entries, dry_run=False)
        assert result.entries == []

    def test_dry_run(self, tmp_path):
        """dry_run=True reports changes without writing."""
        ts_file = tmp_path / "app.ts"
        original = "import { unused } from './utils';\n\nconsole.log('hi');\n"
        ts_file.write_text(original)
        entries = [
            {"file": str(ts_file), "name": "unused", "line": 1, "category": "imports"},
        ]
        result = fix_unused_imports(entries, dry_run=True)
        assert len(result.entries) == 1
        assert ts_file.read_text() == original

    def test_removes_alias_by_local_name_with_inline_comment(self, tmp_path):
        """Unused alias bindings are removed even when import has a trailing comment."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            "import { foo as bar, baz } from './m'; // keep\nconsole.log(baz)\n"
        )
        entries = [
            {"file": str(ts_file), "name": "bar", "line": 1, "category": "imports"},
        ]

        result = fix_unused_imports(entries, dry_run=False)
        content = ts_file.read_text()

        assert len(result.entries) == 1
        assert result.entries[0]["removed"] == ["bar"]
        assert "foo as bar" not in content
        assert "{ baz }" in content
        assert "// keep" in content

    def test_removes_type_prefixed_named_member(self, tmp_path):
        """`type Foo` members in named imports are removable by the `Foo` symbol."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            "import { type Request, randomUUID } from 'crypto';\n"
            "console.log(randomUUID())\n"
        )
        entries = [
            {"file": str(ts_file), "name": "Request", "line": 1, "category": "imports"},
        ]

        result = fix_unused_imports(entries, dry_run=False)
        content = ts_file.read_text()

        assert len(result.entries) == 1
        assert result.entries[0]["removed"] == ["Request"]
        assert "type Request" not in content
        assert "randomUUID" in content

    def test_removes_namespace_import_by_alias(self, tmp_path):
        """Namespace imports are removable when tsc reports the alias as unused."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("import * as utils from './utils';\nconsole.log('x')\n")
        entries = [
            {"file": str(ts_file), "name": "utils", "line": 1, "category": "imports"},
        ]

        result = fix_unused_imports(entries, dry_run=False)
        content = ts_file.read_text()

        assert len(result.entries) == 1
        assert result.entries[0]["removed"] == ["utils"]
        assert "import * as utils" not in content


# =====================================================================
# vars.py — fix_unused_vars
# =====================================================================


class TestFixUnusedVars:
    """Tests for fix_unused_vars()."""

    def test_remove_multiline_destructuring_member(self, tmp_path):
        """A member on its own line in a multi-line destructuring is removed."""
        ts_file = tmp_path / "comp.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            const {
              alpha,
              beta,
              gamma,
            } = props;
            console.log(alpha, gamma);
        """)
        )
        entries = [{"file": str(ts_file), "name": "beta", "line": 3}]
        result = fix_unused_vars(entries, dry_run=False)
        assert len(result.entries) == 1
        content = ts_file.read_text()
        # beta should be gone from the destructuring
        assert "beta" not in content
        assert "alpha" in content
        assert "gamma" in content

    def test_remove_inline_destructuring_member(self, tmp_path):
        """A member in a single-line destructuring is removed."""
        ts_file = tmp_path / "comp.ts"
        ts_file.write_text("const { a, unused, b } = obj;\n")
        entries = [{"file": str(ts_file), "name": "unused", "line": 1}]
        result = fix_unused_vars(entries, dry_run=False)
        assert len(result.entries) == 1
        content = ts_file.read_text()
        assert "unused" not in content
        assert "a" in content
        assert "b" in content

    def test_skip_rest_element(self, tmp_path):
        """Destructuring with ...rest is skipped (removing a member changes rest)."""
        ts_file = tmp_path / "comp.ts"
        ts_file.write_text("const { a, unused, ...rest } = obj;\n")
        entries = [{"file": str(ts_file), "name": "unused", "line": 1}]
        result = fix_unused_vars(entries, dry_run=False)
        assert result.entries == []
        assert result.skip_reasons.get("rest_element", 0) > 0

    def test_remove_standalone_var(self, tmp_path):
        """A standalone const assignment is removed entirely."""
        ts_file = tmp_path / "comp.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            const unused = 42;
            const used = 1;
            console.log(used);
        """)
        )
        entries = [{"file": str(ts_file), "name": "unused", "line": 1}]
        result = fix_unused_vars(entries, dry_run=False)
        assert len(result.entries) == 1
        content = ts_file.read_text()
        assert "unused" not in content
        assert "used" in content

    def test_dry_run(self, tmp_path):
        """dry_run=True does not modify files."""
        ts_file = tmp_path / "comp.ts"
        original = "const { a, unused } = obj;\n"
        ts_file.write_text(original)
        entries = [{"file": str(ts_file), "name": "unused", "line": 1}]
        fix_unused_vars(entries, dry_run=True)
        assert ts_file.read_text() == original


# =====================================================================
# logs.py — fix_debug_logs
# =====================================================================


class TestFixDebugLogs:
    """Tests for fix_debug_logs()."""

    def test_remove_single_log(self, tmp_path):
        """A single tagged console.log is removed."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            function foo() {
              console.log('[DEBUG] test');
              return 1;
            }
        """)
        )
        entries = [
            {
                "file": str(ts_file),
                "line": 2,
                "tag": "DEBUG",
                "content": "console.log('[DEBUG] test');",
            }
        ]
        result = fix_debug_logs(entries, dry_run=False)
        assert len(result.entries) == 1
        content = ts_file.read_text()
        assert "console.log" not in content
        assert "return 1;" in content

    def test_remove_multiline_log(self, tmp_path):
        """A multi-line console.log call is fully removed."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            function foo() {
              console.log(
                '[DEBUG] multi',
                someVar
              );
              return 1;
            }
        """)
        )
        entries = [
            {"file": str(ts_file), "line": 2, "tag": "DEBUG", "content": "console.log("}
        ]
        result = fix_debug_logs(entries, dry_run=False)
        assert len(result.entries) == 1
        content = ts_file.read_text()
        assert "console.log" not in content
        assert "return 1;" in content

    def test_removes_orphaned_debug_comment(self, tmp_path):
        """A preceding // DEBUG comment is removed along with the log."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            function foo() {
              // DEBUG: temporary logging
              console.log('[DEBUG] test');
              return 1;
            }
        """)
        )
        entries = [
            {
                "file": str(ts_file),
                "line": 3,
                "tag": "DEBUG",
                "content": "console.log('[DEBUG] test');",
            }
        ]
        _ = fix_debug_logs(entries, dry_run=False)
        content = ts_file.read_text()
        assert "DEBUG" not in content

    def test_keeps_logger_wrapper_arrow_methods(self, tmp_path):
        """Logger object arrow-method wrappers around console.log are preserved."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            const log = {
              info: (msg: string) => console.log('[APP] ' + msg),
              warn: (msg: string) => console.log('[APP] ' + msg),
              error: (msg: string) => console.error('[APP] ' + msg),
            };
        """)
        )
        entries = [
            {
                "file": str(ts_file),
                "line": 2,
                "tag": "APP",
                "content": "info: (msg: string) => console.log('[APP] ' + msg),",
            },
            {
                "file": str(ts_file),
                "line": 3,
                "tag": "APP",
                "content": "warn: (msg: string) => console.log('[APP] ' + msg),",
            },
        ]
        result = fix_debug_logs(entries, dry_run=False)
        assert result.entries == []
        content = ts_file.read_text()
        assert "info:" in content
        assert "warn:" in content
        assert "error:" in content

    def test_keeps_logger_wrapper_method_bodies(self, tmp_path):
        """Logger object methods that contain console.log are preserved."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            const log = {
              info(msg: string) {
                console.log('[APP] ' + msg);
              },
            };
        """)
        )
        entries = [
            {
                "file": str(ts_file),
                "line": 3,
                "tag": "APP",
                "content": "console.log('[APP] ' + msg);",
            }
        ]
        result = fix_debug_logs(entries, dry_run=False)
        assert result.entries == []
        content = ts_file.read_text()
        assert "info(msg: string)" in content
        assert "console.log('[APP] '" in content

    def test_dry_run(self, tmp_path):
        """dry_run=True reports changes without writing."""
        ts_file = tmp_path / "app.ts"
        original = "console.log('[DEBUG] x');\nreturn 1;\n"
        ts_file.write_text(original)
        entries = [
            {
                "file": str(ts_file),
                "line": 1,
                "tag": "DEBUG",
                "content": "console.log('[DEBUG] x');",
            }
        ]
        result = fix_debug_logs(entries, dry_run=True)
        assert len(result.entries) == 1
        assert ts_file.read_text() == original

    def test_zero_line_number_skipped(self, tmp_path):
        """An entry with line=0 is skipped without corrupting the file."""
        ts_file = tmp_path / "app.ts"
        original = "function foo() {\n  return 1;\n}\n"
        ts_file.write_text(original)
        entries = [
            {
                "file": str(ts_file),
                "line": 0,
                "tag": "DEBUG",
                "content": "console.log('[DEBUG] oops');",
            }
        ]
        result = fix_debug_logs(entries, dry_run=False)
        # Entry is out-of-bounds (line 0 → index -1); file must be unchanged
        assert ts_file.read_text() == original
        assert len(result.entries) == 0

    def test_result_metadata(self, tmp_path):
        """Result dict contains expected keys: file, tags, lines_removed, log_count."""
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("console.log('[TRACE] hi');\nkeep me;\n")
        entries = [
            {
                "file": str(ts_file),
                "line": 1,
                "tag": "TRACE",
                "content": "console.log('[TRACE] hi');",
            }
        ]
        result = fix_debug_logs(entries, dry_run=False)
        assert len(result.entries) == 1
        r = result.entries[0]
        assert "tags" in r
        assert "TRACE" in r["tags"]
        assert "lines_removed" in r
        assert "log_count" in r


# =====================================================================
# params.py — _is_param_context, fix_unused_params
# =====================================================================


class TestIsParamContext:
    """Tests for _is_param_context()."""

    def test_function_param_context(self):
        """Line inside a function param list is recognized."""
        lines = ["function foo(\n", "  a: string,\n", "  b: number\n", ") {\n"]
        # Line 1 (a: string) should be in a param context
        assert _is_param_context(lines, 1) is True

    def test_not_param_context(self):
        """Line not inside any param list returns False."""
        lines = ["const x = 1;\n", "const y = 2;\n"]
        assert _is_param_context(lines, 1) is False

    def test_catch_param_context(self):
        """Line inside a catch() param list is recognized."""
        lines = ["} catch(\n", "  error\n", ") {\n"]
        assert _is_param_context(lines, 1) is True


class TestFixUnusedParams:
    """Tests for fix_unused_params()."""

    def test_prefix_unused_param(self, tmp_path):
        """Unused function param is prefixed with _."""
        ts_file = tmp_path / "handler.ts"
        ts_file.write_text(
            textwrap.dedent("""\
            function handler(event: Event, context: Context) {
              return context.done();
            }
        """)
        )
        entries = [
            {
                "file": str(ts_file),
                "name": "event",
                "line": 1,
                "col": 18,
                "category": "vars",
            },
        ]
        result = fix_unused_params(entries, dry_run=False)
        assert len(result.entries) == 1
        content = ts_file.read_text()
        assert "_event" in content
        assert "context" in content  # untouched

    def test_skip_already_prefixed(self, tmp_path):
        """Params already starting with _ are not double-prefixed."""
        ts_file = tmp_path / "handler.ts"
        ts_file.write_text("function handler(_event: Event) { }\n")
        entries = [
            {
                "file": str(ts_file),
                "name": "_event",
                "line": 1,
                "col": 18,
                "category": "vars",
            },
        ]
        result = fix_unused_params(entries, dry_run=False)
        assert result.entries == []

    def test_dry_run(self, tmp_path):
        """dry_run=True does not modify the file."""
        ts_file = tmp_path / "handler.ts"
        original = "function handler(event: Event) { }\n"
        ts_file.write_text(original)
        entries = [
            {
                "file": str(ts_file),
                "name": "event",
                "line": 1,
                "col": 18,
                "category": "vars",
            },
        ]
        _ = fix_unused_params(entries, dry_run=True)
        assert ts_file.read_text() == original


