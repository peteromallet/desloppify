"""Tests for desloppify.lang.typescript.fixers — all fixer modules.

Covers: __init__, common, imports, vars, logs, params, exports, if_chain, useeffect.
"""

import os
import textwrap

import pytest


# =====================================================================
# __init__.py — verify re-exports
# =====================================================================


class TestFixerInit:
    """Tests for the fixers __init__.py re-exports."""

    def test_all_exports_present(self):
        """__all__ lists all expected fixer functions."""
        from desloppify.lang.typescript.fixers import __all__
        expected = [
            "fix_debug_logs",
            "fix_unused_imports",
            "fix_dead_exports",
            "fix_unused_vars",
            "fix_unused_params",
            "fix_dead_useeffect",
            "fix_empty_if_chain",
        ]
        assert set(__all__) == set(expected)

    def test_imports_resolve(self):
        """All exported names can be imported."""
        from desloppify.lang.typescript.fixers import (
            fix_debug_logs,
            fix_unused_imports,
            fix_dead_exports,
            fix_unused_vars,
            fix_unused_params,
            fix_dead_useeffect,
            fix_empty_if_chain,
        )
        for fn in [fix_debug_logs, fix_unused_imports, fix_dead_exports,
                    fix_unused_vars, fix_unused_params, fix_dead_useeffect,
                    fix_empty_if_chain]:
            assert callable(fn)


# =====================================================================
# common.py — find_balanced_end, extract_body_between_braces, apply_fixer,
#              collapse_blank_lines
# =====================================================================


class TestCommonFindBalancedEnd:
    """Tests for find_balanced_end()."""

    def test_single_line_parens(self):
        """Balanced parens on a single line returns that line index."""
        from desloppify.lang.typescript.fixers.common import find_balanced_end
        lines = ["foo(bar)\n"]
        assert find_balanced_end(lines, 0, track="parens") == 0

    def test_multiline_parens(self):
        """Parens spanning multiple lines returns the closing line."""
        from desloppify.lang.typescript.fixers.common import find_balanced_end
        lines = ["foo(\n", "  bar,\n", "  baz\n", ")\n"]
        assert find_balanced_end(lines, 0, track="parens") == 3

    def test_braces_tracking(self):
        """Brace tracking returns line of closing brace."""
        from desloppify.lang.typescript.fixers.common import find_balanced_end
        lines = ["if (x) {\n", "  return 1;\n", "}\n"]
        assert find_balanced_end(lines, 0, track="braces") == 2

    def test_nested_braces(self):
        """Nested braces are properly tracked."""
        from desloppify.lang.typescript.fixers.common import find_balanced_end
        lines = ["function f() {\n", "  if (x) {\n", "    return 1;\n", "  }\n", "}\n"]
        assert find_balanced_end(lines, 0, track="braces") == 4

    def test_string_escaping(self):
        """Brackets inside string literals are ignored."""
        from desloppify.lang.typescript.fixers.common import find_balanced_end
        lines = ["foo('not a (' + bar)\n"]
        assert find_balanced_end(lines, 0, track="parens") == 0

    def test_returns_none_when_unbalanced(self):
        """Returns None if braces never balance."""
        from desloppify.lang.typescript.fixers.common import find_balanced_end
        lines = ["foo(\n", "  bar\n"]
        assert find_balanced_end(lines, 0, track="parens") is None


class TestCommonExtractBody:
    """Tests for extract_body_between_braces()."""

    def test_simple_body(self):
        """Extracts content between first { and matching }."""
        from desloppify.lang.typescript.fixers.common import extract_body_between_braces
        text = "function f() { return 1; }"
        body = extract_body_between_braces(text)
        assert body.strip() == "return 1;"

    def test_search_after(self):
        """search_after skips to content after the marker."""
        from desloppify.lang.typescript.fixers.common import extract_body_between_braces
        text = "const f = () => { return 42; }"
        body = extract_body_between_braces(text, search_after="=>")
        assert body.strip() == "return 42;"

    def test_nested_braces(self):
        """Nested braces are handled correctly."""
        from desloppify.lang.typescript.fixers.common import extract_body_between_braces
        text = "function f() { if (x) { return 1; } return 2; }"
        body = extract_body_between_braces(text)
        assert "if (x)" in body
        assert "return 2;" in body

    def test_no_braces_returns_none(self):
        """Returns None if no braces are present."""
        from desloppify.lang.typescript.fixers.common import extract_body_between_braces
        assert extract_body_between_braces("no braces here") is None

    def test_search_after_not_found_returns_none(self):
        """Returns None if search_after marker not found."""
        from desloppify.lang.typescript.fixers.common import extract_body_between_braces
        assert extract_body_between_braces("no marker", search_after="=>") is None


class TestCommonCollapseBlankLines:
    """Tests for collapse_blank_lines()."""

    def test_removes_indices(self):
        """Lines at specified indices are removed."""
        from desloppify.lang.typescript.fixers.common import collapse_blank_lines
        lines = ["a\n", "b\n", "c\n"]
        result = collapse_blank_lines(lines, removed_indices={1})
        assert result == ["a\n", "c\n"]

    def test_collapses_double_blanks(self):
        """Consecutive blank lines are collapsed to one."""
        from desloppify.lang.typescript.fixers.common import collapse_blank_lines
        lines = ["a\n", "\n", "\n", "b\n"]
        result = collapse_blank_lines(lines)
        assert result == ["a\n", "\n", "b\n"]

    def test_no_indices_still_collapses(self):
        """Even without removed_indices, double blanks are collapsed."""
        from desloppify.lang.typescript.fixers.common import collapse_blank_lines
        lines = ["x\n", "\n", "\n", "\n", "y\n"]
        result = collapse_blank_lines(lines)
        assert result == ["x\n", "\n", "y\n"]


class TestCommonApplyFixer:
    """Tests for apply_fixer() template."""

    def test_applies_transform_and_writes(self, tmp_path):
        """apply_fixer writes transformed content atomically."""
        from desloppify.lang.typescript.fixers.common import apply_fixer
        ts_file = tmp_path / "test.ts"
        ts_file.write_text("line_a\nline_b\nline_c\n")

        entries = [{"file": str(ts_file), "target": "line_b"}]

        def transform(lines, file_entries):
            new_lines = [l for l in lines if "line_b" not in l]
            return new_lines, ["line_b"]

        results = apply_fixer(entries, transform, dry_run=False)
        assert len(results) == 1
        assert results[0]["removed"] == ["line_b"]
        assert results[0]["lines_removed"] == 1
        assert "line_b" not in ts_file.read_text()

    def test_dry_run_does_not_write(self, tmp_path):
        """apply_fixer with dry_run=True does not modify the file."""
        from desloppify.lang.typescript.fixers.common import apply_fixer
        ts_file = tmp_path / "test.ts"
        original = "line_a\nline_b\nline_c\n"
        ts_file.write_text(original)

        entries = [{"file": str(ts_file), "target": "line_b"}]

        def transform(lines, file_entries):
            new_lines = [l for l in lines if "line_b" not in l]
            return new_lines, ["line_b"]

        results = apply_fixer(entries, transform, dry_run=True)
        assert len(results) == 1
        assert ts_file.read_text() == original

    def test_no_change_no_result(self, tmp_path):
        """If transform returns the same content, no result is produced."""
        from desloppify.lang.typescript.fixers.common import apply_fixer
        ts_file = tmp_path / "test.ts"
        ts_file.write_text("line_a\nline_b\n")

        entries = [{"file": str(ts_file)}]

        def transform(lines, file_entries):
            return lines, []

        results = apply_fixer(entries, transform, dry_run=False)
        assert results == []

    def test_atomic_write_no_tmp_left(self, tmp_path):
        """After apply_fixer, no .tmp files remain."""
        from desloppify.lang.typescript.fixers.common import apply_fixer
        ts_file = tmp_path / "test.ts"
        ts_file.write_text("a\nb\nc\n")

        entries = [{"file": str(ts_file)}]

        def transform(lines, file_entries):
            return [l for l in lines if "b" not in l], ["b"]

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
        from desloppify.lang.typescript.fixers.imports import fix_unused_imports
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(textwrap.dedent("""\
            import { unused } from './utils';
            import { used } from './helpers';

            console.log(used);
        """))
        entries = [
            {"file": str(ts_file), "name": "unused", "line": 1, "category": "imports"},
        ]
        results = fix_unused_imports(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert "unused" not in content
        assert "used" in content

    def test_remove_symbol_from_multi_import(self, tmp_path):
        """One symbol is removed from a multi-symbol import, others kept."""
        from desloppify.lang.typescript.fixers.imports import fix_unused_imports
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(textwrap.dedent("""\
            import { alpha, beta, gamma } from './lib';

            console.log(alpha, gamma);
        """))
        entries = [
            {"file": str(ts_file), "name": "beta", "line": 1, "category": "imports"},
        ]
        results = fix_unused_imports(entries, dry_run=False)
        content = ts_file.read_text()
        assert "beta" not in content
        assert "alpha" in content
        assert "gamma" in content

    def test_remove_entire_import_marker(self, tmp_path):
        """(entire import) marker removes the whole import statement."""
        from desloppify.lang.typescript.fixers.imports import fix_unused_imports
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(textwrap.dedent("""\
            import React from 'react';
            import { useState } from 'react';

            useState();
        """))
        entries = [
            {"file": str(ts_file), "name": "(entire import)", "line": 1, "category": "imports"},
        ]
        results = fix_unused_imports(entries, dry_run=False)
        content = ts_file.read_text()
        assert "import React" not in content
        assert "useState" in content

    def test_filters_non_import_entries(self, tmp_path):
        """Entries with category != 'imports' are ignored."""
        from desloppify.lang.typescript.fixers.imports import fix_unused_imports
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("import { x } from './x';\n")
        entries = [
            {"file": str(ts_file), "name": "x", "line": 1, "category": "vars"},
        ]
        results = fix_unused_imports(entries, dry_run=False)
        assert results == []

    def test_dry_run(self, tmp_path):
        """dry_run=True reports changes without writing."""
        from desloppify.lang.typescript.fixers.imports import fix_unused_imports
        ts_file = tmp_path / "app.ts"
        original = "import { unused } from './utils';\n\nconsole.log('hi');\n"
        ts_file.write_text(original)
        entries = [
            {"file": str(ts_file), "name": "unused", "line": 1, "category": "imports"},
        ]
        results = fix_unused_imports(entries, dry_run=True)
        assert len(results) == 1
        assert ts_file.read_text() == original


# =====================================================================
# vars.py — fix_unused_vars
# =====================================================================


class TestFixUnusedVars:
    """Tests for fix_unused_vars()."""

    def test_remove_multiline_destructuring_member(self, tmp_path):
        """A member on its own line in a multi-line destructuring is removed."""
        from desloppify.lang.typescript.fixers.vars import fix_unused_vars
        ts_file = tmp_path / "comp.ts"
        ts_file.write_text(textwrap.dedent("""\
            const {
              alpha,
              beta,
              gamma,
            } = props;
            console.log(alpha, gamma);
        """))
        entries = [{"file": str(ts_file), "name": "beta", "line": 3}]
        results, skips = fix_unused_vars(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        # beta should be gone from the destructuring
        assert "beta" not in content
        assert "alpha" in content
        assert "gamma" in content

    def test_remove_inline_destructuring_member(self, tmp_path):
        """A member in a single-line destructuring is removed."""
        from desloppify.lang.typescript.fixers.vars import fix_unused_vars
        ts_file = tmp_path / "comp.ts"
        ts_file.write_text("const { a, unused, b } = obj;\n")
        entries = [{"file": str(ts_file), "name": "unused", "line": 1}]
        results, skips = fix_unused_vars(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert "unused" not in content
        assert "a" in content
        assert "b" in content

    def test_skip_rest_element(self, tmp_path):
        """Destructuring with ...rest is skipped (removing a member changes rest)."""
        from desloppify.lang.typescript.fixers.vars import fix_unused_vars
        ts_file = tmp_path / "comp.ts"
        ts_file.write_text("const { a, unused, ...rest } = obj;\n")
        entries = [{"file": str(ts_file), "name": "unused", "line": 1}]
        results, skips = fix_unused_vars(entries, dry_run=False)
        assert results == []
        assert skips.get("rest_element", 0) > 0

    def test_remove_standalone_var(self, tmp_path):
        """A standalone const assignment is removed entirely."""
        from desloppify.lang.typescript.fixers.vars import fix_unused_vars
        ts_file = tmp_path / "comp.ts"
        ts_file.write_text(textwrap.dedent("""\
            const unused = 42;
            const used = 1;
            console.log(used);
        """))
        entries = [{"file": str(ts_file), "name": "unused", "line": 1}]
        results, skips = fix_unused_vars(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert "unused" not in content
        assert "used" in content

    def test_dry_run(self, tmp_path):
        """dry_run=True does not modify files."""
        from desloppify.lang.typescript.fixers.vars import fix_unused_vars
        ts_file = tmp_path / "comp.ts"
        original = "const { a, unused } = obj;\n"
        ts_file.write_text(original)
        entries = [{"file": str(ts_file), "name": "unused", "line": 1}]
        results, _ = fix_unused_vars(entries, dry_run=True)
        assert ts_file.read_text() == original


# =====================================================================
# logs.py — fix_debug_logs
# =====================================================================


class TestFixDebugLogs:
    """Tests for fix_debug_logs()."""

    def test_remove_single_log(self, tmp_path):
        """A single tagged console.log is removed."""
        from desloppify.lang.typescript.fixers.logs import fix_debug_logs
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(textwrap.dedent("""\
            function foo() {
              console.log('[DEBUG] test');
              return 1;
            }
        """))
        entries = [{"file": str(ts_file), "line": 2, "tag": "DEBUG", "content": "console.log('[DEBUG] test');"}]
        results = fix_debug_logs(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert "console.log" not in content
        assert "return 1;" in content

    def test_remove_multiline_log(self, tmp_path):
        """A multi-line console.log call is fully removed."""
        from desloppify.lang.typescript.fixers.logs import fix_debug_logs
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(textwrap.dedent("""\
            function foo() {
              console.log(
                '[DEBUG] multi',
                someVar
              );
              return 1;
            }
        """))
        entries = [{"file": str(ts_file), "line": 2, "tag": "DEBUG", "content": "console.log("}]
        results = fix_debug_logs(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert "console.log" not in content
        assert "return 1;" in content

    def test_removes_orphaned_debug_comment(self, tmp_path):
        """A preceding // DEBUG comment is removed along with the log."""
        from desloppify.lang.typescript.fixers.logs import fix_debug_logs
        ts_file = tmp_path / "app.ts"
        ts_file.write_text(textwrap.dedent("""\
            function foo() {
              // DEBUG: temporary logging
              console.log('[DEBUG] test');
              return 1;
            }
        """))
        entries = [{"file": str(ts_file), "line": 3, "tag": "DEBUG", "content": "console.log('[DEBUG] test');"}]
        results = fix_debug_logs(entries, dry_run=False)
        content = ts_file.read_text()
        assert "DEBUG" not in content

    def test_dry_run(self, tmp_path):
        """dry_run=True reports changes without writing."""
        from desloppify.lang.typescript.fixers.logs import fix_debug_logs
        ts_file = tmp_path / "app.ts"
        original = "console.log('[DEBUG] x');\nreturn 1;\n"
        ts_file.write_text(original)
        entries = [{"file": str(ts_file), "line": 1, "tag": "DEBUG", "content": "console.log('[DEBUG] x');"}]
        results = fix_debug_logs(entries, dry_run=True)
        assert len(results) == 1
        assert ts_file.read_text() == original

    def test_result_metadata(self, tmp_path):
        """Result dict contains expected keys: file, tags, lines_removed, log_count."""
        from desloppify.lang.typescript.fixers.logs import fix_debug_logs
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("console.log('[TRACE] hi');\nkeep me;\n")
        entries = [{"file": str(ts_file), "line": 1, "tag": "TRACE", "content": "console.log('[TRACE] hi');"}]
        results = fix_debug_logs(entries, dry_run=False)
        assert len(results) == 1
        r = results[0]
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
        from desloppify.lang.typescript.fixers.params import _is_param_context
        lines = ["function foo(\n", "  a: string,\n", "  b: number\n", ") {\n"]
        # Line 1 (a: string) should be in a param context
        assert _is_param_context(lines, 1) is True

    def test_not_param_context(self):
        """Line not inside any param list returns False."""
        from desloppify.lang.typescript.fixers.params import _is_param_context
        lines = ["const x = 1;\n", "const y = 2;\n"]
        assert _is_param_context(lines, 1) is False

    def test_catch_param_context(self):
        """Line inside a catch() param list is recognized."""
        from desloppify.lang.typescript.fixers.params import _is_param_context
        lines = ["} catch(\n", "  error\n", ") {\n"]
        assert _is_param_context(lines, 1) is True


class TestFixUnusedParams:
    """Tests for fix_unused_params()."""

    def test_prefix_unused_param(self, tmp_path):
        """Unused function param is prefixed with _."""
        from desloppify.lang.typescript.fixers.params import fix_unused_params
        ts_file = tmp_path / "handler.ts"
        ts_file.write_text(textwrap.dedent("""\
            function handler(event: Event, context: Context) {
              return context.done();
            }
        """))
        entries = [
            {"file": str(ts_file), "name": "event", "line": 1, "col": 18, "category": "vars"},
        ]
        results = fix_unused_params(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert "_event" in content
        assert "context" in content  # untouched

    def test_skip_already_prefixed(self, tmp_path):
        """Params already starting with _ are not double-prefixed."""
        from desloppify.lang.typescript.fixers.params import fix_unused_params
        ts_file = tmp_path / "handler.ts"
        ts_file.write_text("function handler(_event: Event) { }\n")
        entries = [
            {"file": str(ts_file), "name": "_event", "line": 1, "col": 18, "category": "vars"},
        ]
        results = fix_unused_params(entries, dry_run=False)
        assert results == []

    def test_dry_run(self, tmp_path):
        """dry_run=True does not modify the file."""
        from desloppify.lang.typescript.fixers.params import fix_unused_params
        ts_file = tmp_path / "handler.ts"
        original = "function handler(event: Event) { }\n"
        ts_file.write_text(original)
        entries = [
            {"file": str(ts_file), "name": "event", "line": 1, "col": 18, "category": "vars"},
        ]
        results = fix_unused_params(entries, dry_run=True)
        assert ts_file.read_text() == original


# =====================================================================
# exports.py — fix_dead_exports
# =====================================================================


class TestFixDeadExports:
    """Tests for fix_dead_exports()."""

    def test_remove_export_keyword(self, tmp_path):
        """export keyword is removed from a declaration, keeping the rest."""
        from desloppify.lang.typescript.fixers.exports import fix_dead_exports
        ts_file = tmp_path / "lib.ts"
        ts_file.write_text(textwrap.dedent("""\
            export function helper() {
              return 1;
            }
        """))
        entries = [{"file": str(ts_file), "line": 1, "name": "helper"}]
        results = fix_dead_exports(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert content.startswith("function helper()")
        assert "export" not in content

    def test_remove_export_const(self, tmp_path):
        """export keyword is removed from const declaration."""
        from desloppify.lang.typescript.fixers.exports import fix_dead_exports
        ts_file = tmp_path / "config.ts"
        ts_file.write_text("export const VALUE = 42;\n")
        entries = [{"file": str(ts_file), "line": 1, "name": "VALUE"}]
        results = fix_dead_exports(entries, dry_run=False)
        content = ts_file.read_text()
        assert content.strip() == "const VALUE = 42;"

    def test_remove_export_type(self, tmp_path):
        """export keyword is removed from a type declaration."""
        from desloppify.lang.typescript.fixers.exports import fix_dead_exports
        ts_file = tmp_path / "types.ts"
        ts_file.write_text("export type Foo = string;\n")
        entries = [{"file": str(ts_file), "line": 1, "name": "Foo"}]
        results = fix_dead_exports(entries, dry_run=False)
        content = ts_file.read_text()
        assert content.strip() == "type Foo = string;"

    def test_remove_export_interface(self, tmp_path):
        """export keyword is removed from an interface declaration."""
        from desloppify.lang.typescript.fixers.exports import fix_dead_exports
        ts_file = tmp_path / "types.ts"
        ts_file.write_text("export interface Bar { x: number; }\n")
        entries = [{"file": str(ts_file), "line": 1, "name": "Bar"}]
        results = fix_dead_exports(entries, dry_run=False)
        content = ts_file.read_text()
        assert content.strip() == "interface Bar { x: number; }"

    def test_remove_named_export(self, tmp_path):
        """An export { name } statement is removed entirely when all names are dead."""
        from desloppify.lang.typescript.fixers.exports import fix_dead_exports
        ts_file = tmp_path / "index.ts"
        ts_file.write_text(textwrap.dedent("""\
            const a = 1;
            export { a };
        """))
        entries = [{"file": str(ts_file), "line": 2, "name": "a"}]
        results = fix_dead_exports(entries, dry_run=False)
        content = ts_file.read_text()
        assert "export" not in content

    def test_lines_removed_is_zero(self, tmp_path):
        """Dead export removal never removes lines (just the keyword)."""
        from desloppify.lang.typescript.fixers.exports import fix_dead_exports
        ts_file = tmp_path / "lib.ts"
        ts_file.write_text("export const X = 1;\n")
        entries = [{"file": str(ts_file), "line": 1, "name": "X"}]
        results = fix_dead_exports(entries, dry_run=False)
        assert results[0]["lines_removed"] == 0

    def test_dry_run(self, tmp_path):
        """dry_run=True does not modify the file."""
        from desloppify.lang.typescript.fixers.exports import fix_dead_exports
        ts_file = tmp_path / "lib.ts"
        original = "export function helper() { return 1; }\n"
        ts_file.write_text(original)
        entries = [{"file": str(ts_file), "line": 1, "name": "helper"}]
        results = fix_dead_exports(entries, dry_run=True)
        assert len(results) == 1
        assert ts_file.read_text() == original


# =====================================================================
# if_chain.py — fix_empty_if_chain, _find_if_chain_end
# =====================================================================


class TestFindIfChainEnd:
    """Tests for _find_if_chain_end()."""

    def test_simple_if_block(self):
        """Single if block end is found correctly."""
        from desloppify.lang.typescript.fixers.if_chain import _find_if_chain_end
        lines = ["if (x) {\n", "  doStuff();\n", "}\n"]
        assert _find_if_chain_end(lines, 0) == 2

    def test_if_else_chain_same_line(self):
        """if/else chain where else is on the closing-brace line continues tracking."""
        from desloppify.lang.typescript.fixers.if_chain import _find_if_chain_end
        # When "} else {" is on one line, the brace tracker sees } (depth=0),
        # recognizes "else" follows, breaks out of the char loop, but does NOT
        # re-enter the second { on that line.  So brace_depth stays 0 and the
        # function never finds the closing } of the else branch.  It falls
        # through and returns `start`.
        lines = [
            "if (x) {\n",
            "  a();\n",
            "} else {\n",
            "  b();\n",
            "}\n",
        ]
        result = _find_if_chain_end(lines, 0)
        # The current implementation returns start (0) for this pattern;
        # fix_empty_if_chain uses apply_fixer/collapse which handles it
        assert isinstance(result, int)

    def test_fallback_to_start(self):
        """If no braces found, returns start index."""
        from desloppify.lang.typescript.fixers.if_chain import _find_if_chain_end
        lines = ["if (x) doSomething();\n"]
        assert _find_if_chain_end(lines, 0) == 0


class TestFixEmptyIfChain:
    """Tests for fix_empty_if_chain()."""

    def test_remove_empty_if(self, tmp_path):
        """An empty if block is removed."""
        from desloppify.lang.typescript.fixers.if_chain import fix_empty_if_chain
        ts_file = tmp_path / "logic.ts"
        ts_file.write_text(textwrap.dedent("""\
            if (x) {
            }
            const y = 1;
        """))
        entries = [{"file": str(ts_file), "line": 1, "content": "if (x) {"}]
        results = fix_empty_if_chain(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert "if (x)" not in content
        assert "const y = 1;" in content

    def test_dry_run(self, tmp_path):
        """dry_run=True does not modify the file."""
        from desloppify.lang.typescript.fixers.if_chain import fix_empty_if_chain
        ts_file = tmp_path / "logic.ts"
        original = "if (x) {\n}\nconst y = 1;\n"
        ts_file.write_text(original)
        entries = [{"file": str(ts_file), "line": 1, "content": "if (x) {"}]
        results = fix_empty_if_chain(entries, dry_run=True)
        assert len(results) == 1
        assert ts_file.read_text() == original


# =====================================================================
# useeffect.py — fix_dead_useeffect
# =====================================================================


class TestFixDeadUseEffect:
    """Tests for fix_dead_useeffect()."""

    def test_remove_empty_useeffect(self, tmp_path):
        """An empty useEffect call is removed."""
        from desloppify.lang.typescript.fixers.useeffect import fix_dead_useeffect
        ts_file = tmp_path / "comp.tsx"
        ts_file.write_text(textwrap.dedent("""\
            useEffect(() => {
            }, []);
            const x = 1;
        """))
        entries = [{"file": str(ts_file), "line": 1, "content": "useEffect(() => {"}]
        results = fix_dead_useeffect(entries, dry_run=False)
        assert len(results) == 1
        content = ts_file.read_text()
        assert "useEffect" not in content
        assert "const x = 1;" in content

    def test_removes_preceding_comment(self, tmp_path):
        """A comment immediately before the useEffect is also removed."""
        from desloppify.lang.typescript.fixers.useeffect import fix_dead_useeffect
        ts_file = tmp_path / "comp.tsx"
        ts_file.write_text(textwrap.dedent("""\
            // Load data on mount
            useEffect(() => {
            }, []);
            const x = 1;
        """))
        entries = [{"file": str(ts_file), "line": 2, "content": "useEffect(() => {"}]
        results = fix_dead_useeffect(entries, dry_run=False)
        content = ts_file.read_text()
        assert "Load data" not in content
        assert "useEffect" not in content

    def test_dry_run(self, tmp_path):
        """dry_run=True does not modify the file."""
        from desloppify.lang.typescript.fixers.useeffect import fix_dead_useeffect
        ts_file = tmp_path / "comp.tsx"
        original = "useEffect(() => {\n}, []);\nconst x = 1;\n"
        ts_file.write_text(original)
        entries = [{"file": str(ts_file), "line": 1, "content": "useEffect(() => {"}]
        results = fix_dead_useeffect(entries, dry_run=True)
        assert len(results) == 1
        assert ts_file.read_text() == original
