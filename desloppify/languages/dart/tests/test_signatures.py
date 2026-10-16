"""Signature analysis must consume declarations, not calls with callbacks."""

from __future__ import annotations

import sys
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.detectors.signature import detect_signature_variance
from desloppify.languages._framework.base import shared_phases_review
from desloppify.languages._framework.base.types import SignatureExtractionUnavailable
from desloppify.languages._framework.runtime_support.runtime import make_lang_run
from desloppify.languages.dart import DartConfig, signatures
from desloppify.languages.dart.extractors import extract_functions


@pytest.fixture
def dart_grammar():
    try:
        return signatures._get_parser()
    except SignatureExtractionUnavailable as error:
        pytest.skip(str(error))


def _write(tmp_path, text, name="example.dart"):
    source = tmp_path / name
    source.write_text(text)
    return source


def test_callsite_variance_is_removed_but_real_declarations_remain(
    tmp_path, dart_grammar
):
    _write(
        tmp_path,
        """
void test(String description, void Function() body) => body();
class MaterialApp {
  MaterialApp({required String title, required Object Function(Object) builder});
}
""",
        "support.dart",
    )
    for index, word in enumerate(("alpha", "beta", "gamma")):
        parameters = "int value" if index != 1 else "int value, int adjustment"
        expression = "value" if index != 1 else "value + adjustment"
        _write(
            tmp_path,
            f"""
import 'support.dart';
void main() {{
  const title{word.title()} = 'Example';
  test('scenario {word}, valid', () {{ print('done'); }});
  MaterialApp(title: title{word.title()}, builder: (context) {{ return context; }});
}}
int calculate({parameters}) {{ return {expression}; }}
""",
            f"example_{index}.dart",
        )
    legacy = extract_functions(tmp_path)
    legacy_snapshot = [asdict(fn) for fn in legacy]
    legacy_entries, _ = detect_signature_variance(legacy)
    assert {entry["name"] for entry in legacy_entries} == {
        "test",
        "MaterialApp",
        "calculate",
    }

    declarations = signatures.extract_signature_functions(tmp_path)
    entries, _ = detect_signature_variance(declarations)

    assert [entry["name"] for entry in entries] == ["calculate"]
    assert [fn.name for fn in declarations].count("test") == 1
    assert [fn.name for fn in declarations].count("MaterialApp") == 0
    assert [asdict(fn) for fn in extract_functions(tmp_path)] == legacy_snapshot
    issues, potential = shared_phases_review.phase_signature(
        tmp_path, make_lang_run(DartConfig())
    )
    assert len(issues) == 1
    assert (
        issues[0]["summary"] == "'calculate' has 2 different signatures across 3 files"
    )
    assert potential == {"signature": 1}


def test_formal_parameters_preserve_nested_defaults_and_last_named_parameter(
    tmp_path, dart_grammar
):
    source = _write(
        tmp_path,
        """
void optional([Map<String, List<int>> values = const {'x': [1, 2]}, int? last]) {}
void named({required String first, int? last}) {}
void defaults({String label = 'one,two', List<int> values = const [1, 2],
  Map<String, int> lookup = const {'a': 1, 'b': 2}}) {}
void callbacks(void Function(int, String) callback,
  int Function(Map<String, List<int>>) transform) {}
void legacy(void callback(int inner, String another)) {}
int generic<T>(T value, {T? fallback}) => 1;
""",
    )
    assert not dart_grammar.parse(source.read_bytes()).root_node.has_error

    functions = {fn.name: fn for fn in signatures.extract_signature_functions(tmp_path)}

    assert {name: fn.params for name, fn in functions.items()} == {
        "optional": ["values", "last"],
        "named": ["first", "last"],
        "defaults": ["label", "values", "lookup"],
        "callbacks": ["callback", "transform"],
        "legacy": ["callback"],
        "generic": ["value", "fallback"],
    }


def test_methods_local_declarations_and_constructor_parameters(tmp_path, dart_grammar):
    source = _write(
        tmp_path,
        """
class Base { Base({Object? key}); }
class Box extends Base {
  Box(this.value, {super.key}) { print(value); }
  Box.named(this.value) : assert(value >= 0) { print(value); }
  factory Box.create(int value) => Box(value);
  final int value;
  static Future<void> work({required int input, int? last}) async {
    int local(int first, {int? last}) => first;
    invoke((int nested) { return nested; });
  }
  Iterable<int> generate(int count) sync* { yield count; }
  Stream<int> stream(int count) async* { yield count; }
  set selected(int next) { print(next); }
}
""",
    )
    assert not dart_grammar.parse(source.read_bytes()).root_node.has_error

    functions = signatures.extract_signature_functions(tmp_path)

    assert [(fn.name, fn.params) for fn in functions] == [
        ("Box", ["value", "key"]),
        ("Box.named", ["value"]),
        ("Box.create", ["value"]),
        ("work", ["input", "last"]),
        ("local", ["first", "last"]),
        ("generate", ["count"]),
        ("stream", ["count"]),
        ("selected", ["next"]),
    ]
    assert "invoke((int nested)" in next(
        fn.body for fn in functions if fn.name == "work"
    )


def test_comments_strings_and_callback_arguments_are_not_declarations(
    tmp_path, dart_grammar
):
    _write(
        tmp_path,
        """
const example = '''
void fabricated(int value) { print(value); }
''';
// void commented(int value) { print(value); }
void actual(int value) /* a brace } in a comment */ {
  call(value, () => value);
  call(value, (int arg) { return arg; });
}
""",
    )

    functions = signatures.extract_signature_functions(tmp_path)

    assert [(fn.name, fn.params) for fn in functions] == [("actual", ["value"])]


def test_unavailable_parser_is_explicit_and_does_not_use_general_extraction(
    monkeypatch, tmp_path
):
    def missing_parser():
        raise SignatureExtractionUnavailable("Dart grammar unavailable")

    monkeypatch.setattr(signatures, "_get_parser", missing_parser)
    config = DartConfig()
    general_calls = []
    config.extract_functions = lambda path: general_calls.append(path)
    lang = make_lang_run(config)

    assert shared_phases_review.phase_signature(tmp_path, lang) == ([], {})
    assert general_calls == []
    assert lang.detector_coverage["signature"]["status"] == "reduced"
    assert lang.detector_coverage["signature"]["confidence"] == 0.0
    assert lang.detector_coverage["signature"]["reason"] == "Dart grammar unavailable"


def test_missing_optional_parser_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)

    with pytest.raises(SignatureExtractionUnavailable) as caught:
        signatures._get_parser()

    assert isinstance(caught.value.__cause__, ImportError)


def test_signature_hook_does_not_populate_or_replace_general_function_cache(
    monkeypatch, tmp_path
):
    general = [FunctionInfo("call", "one.dart", 1, 4, 4, "call(() {});")]
    declarations = [FunctionInfo("declared", "one.dart", 1, 4, 4, "void declared() {}")]
    seen = []
    lang = SimpleNamespace(
        extract_functions=lambda _path: general,
        extract_signature_functions=lambda _path: declarations,
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.signature.detect_signature_variance",
        lambda functions, **_kwargs: (seen.append(functions) or [], len(functions)),
    )

    assert shared_phases_review._resolve_review_functions(tmp_path, lang) is general
    shared_phases_review.phase_signature(tmp_path, lang)

    assert seen == [declarations]
    assert shared_phases_review._resolve_review_functions(tmp_path, lang) is general
