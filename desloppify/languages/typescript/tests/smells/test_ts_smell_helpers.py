"""Tests for desloppify.languages.typescript.detectors.smells.helpers."""

from desloppify.languages.typescript.detectors.smells import TS_SMELL_CHECKS
from desloppify.languages.typescript.detectors.smells.detector_core import (
    _find_function_start,
)
from desloppify.languages.typescript.detectors.smells.detector_flow import (
    _detect_async_no_await,
    _detect_empty_if_chains,
    _detect_error_no_throw,
    _detect_monster_functions,
    _detect_stub_functions,
)
from desloppify.languages.typescript.detectors.smells.detector_safety import (
    _detect_catch_return_default,
    _detect_dead_useeffects,
    _detect_swallowed_errors,
    _detect_window_globals,
)
from desloppify.languages.typescript.detectors.smells.helpers import (
    _code_text,
    _content_line_info,
    _extract_block_body,
    _FileContext,
    _strip_ts_comments,
    _track_brace_body,
    _ts_match_is_in_string,
)


def _ctx(content: str, filepath: str = "test.ts") -> _FileContext:
    """Build a _FileContext from content string for testing."""
    lines = content.splitlines()
    return _FileContext(filepath=filepath, content=content, lines=lines, line_state={})


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


# ── _code_text ───────────────────────────────────────────────


class TestCodeText:
    def test_preserves_plain_code(self):
        assert _code_text("const x = 1;") == "const x = 1;"

    def test_blanks_double_quoted_string(self):
        result = _code_text('const s = "hello";')
        # Opening quote + contents blanked; closing quote preserved by scan_code
        assert "hello" not in result
        assert len(result) == len('const s = "hello";')

    def test_blanks_single_quoted_string(self):
        result = _code_text("const s = 'hello';")
        assert "hello" not in result
        assert result.startswith("const s = ")

    def test_blanks_template_literal(self):
        result = _code_text("const s = `hello`;")
        assert "hello" not in result

    def test_blanks_line_comment(self):
        result = _code_text("code // comment")
        assert "comment" not in result
        assert result.startswith("code ")
        assert len(result) == len("code // comment")

    def test_blanks_line_comment_multiline(self):
        result = _code_text("code // comment\nnext line")
        assert "next line" in result
        assert "comment" not in result

    def test_preserves_positions(self):
        text = 'x = "str"; y = 1;'
        result = _code_text(text)
        assert len(result) == len(text)
        assert result[0] == "x"
        assert result[-1] == ";"

    def test_division_not_treated_as_comment(self):
        result = _code_text("a / b / c")
        assert result == "a / b / c"

    def test_await_in_string_blanked(self):
        result = _code_text("const s = 'await something';")
        assert "await" not in result

    def test_await_in_comment_blanked(self):
        result = _code_text("return 1; // await fetch")
        assert "await" not in result
        assert result.startswith("return 1;")


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


# ── _extract_block_body ──────────────────────────────────────


class TestExtractBlockBody:
    def test_simple_block(self):
        content = "if (x) { return 1; }"
        brace_pos = content.index("{")
        assert _extract_block_body(content, brace_pos) == " return 1; "

    def test_nested_braces(self):
        content = "outer { inner { x } y }"
        brace_pos = content.index("{")
        assert _extract_block_body(content, brace_pos) == " inner { x } y "

    def test_unclosed_returns_none(self):
        content = "if (x) { return 1;"
        brace_pos = content.index("{")
        assert _extract_block_body(content, brace_pos) is None

    def test_string_braces_ignored(self):
        content = "fn() { const s = '{}'; }"
        brace_pos = content.index("{")
        assert _extract_block_body(content, brace_pos) == " const s = '{}'; "


# ── _content_line_info ───────────────────────────────────────


class TestContentLineInfo:
    def test_first_line(self):
        content = "catch (e) { console.log(e); }"
        line_no, snippet = _content_line_info(content, 0)
        assert line_no == 1
        assert "catch" in snippet

    def test_multiline(self):
        content = "line one\nline two\nline three"
        line_no, snippet = _content_line_info(content, content.index("two"))
        assert line_no == 2
        assert snippet == "line two"

    def test_snippet_truncated(self):
        long_line = "x" * 200
        content = f"first\n{long_line}\nthird"
        _, snippet = _content_line_info(content, content.index(long_line))
        assert len(snippet) == 100


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
    return {s["id"]: [] for s in TS_SMELL_CHECKS}


class TestDetectAsyncNoAwait:
    def test_flags_async_without_await(self):
        content = "async function fetchData() {\n  return 1;\n}\n"
        counts = _make_counts()
        _detect_async_no_await(_ctx(content), counts)
        assert len(counts["async_no_await"]) == 1

    def test_skips_async_with_await(self):
        content = "async function fetchData() {\n  const d = await fetch('/');\n  return d;\n}\n"
        counts = _make_counts()
        _detect_async_no_await(_ctx(content), counts)
        assert len(counts["async_no_await"]) == 0

    def test_skips_multiline_async_with_default_object_and_await(self):
        content = (
            "export async function runOperation(\n"
            "  operationId: string,\n"
            "  input: Record<string, unknown>,\n"
            "  opts: RunOpts = {},\n"
            "): Promise<Envelope> {\n"
            "  const registry = await loadRegistry();\n"
            "  return registry.get(operationId);\n"
            "}\n"
        )
        counts = _make_counts()
        _detect_async_no_await(_ctx(content), counts)
        assert len(counts["async_no_await"]) == 0

    def test_skips_multiline_async_destructured_param_with_await(self):
        content = (
            "async function runSinglePage(\n"
            "  {\n"
            "    cmd,\n"
            "    warnings = [],\n"
            "  }: ExecutableOperationRun,\n"
            "  makeRequest: RequestFactory,\n"
            "): Promise<{ env: Envelope }> {\n"
            "  const req = await makeRequest(cmd);\n"
            "  return { env: req };\n"
            "}\n"
        )
        counts = _make_counts()
        _detect_async_no_await(_ctx(content), counts)
        assert len(counts["async_no_await"]) == 0

    def test_arrow_async_without_await(self):
        content = "const fn = async () => {\n  return 42;\n}\n"
        counts = _make_counts()
        _detect_async_no_await(_ctx(content), counts)
        assert len(counts["async_no_await"]) == 1

    def test_await_in_comment_still_flagged(self):
        """'await' inside a comment should not count — function is still flagged."""
        content = "async function fetchData() {\n  // await fetch('/');\n  return 1;\n}\n"
        counts = _make_counts()
        _detect_async_no_await(_ctx(content), counts)
        assert len(counts["async_no_await"]) == 1

    def test_await_in_string_still_flagged(self):
        """'await' inside a string literal should not count — function is still flagged."""
        content = "async function fetchData() {\n  const s = 'await something';\n  return s;\n}\n"
        counts = _make_counts()
        _detect_async_no_await(_ctx(content), counts)
        assert len(counts["async_no_await"]) == 1

    def test_await_beyond_line_200_detected(self):
        """Await past old 200-line cap should still be detected (limit is now 2000)."""
        filler = "\n".join(f"  const x{i} = {i};" for i in range(250))
        content = f"async function big() {{\n{filler}\n  const d = await fetch('/');\n  return d;\n}}\n"
        counts = _make_counts()
        _detect_async_no_await(_ctx(content), counts)
        assert len(counts["async_no_await"]) == 0


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
        _detect_error_no_throw(_ctx("\n".join(lines)), counts)
        assert len(counts["console_error_no_throw"]) == 1

    def test_skips_when_throw_follows(self):
        lines = [
            "function handle() {",
            "  console.error('bad');",
            "  throw new Error('bad');",
            "}",
        ]
        counts = _make_counts()
        _detect_error_no_throw(_ctx("\n".join(lines)), counts)
        assert len(counts["console_error_no_throw"]) == 0

    def test_skips_logger_files(self):
        """Logger utility files should be entirely skipped."""
        lines = [
            "function logError(msg) {",
            "  console.error(msg);",
            "  doSomething();",
            "  doMore();",
            "  doEvenMore();",
            "}",
        ]
        counts = _make_counts()
        _detect_error_no_throw(_ctx("\n".join(lines), "src/utils/logger.ts"), counts)
        assert len(counts["console_error_no_throw"]) == 0

    def test_skips_error_handler_files(self):
        """Error handler utility files should be entirely skipped."""
        lines = [
            "function handleError(err) {",
            "  console.error(err);",
            "  doSomething();",
            "  doMore();",
            "  doEvenMore();",
            "}",
        ]
        counts = _make_counts()
        _detect_error_no_throw(_ctx("\n".join(lines), "src/ErrorHandler.ts"), counts)
        assert len(counts["console_error_no_throw"]) == 0

    def test_skips_component_did_catch(self):
        """console.error inside componentDidCatch context should be skipped."""
        lines = [
            "class ErrorBoundary extends React.Component {",
            "  componentDidCatch(error, info) {",
            "    // Log error to service",
            "    console.error(error);",
            "    doSomething();",
            "    doMore();",
            "    doEvenMore();",
            "  }",
            "}",
        ]
        counts = _make_counts()
        _detect_error_no_throw(_ctx("\n".join(lines)), counts)
        assert len(counts["console_error_no_throw"]) == 0

    def test_skips_dev_only_block(self):
        """console.error inside dev-only block should be skipped."""
        lines = [
            "function handle() {",
            "  if (import.meta.env.DEV) {",
            "    console.error('debug info');",
            "    doSomething();",
            "    doMore();",
            "    doEvenMore();",
            "  }",
            "}",
        ]
        counts = _make_counts()
        _detect_error_no_throw(_ctx("\n".join(lines)), counts)
        assert len(counts["console_error_no_throw"]) == 0

    def test_toast_counts_as_handled(self):
        """toast() in following lines should count as handled."""
        lines = [
            "function handle() {",
            "  console.error('bad');",
            "  toast('Something went wrong');",
            "}",
        ]
        counts = _make_counts()
        _detect_error_no_throw(_ctx("\n".join(lines)), counts)
        assert len(counts["console_error_no_throw"]) == 0


class TestDetectEmptyIfChains:
    def test_single_line_empty_if(self):
        counts = _make_counts()
        _detect_empty_if_chains(_ctx("if (x) { }"), counts)
        assert len(counts["empty_if_chain"]) == 1

    def test_multi_line_empty_if(self):
        counts = _make_counts()
        _detect_empty_if_chains(_ctx("if (x) {\n}\n"), counts)
        assert len(counts["empty_if_chain"]) == 1


class TestDetectDeadUseeffects:
    def test_empty_useeffect_body(self):
        content = "useEffect(() => {\n}, []);"
        counts = _make_counts()
        _detect_dead_useeffects(_ctx(content), counts)
        assert len(counts["dead_useeffect"]) == 1

    def test_comment_only_useeffect_body(self):
        content = "useEffect(() => {\n  // just a comment\n}, [dep]);"
        counts = _make_counts()
        _detect_dead_useeffects(_ctx(content), counts)
        assert len(counts["dead_useeffect"]) == 1

    def test_non_empty_useeffect_not_flagged(self):
        content = "useEffect(() => {\n  setCount(1);\n}, [dep]);"
        counts = _make_counts()
        _detect_dead_useeffects(_ctx(content), counts)
        assert len(counts["dead_useeffect"]) == 0


class TestDetectSwallowedErrors:
    def test_catch_only_console_log(self):
        content = "try { x(); } catch (e) { console.log(e); }"
        counts = _make_counts()
        _detect_swallowed_errors(_ctx(content), counts)
        assert len(counts["swallowed_error"]) == 1

    def test_catch_with_rethrow_not_flagged(self):
        content = "try { x(); } catch (e) { console.error(e); throw e; }"
        counts = _make_counts()
        _detect_swallowed_errors(_ctx(content), counts)
        assert len(counts["swallowed_error"]) == 0


class TestDetectWindowGlobals:
    def test_window_double_underscore(self):
        counts = _make_counts()
        _detect_window_globals(_ctx("window.__debug = true;"), counts)
        assert len(counts["window_global"]) == 1

    def test_window_as_any(self):
        counts = _make_counts()
        _detect_window_globals(_ctx("(window as any).__myVar = 'test';"), counts)
        assert len(counts["window_global"]) == 1

    def test_window_bracket_access(self):
        counts = _make_counts()
        _detect_window_globals(_ctx("window['__myVar'] = 'test';"), counts)
        assert len(counts["window_global"]) == 1

    def test_skips_lines_in_block_comment(self):
        content = "window.__debug = true;"
        ctx = _FileContext(
            filepath="test.ts",
            content=content,
            lines=content.splitlines(),
            line_state={0: "block_comment"},
        )
        counts = _make_counts()
        _detect_window_globals(ctx, counts)
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
        _detect_catch_return_default(_ctx(content), counts)
        assert len(counts["catch_return_default"]) == 1

    def test_catch_return_single_field_not_flagged(self):
        content = (
            "try { return getData(); }\ncatch (e) {\n  return { success: false };\n}\n"
        )
        counts = _make_counts()
        _detect_catch_return_default(_ctx(content), counts)
        assert len(counts["catch_return_default"]) == 0

    def test_catch_with_noop_callbacks(self):
        content = (
            "try { return getData(); }\n"
            "catch (e) {\n"
            "  return { onSuccess: () => {}, onError: () => {}, data: null };\n"
            "}\n"
        )
        counts = _make_counts()
        _detect_catch_return_default(_ctx(content), counts)
        assert len(counts["catch_return_default"]) == 1


class TestDetectMonsterFunctions:
    def test_flags_function_over_150_loc(self):
        body = "\n".join(f"  const x{i} = {i};" for i in range(160))
        content = f"function big() {{\n{body}\n}}"
        counts = _make_counts()
        _detect_monster_functions(_ctx(content), counts)
        assert len(counts["monster_function"]) == 1

    def test_skips_short_function(self):
        content = "function small() {\n  return 1;\n}"
        counts = _make_counts()
        _detect_monster_functions(_ctx(content), counts)
        assert len(counts["monster_function"]) == 0


class TestDetectStubFunctions:
    def test_empty_function(self):
        content = "function noop() {\n}"
        counts = _make_counts()
        _detect_stub_functions(_ctx(content), counts)
        assert len(counts["stub_function"]) == 1

    def test_return_null_function(self):
        content = "function stub() {\n  return null;\n}"
        counts = _make_counts()
        _detect_stub_functions(_ctx(content), counts)
        assert len(counts["stub_function"]) == 1

    def test_function_with_body_not_flagged(self):
        content = "function active() {\n  const x = calculate();\n  return x;\n}"
        counts = _make_counts()
        _detect_stub_functions(_ctx(content), counts)
        assert len(counts["stub_function"]) == 0

    def test_decorated_function_skipped(self):
        content = "@Controller()\nfunction handler() {\n}"
        counts = _make_counts()
        _detect_stub_functions(_ctx(content), counts)
        assert len(counts["stub_function"]) == 0
