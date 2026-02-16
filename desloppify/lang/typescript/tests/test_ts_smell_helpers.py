"""Tests for desloppify.lang.typescript.detectors._smell_helpers — string processing helpers."""

import pytest

from desloppify.lang.typescript.detectors._smell_helpers import (
    _strip_ts_comments,
    _ts_match_is_in_string,
    _track_brace_body,
    _detect_async_no_await,
    _detect_error_no_throw,
    _detect_empty_if_chains,
    _detect_dead_useeffects,
    _detect_swallowed_errors,
)
from desloppify.lang.typescript.detectors._smell_detectors import (
    _find_function_start,
    _detect_monster_functions,
    _detect_dead_functions,
    _detect_window_globals,
    _detect_catch_return_default,
)


# ── _strip_ts_comments ───────────────────────────────────────


class TestStripTsComments:
    def test_strips_line_comment(self):
        assert _strip_ts_comments("code // comment") == "code "

    def test_strips_block_comment(self):
        assert _strip_ts_comments("before /* block */ after") == "before  after"

    def test_preserves_string_with_slashes(self):
        result = _strip_ts_comments('const url = "http://example.com";')
        assert "http://example.com" in result

    def test_preserves_single_quoted_string(self):
        result = _strip_ts_comments("const s = '// not a comment';")
        assert "// not a comment" in result

    def test_preserves_template_literal(self):
        result = _strip_ts_comments("const s = `// not a comment`;")
        assert "// not a comment" in result

    def test_strips_multiline_block_comment(self):
        text = "start /* this is\na multiline\ncomment */ end"
        result = _strip_ts_comments(text)
        assert "start" in result
        assert "end" in result
        assert "multiline" not in result

    def test_empty_input(self):
        assert _strip_ts_comments("") == ""

    def test_no_comments(self):
        code = "const x = 1;\nconst y = 2;"
        assert _strip_ts_comments(code) == code

    def test_nested_string_in_comment_region(self):
        # The comment contains string-like characters
        result = _strip_ts_comments('code /* "not a string" */ more')
        assert "code" in result
        assert "more" in result
        assert "not a string" not in result

    def test_unterminated_block_comment(self):
        # Unterminated block comment -- should strip to end
        result = _strip_ts_comments("code /* unterminated")
        assert result == "code "

    def test_unterminated_line_comment(self):
        result = _strip_ts_comments("code // line comment no newline")
        assert result == "code "


# ── _ts_match_is_in_string ───────────────────────────────────


class TestTsMatchIsInString:
    def test_match_in_double_quoted_string(self):
        line = 'const s = "any type";'
        pos = line.index("any")
        assert _ts_match_is_in_string(line, pos) is True

    def test_match_in_single_quoted_string(self):
        line = "const s = 'any type';"
        pos = line.index("any")
        assert _ts_match_is_in_string(line, pos) is True

    def test_match_in_template_literal(self):
        line = "const s = `any type`;"
        pos = line.index("any")
        assert _ts_match_is_in_string(line, pos) is True

    def test_match_in_code(self):
        line = "const x: any = 5;"
        pos = line.index("any")
        assert _ts_match_is_in_string(line, pos) is False

    def test_match_in_line_comment(self):
        line = "const x = 1; // any type here"
        pos = line.index("any")
        assert _ts_match_is_in_string(line, pos) is True

    def test_match_after_escaped_quote(self):
        line = r"const s = 'it\'s any type';"
        # After the escaped quote, "any" is still inside the string
        pos = line.index("any")
        assert _ts_match_is_in_string(line, pos) is True

    def test_match_at_start_of_line(self):
        line = "any = 5;"
        assert _ts_match_is_in_string(line, 0) is False

    def test_match_after_string_closes(self):
        line = "const s = 'hi'; const x: any = 5;"
        pos = line.rindex("any")
        assert _ts_match_is_in_string(line, pos) is False

    def test_empty_line(self):
        assert _ts_match_is_in_string("", 0) is False


# ── _track_brace_body ────────────────────────────────────────


class TestTrackBraceBody:
    def test_simple_function(self):
        lines = ["function foo() {", "  return 1;", "}"]
        assert _track_brace_body(lines, 0) == 2

    def test_nested_braces(self):
        lines = ["function foo() {", "  if (true) {", "    return 1;", "  }", "}"]
        assert _track_brace_body(lines, 0) == 4

    def test_braces_in_string_ignored(self):
        lines = ["function foo() {", "  const s = '{}';", "}"]
        assert _track_brace_body(lines, 0) == 2

    def test_no_opening_brace(self):
        lines = ["no braces here"]
        assert _track_brace_body(lines, 0) is None

    def test_unclosed_brace(self):
        lines = ["function foo() {", "  const x = 1;"]
        assert _track_brace_body(lines, 0) is None


# ── _find_function_start ─────────────────────────────────────


class TestFindFunctionStart:
    def test_function_declaration(self):
        assert _find_function_start("function foo() {", []) == "foo"

    def test_export_function(self):
        assert _find_function_start("export function bar() {", []) == "bar"

    def test_async_function(self):
        assert _find_function_start("async function baz() {", []) == "baz"

    def test_export_default_function(self):
        assert _find_function_start("export default function qux() {", []) == "qux"

    def test_arrow_function(self):
        result = _find_function_start("const myFn = () => {", [])
        assert result == "myFn"

    def test_async_arrow_function(self):
        result = _find_function_start("const myFn = async () => {", [])
        assert result == "myFn"

    def test_interface_skipped(self):
        assert _find_function_start("interface MyProps {", []) is None

    def test_type_skipped(self):
        assert _find_function_start("type MyType = {", []) is None

    def test_enum_skipped(self):
        assert _find_function_start("enum Status {", []) is None

    def test_class_skipped(self):
        assert _find_function_start("class Foo {", []) is None

    def test_plain_const_not_function(self):
        # A const that is not a function assignment
        result = _find_function_start("const x = 5;", [])
        assert result is None

    def test_const_function_keyword(self):
        result = _find_function_start("const handler = function() {", [])
        assert result == "handler"


# ── Multi-line smell helpers (direct invocation) ─────────────


def _make_counts():
    """Return a fresh smell_counts dict for testing."""
    from desloppify.lang.typescript.detectors.smells import TS_SMELL_CHECKS
    return {s["id"]: [] for s in TS_SMELL_CHECKS}


class TestDetectAsyncNoAwait:
    def test_flags_async_without_await(self):
        content = "async function fetchData() {\n  return 1;\n}\n"
        lines = content.splitlines()
        counts = _make_counts()
        _detect_async_no_await("test.ts", content, lines, counts)
        assert len(counts["async_no_await"]) == 1

    def test_skips_async_with_await(self):
        content = "async function fetchData() {\n  const d = await fetch('/');\n  return d;\n}\n"
        lines = content.splitlines()
        counts = _make_counts()
        _detect_async_no_await("test.ts", content, lines, counts)
        assert len(counts["async_no_await"]) == 0

    def test_arrow_async_without_await(self):
        content = "const fn = async () => {\n  return 42;\n}\n"
        lines = content.splitlines()
        counts = _make_counts()
        _detect_async_no_await("test.ts", content, lines, counts)
        assert len(counts["async_no_await"]) == 1


class TestDetectErrorNoThrow:
    def test_flags_error_without_throw(self):
        lines = [
            "function handle() {",
            "  console.error('bad');",
            "  doSomething();",
            "  doMore();",
            "  doEvenMore();",
            "}",
        ]
        counts = _make_counts()
        _detect_error_no_throw("test.ts", lines, counts)
        assert len(counts["console_error_no_throw"]) == 1

    def test_skips_when_throw_follows(self):
        lines = [
            "function handle() {",
            "  console.error('bad');",
            "  throw new Error('bad');",
            "}",
        ]
        counts = _make_counts()
        _detect_error_no_throw("test.ts", lines, counts)
        assert len(counts["console_error_no_throw"]) == 0


class TestDetectEmptyIfChains:
    def test_single_line_empty_if(self):
        lines = ["if (x) { }"]
        counts = _make_counts()
        _detect_empty_if_chains("test.ts", lines, counts)
        assert len(counts["empty_if_chain"]) == 1

    def test_multi_line_empty_if(self):
        lines = ["if (x) {", "}", ""]
        counts = _make_counts()
        _detect_empty_if_chains("test.ts", lines, counts)
        assert len(counts["empty_if_chain"]) == 1


class TestDetectDeadUseeffects:
    def test_empty_useeffect_body(self):
        lines = ["useEffect(() => {", "}, []);"]
        counts = _make_counts()
        _detect_dead_useeffects("test.ts", lines, counts)
        assert len(counts["dead_useeffect"]) == 1

    def test_comment_only_useeffect_body(self):
        lines = ["useEffect(() => {", "  // just a comment", "}, [dep]);"]
        counts = _make_counts()
        _detect_dead_useeffects("test.ts", lines, counts)
        assert len(counts["dead_useeffect"]) == 1

    def test_non_empty_useeffect_not_flagged(self):
        lines = ["useEffect(() => {", "  setCount(1);", "}, [dep]);"]
        counts = _make_counts()
        _detect_dead_useeffects("test.ts", lines, counts)
        assert len(counts["dead_useeffect"]) == 0


class TestDetectSwallowedErrors:
    def test_catch_only_console_log(self):
        content = "try { x(); } catch (e) { console.log(e); }"
        lines = content.splitlines()
        counts = _make_counts()
        _detect_swallowed_errors("test.ts", content, lines, counts)
        assert len(counts["swallowed_error"]) == 1

    def test_catch_with_rethrow_not_flagged(self):
        content = "try { x(); } catch (e) { console.error(e); throw e; }"
        lines = content.splitlines()
        counts = _make_counts()
        _detect_swallowed_errors("test.ts", content, lines, counts)
        assert len(counts["swallowed_error"]) == 0


class TestDetectWindowGlobals:
    def test_window_double_underscore(self):
        lines = ["window.__debug = true;"]
        line_state = {}
        counts = _make_counts()
        _detect_window_globals("test.ts", lines, line_state, counts)
        assert len(counts["window_global"]) == 1

    def test_window_as_any(self):
        lines = ["(window as any).__myVar = 'test';"]
        line_state = {}
        counts = _make_counts()
        _detect_window_globals("test.ts", lines, line_state, counts)
        assert len(counts["window_global"]) == 1

    def test_window_bracket_access(self):
        lines = ["window['__myVar'] = 'test';"]
        line_state = {}
        counts = _make_counts()
        _detect_window_globals("test.ts", lines, line_state, counts)
        assert len(counts["window_global"]) == 1

    def test_skips_lines_in_block_comment(self):
        lines = ["window.__debug = true;"]
        line_state = {0: "block_comment"}
        counts = _make_counts()
        _detect_window_globals("test.ts", lines, line_state, counts)
        assert len(counts["window_global"]) == 0


class TestDetectCatchReturnDefault:
    def test_catch_return_default_object(self):
        content = (
            "try { return getData(); }\n"
            "catch (e) {\n"
            "  return { success: false, data: null, error: null };\n"
            "}\n"
        )
        counts = _make_counts()
        _detect_catch_return_default("test.ts", content, counts)
        assert len(counts["catch_return_default"]) == 1

    def test_catch_return_single_field_not_flagged(self):
        content = (
            "try { return getData(); }\n"
            "catch (e) {\n"
            "  return { success: false };\n"
            "}\n"
        )
        counts = _make_counts()
        _detect_catch_return_default("test.ts", content, counts)
        assert len(counts["catch_return_default"]) == 0

    def test_catch_with_noop_callbacks(self):
        content = (
            "try { return getData(); }\n"
            "catch (e) {\n"
            "  return { onSuccess: () => {}, onError: () => {}, data: null };\n"
            "}\n"
        )
        counts = _make_counts()
        _detect_catch_return_default("test.ts", content, counts)
        assert len(counts["catch_return_default"]) == 1


class TestDetectMonsterFunctions:
    def test_flags_function_over_150_loc(self):
        body = "\n".join(f"  const x{i} = {i};" for i in range(160))
        lines = [f"function big() {{", *body.splitlines(), "}"]
        counts = _make_counts()
        _detect_monster_functions("test.ts", lines, counts)
        assert len(counts["monster_function"]) == 1

    def test_skips_short_function(self):
        lines = ["function small() {", "  return 1;", "}"]
        counts = _make_counts()
        _detect_monster_functions("test.ts", lines, counts)
        assert len(counts["monster_function"]) == 0


class TestDetectDeadFunctions:
    def test_empty_function(self):
        lines = ["function noop() {", "}"]
        counts = _make_counts()
        _detect_dead_functions("test.ts", lines, counts)
        assert len(counts["dead_function"]) == 1

    def test_return_null_function(self):
        lines = ["function stub() {", "  return null;", "}"]
        counts = _make_counts()
        _detect_dead_functions("test.ts", lines, counts)
        assert len(counts["dead_function"]) == 1

    def test_function_with_body_not_flagged(self):
        lines = ["function active() {", "  const x = calculate();", "  return x;", "}"]
        counts = _make_counts()
        _detect_dead_functions("test.ts", lines, counts)
        assert len(counts["dead_function"]) == 0

    def test_decorated_function_skipped(self):
        lines = ["@Controller()", "function handler() {", "}"]
        counts = _make_counts()
        _detect_dead_functions("test.ts", lines, counts)
        assert len(counts["dead_function"]) == 0
