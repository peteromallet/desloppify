"""Tests for C# parsing helpers: brace matching, expression end, param splitting."""

from __future__ import annotations

from desloppify.languages.csharp._parse_helpers import (
    extract_csharp_params,
    extract_csharp_return_annotation,
    find_expression_end,
    find_matching_brace,
    split_params,
)


class TestFindMatchingBrace:
    def test_simple(self):
        content = "{ return 1; }"
        assert find_matching_brace(content, 0) == 12

    def test_nested(self):
        content = "{ if (x) { return 1; } }"
        assert find_matching_brace(content, 0) == 23

    def test_deeply_nested(self):
        content = "{ { { } } }"
        assert find_matching_brace(content, 0) == 10

    def test_inner(self):
        """Issue matching brace starting at inner open brace."""
        content = "{ { inner } outer }"
        assert find_matching_brace(content, 2) == 10

    def test_skips_strings(self):
        """Braces inside strings are not counted."""
        content = '{ var s = "{ }"; }'
        assert find_matching_brace(content, 0) == 17

    def test_skips_single_quote_strings(self):
        content = "{ var c = '{'; }"
        assert find_matching_brace(content, 0) == 15

    def test_handles_escape_in_string(self):
        content = '{ var s = "\\"}"; }'
        assert find_matching_brace(content, 0) == 17

    def test_unmatched_returns_none(self):
        content = "{ if (x) {"
        assert find_matching_brace(content, 0) is None

    def test_empty_body(self):
        content = "{}"
        assert find_matching_brace(content, 0) == 1

    def test_skips_block_comments_with_unbalanced_braces(self):
        content = "{ /* } }} {{{ */ return 1; }"
        assert find_matching_brace(content, 0) == len(content) - 1

    def test_skips_line_comments_with_unbalanced_braces(self):
        content = "{ // } }}\n return 1; }"
        assert find_matching_brace(content, 0) == len(content) - 1


class TestFindExpressionEnd:
    def test_simple(self):
        content = "x + 1;"
        assert find_expression_end(content, 0) == 5

    def test_with_parens(self):
        content = "Math.Max(a, b);"
        assert find_expression_end(content, 0) == 14

    def test_nested_parens(self):
        content = "foo(bar(x), baz(y; z));"
        assert find_expression_end(content, 0) == 22

    def test_with_brackets(self):
        content = "arr[i + 1];"
        assert find_expression_end(content, 0) == 10

    def test_with_curly(self):
        """Curly braces (e.g., collection initializers) delay semicolon matching."""
        content = "new List<int> { 1, 2, 3 };"
        assert find_expression_end(content, 0) == 25

    def test_skips_string(self):
        content = 'var s = "a;b";'
        assert find_expression_end(content, 0) == 13

    def test_no_semicolon(self):
        content = "x + 1"
        assert find_expression_end(content, 0) is None

    def test_from_offset(self):
        content = "skip; target;"
        assert find_expression_end(content, 6) == 12


class TestSplitParams:
    def test_simple(self):
        assert split_params("int x, string y") == ["int x", " string y"]

    def test_empty(self):
        assert split_params("") == []

    def test_single(self):
        assert split_params("int x") == ["int x"]

    def test_generic_type(self):
        """Commas inside generic brackets are not split points."""
        result = split_params("Dictionary<string, int> map, int count")
        assert len(result) == 2
        assert "Dictionary<string, int> map" in result[0]

    def test_nested_generics(self):
        result = split_params("Func<int, List<string>> callback, bool flag")
        assert len(result) == 2

    def test_with_tuple(self):
        result = split_params("(int, string) pair, int x")
        assert len(result) == 2

    def test_with_array(self):
        result = split_params("int[] arr, string[,] matrix")
        assert len(result) == 2


class TestExtractCsharpParams:
    def test_basic(self):
        names = extract_csharp_params("int x, string y")
        assert names == ["x", "y"]

    def test_empty(self):
        assert extract_csharp_params("") == []

    def test_strips_modifiers(self):
        names = extract_csharp_params("ref int x, out string y, in float z")
        assert names == ["x", "y", "z"]

    def test_strips_this(self):
        names = extract_csharp_params("this string s, int n")
        assert names == ["s", "n"]

    def test_strips_params_keyword(self):
        names = extract_csharp_params("params string[] args")
        assert names == ["args"]

    def test_strips_default_values(self):
        names = extract_csharp_params("int x = 0, string name = \"hello\"")
        assert names == ["x", "name"]

    def test_handles_at_prefix(self):
        """C# allows @-prefixed identifiers to use reserved words as names."""
        names = extract_csharp_params("int @class, string @event")
        assert names == ["class", "event"]

    def test_generic_type(self):
        names = extract_csharp_params("List<int> items, Dictionary<string, int> counts")
        assert names == ["items", "counts"]

    def test_ignores_non_identifier_tokens(self):
        """Tokens that aren't valid identifiers are skipped."""
        names = extract_csharp_params("int 123")
        assert names == []

    def test_with_required_modifier(self):
        names = extract_csharp_params("required string name")
        assert names == ["name"]


class TestExtractCsharpReturnAnnotation:
    def test_basic(self):
        result = extract_csharp_return_annotation("public int MyMethod(", "MyMethod")
        assert result == "int"

    def test_void(self):
        result = extract_csharp_return_annotation("public void Process(", "Process")
        assert result == "void"

    def test_static(self):
        result = extract_csharp_return_annotation("public static string GetName(", "GetName")
        assert result == "string"

    def test_generic(self):
        result = extract_csharp_return_annotation(
            "public List<int> GetItems(", "GetItems"
        )
        assert result == "List<int>"

    def test_async(self):
        result = extract_csharp_return_annotation(
            "public async Task<bool> ValidateAsync(", "ValidateAsync"
        )
        assert result == "Task<bool>"

    def test_no_match(self):
        result = extract_csharp_return_annotation("some random text", "NonExistent")
        assert result is None

    def test_no_prefix(self):
        """If there's nothing before the method name, return None."""
        result = extract_csharp_return_annotation("MyMethod(", "MyMethod")
        assert result is None

    def test_only_modifiers(self):
        """If prefix is all modifiers (no return type), return None."""
        result = extract_csharp_return_annotation("public static MyMethod(", "MyMethod")
        assert result is None

    def test_override(self):
        result = extract_csharp_return_annotation(
            "protected override bool Equals(", "Equals"
        )
        assert result == "bool"

    def test_multiple_occurrences_uses_last(self):
        """rfind ensures the last occurrence of 'Name(' is used."""
        result = extract_csharp_return_annotation(
            "int Name(int x) { } string Name(", "Name"
        )
        assert result == "string"
