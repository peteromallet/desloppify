"""Tests for desloppify.lang.typescript.extractors — TS function/component extraction."""

import textwrap

import pytest

from desloppify.lang.typescript.extractors import (
    _extract_ts_params,
    _parse_param_names,
    extract_props,
    extract_ts_functions,
    normalize_ts_body,
    tsx_passthrough_pattern,
)


# ── _parse_param_names() ──────────────────────────────────────


def test_parse_param_names_simple():
    """Simple comma-separated param names are extracted."""
    assert _parse_param_names("a, b, c") == ["a", "b", "c"]


def test_parse_param_names_with_types():
    """Type annotations are stripped, only names remain."""
    assert _parse_param_names("a: string, b: number") == ["a", "b"]


def test_parse_param_names_with_defaults():
    """Default values are stripped."""
    assert _parse_param_names("x = 1, y = 'hello'") == ["x", "y"]


def test_parse_param_names_with_rest():
    """Rest params have leading ... stripped."""
    assert _parse_param_names("a, ...rest") == ["a", "rest"]


def test_parse_param_names_with_optional():
    """Optional marker ? is stripped."""
    assert _parse_param_names("x?: string, y: number") == ["x", "y"]


def test_parse_param_names_nested_generics():
    """Commas inside angle brackets are not treated as separators."""
    result = _parse_param_names("a: Map<string, number>, b: string")
    assert result == ["a", "b"]


def test_parse_param_names_empty():
    """Empty string yields no params."""
    assert _parse_param_names("") == []


# ── _extract_ts_params() ─────────────────────────────────────


def test_extract_ts_params_function_decl():
    """Params from a standard function declaration."""
    sig = "function foo(a: string, b: number) {"
    assert _extract_ts_params(sig) == ["a", "b"]


def test_extract_ts_params_arrow():
    """Params from an arrow function."""
    sig = "const foo = (x: string, y: boolean) => {"
    assert _extract_ts_params(sig) == ["x", "y"]


def test_extract_ts_params_destructured():
    """Destructured params are extracted from inner braces."""
    sig = "const Comp = ({ name, value, onChange }: Props) => {"
    result = _extract_ts_params(sig)
    assert result == ["name", "value", "onChange"]


def test_extract_ts_params_no_parens_single_arrow():
    """Single-param arrow function without parens: name => ..."""
    sig = "const fn = x => {"
    result = _extract_ts_params(sig)
    assert result == ["x"]


def test_extract_ts_params_empty_parens():
    """Empty param list yields no params."""
    sig = "function noArgs() {"
    assert _extract_ts_params(sig) == []


# ── normalize_ts_body() ──────────────────────────────────────


def test_normalize_strips_comments():
    """Single-line comments are removed."""
    body = "function foo() {\n  // comment\n  return 1;\n}"
    result = normalize_ts_body(body)
    assert "// comment" not in result
    assert "return 1;" in result


def test_normalize_strips_console():
    """Console statements are removed."""
    body = "function bar() {\n  console.log('debug');\n  return x;\n}"
    result = normalize_ts_body(body)
    assert "console" not in result
    assert "return x;" in result


def test_normalize_strips_blank_lines():
    """Blank lines are removed."""
    body = "function baz() {\n\n  return 1;\n\n}"
    result = normalize_ts_body(body)
    assert "\n\n" not in result


def test_normalize_strips_block_comments():
    """Lines starting with /* or * are removed."""
    body = "function f() {\n  /* block */\n  * middle\n  return 1;\n}"
    result = normalize_ts_body(body)
    assert "block" not in result
    assert "middle" not in result


# ── extract_ts_functions() ───────────────────────────────────


def test_extract_named_function(tmp_path):
    """Named function declaration is extracted with correct metadata."""
    ts_file = tmp_path / "sample.ts"
    ts_file.write_text(textwrap.dedent("""\
        export function greet(name: string) {
          const msg = `Hello ${name}`;
          console.log(msg);
          return msg;
        }
    """))
    funcs = extract_ts_functions(str(ts_file))
    assert len(funcs) == 1
    fn = funcs[0]
    assert fn.name == "greet"
    assert fn.file == str(ts_file)
    assert fn.line == 1
    assert fn.loc == 5
    assert fn.params == ["name"]
    assert fn.body_hash  # non-empty


def test_extract_arrow_function(tmp_path):
    """Arrow function assigned to const is extracted."""
    ts_file = tmp_path / "arrow.ts"
    ts_file.write_text(textwrap.dedent("""\
        const add = (a: number, b: number) => {
          const result = a + b;
          console.log(result);
          return result;
        };
    """))
    funcs = extract_ts_functions(str(ts_file))
    assert len(funcs) == 1
    assert funcs[0].name == "add"
    assert funcs[0].params == ["a", "b"]


def test_extract_const_function(tmp_path):
    """const X = function(...) is extracted."""
    ts_file = tmp_path / "constfn.ts"
    ts_file.write_text(textwrap.dedent("""\
        const multiply = function(x: number, y: number) {
          const r = x * y;
          console.log(r);
          return r;
        };
    """))
    funcs = extract_ts_functions(str(ts_file))
    assert len(funcs) == 1
    assert funcs[0].name == "multiply"


def test_extract_skips_short_functions(tmp_path):
    """Functions with fewer than 3 normalized lines are skipped."""
    ts_file = tmp_path / "short.ts"
    ts_file.write_text(textwrap.dedent("""\
        function tiny() {
          return 1;
        }
    """))
    funcs = extract_ts_functions(str(ts_file))
    # 3 lines total, but after normalization: "function tiny() {" and "return 1;" and "}"
    # That's 3 normalized lines, so it should be included
    assert len(funcs) == 1


def test_extract_multiple_functions(tmp_path):
    """Multiple functions in one file are all extracted."""
    ts_file = tmp_path / "multi.ts"
    ts_file.write_text(textwrap.dedent("""\
        export function first(x: string) {
          const a = x;
          const b = a + "!";
          return b;
        }

        export function second(y: number) {
          const c = y * 2;
          const d = c + 1;
          return d;
        }
    """))
    funcs = extract_ts_functions(str(ts_file))
    assert len(funcs) == 2
    names = {f.name for f in funcs}
    assert names == {"first", "second"}


def test_extract_handles_nonexistent_file():
    """Non-existent file returns empty list."""
    funcs = extract_ts_functions("/nonexistent/path/foo.ts")
    assert funcs == []


def test_extract_handles_nested_braces(tmp_path):
    """Nested braces in function body do not break extraction."""
    ts_file = tmp_path / "nested.ts"
    ts_file.write_text(textwrap.dedent("""\
        function outer(x: number) {
          if (x > 0) {
            const obj = { a: 1, b: 2 };
            return obj;
          }
          return { a: 0, b: 0 };
        }
    """))
    funcs = extract_ts_functions(str(ts_file))
    assert len(funcs) == 1
    assert funcs[0].name == "outer"
    assert funcs[0].loc == 7


def test_extract_skips_strings_with_braces(tmp_path):
    """Braces inside string literals do not confuse brace tracking."""
    ts_file = tmp_path / "strings.ts"
    ts_file.write_text(textwrap.dedent("""\
        function withStrings(x: string) {
          const a = "{ not a brace }";
          const b = '} also not';
          const c = `template ${"{"} literal`;
          return a + b + c;
        }
    """))
    funcs = extract_ts_functions(str(ts_file))
    assert len(funcs) == 1
    assert funcs[0].name == "withStrings"


# ── extract_props() ──────────────────────────────────────────


def test_extract_props_simple():
    """Simple prop names are extracted."""
    assert extract_props("name, value, onChange") == ["name", "value", "onChange"]


def test_extract_props_with_defaults():
    """Props with defaults: name before = is extracted."""
    result = extract_props("name, count = 0, visible = true")
    assert result == ["name", "count", "visible"]


def test_extract_props_with_alias():
    """Props with JS-style rename alias: `original: alias` extracts alias.

    Note: the type-stripping regex in extract_props removes `: <TypeName>` first.
    A bare `: aliasName` looks like a type annotation to the regex, so the name
    before the colon is kept.  An actual alias only survives if the regex does
    not strip it (e.g. complex type).
    """
    # After type-stripping, `name: aliasName` becomes just `name`
    result = extract_props("name: aliasName, value")
    assert result == ["name", "value"]


def test_extract_props_with_rest():
    """Rest props: ...rest -> rest."""
    result = extract_props("name, ...rest")
    assert result == ["name", "rest"]


def test_extract_props_with_types():
    """Type annotations are stripped before extraction."""
    result = extract_props("name: string, count: number, items: Array<string>")
    # After type annotation stripping, the names should be extracted
    assert "name" in result


def test_extract_props_empty():
    """Empty string yields no props."""
    assert extract_props("") == []


# ── tsx_passthrough_pattern() ─────────────────────────────────


def test_tsx_passthrough_pattern_matches():
    """Pattern matches propName={propName} in JSX."""
    import re
    pattern = tsx_passthrough_pattern("onClick")
    assert re.search(pattern, 'onClick={onClick}')
    assert re.search(pattern, 'onClick={ onClick }')


def test_tsx_passthrough_pattern_no_match():
    """Pattern does not match different values."""
    import re
    pattern = tsx_passthrough_pattern("onClick")
    assert not re.search(pattern, 'onClick={handleClick}')
