"""Dart import usage requires semantic analysis, independently of graph parsing."""

from __future__ import annotations

import pytest

from desloppify.languages._framework.treesitter.analysis.extractors import _get_parser
from desloppify.languages._framework.treesitter.analysis.unused_imports import (
    detect_unused_imports,
)
from desloppify.languages._framework.treesitter.imports.graph import ts_build_dep_graph
from desloppify.languages._framework.treesitter.specs.compiled import DART_SPEC


@pytest.mark.parametrize(
    "source",
    [
        "import 'dart:math' as math;\nint clamp(int x) => math.max(x, 0);\n",
        "import 'dart:math' as math;\nconst answer = 42;\n",
        "import 'models.dart';\nCharacter create() => Character();\n",
        "import 'extensions.dart';\nint count(String s) => s.customLength();\n",
        "import 'extensions.dart' as ext;\nint count(String s) => s.customLength();\n",
        "import 'extensions.dart' show StringTools;\n"
        "int count(String s) => s.customLength();\n",
        "import 'extensions.dart' as ext show StringTools;\n"
        "int count(String s) => s.customLength();\n",
        "import 'models.dart' hide Internal;\nCharacter create() => Character();\n",
        "import 'loader.dart' deferred as loader;\n"
        "Future<void> load() => loader.loadLibrary();\n",
        "import 'platform.dart' if (dart.library.io) 'platform_io.dart' as platform;\n"
        "Object create() => platform.create();\n",
    ],
    ids=[
        "used-prefix",
        "unused-prefix-left-to-native-analyzer",
        "unprefixed-namespace",
        "implicit-extension",
        "prefixed-implicit-extension",
        "show-extension",
        "prefixed-show-extension",
        "hide",
        "deferred-prefix",
        "conditional-prefix",
    ],
)
def test_dart_unused_imports_require_native_semantic_analysis(tmp_path, source) -> None:
    parser, _language = _get_parser(DART_SPEC.grammar)
    assert not parser.parse(source.encode()).root_node.has_error
    path = tmp_path / "consumer.dart"
    path.write_text(source)
    (tmp_path / "extensions.dart").write_text(
        "extension StringTools on String { int customLength() => length; }\n"
    )

    assert detect_unused_imports([str(path)], DART_SPEC) == []


@pytest.mark.parametrize("part_name", ["ordinary_part.dart", "consumer.g.dart"])
def test_dart_parts_do_not_change_semantic_import_limitation(
    tmp_path, part_name
) -> None:
    path = tmp_path / "consumer.dart"
    path.write_text(f"import 'dart:math' as math;\npart '{part_name}';\n")
    (tmp_path / part_name).write_text(
        "part of 'consumer.dart';\nint clamp(int x) => math.max(x, 0);\n"
    )

    assert detect_unused_imports([str(path)], DART_SPEC) == []


def test_import_query_keeps_uri_capture_for_dependency_graph(tmp_path) -> None:
    lib = tmp_path / "lib"
    main = lib / "main.dart"
    ordinary = lib / "ordinary.dart"
    aliased = lib / "aliased.dart"
    lib.mkdir()
    main.write_text("import 'ordinary.dart';\nimport 'aliased.dart' as models;\n")
    ordinary.write_text("")
    aliased.write_text("")

    graph = ts_build_dep_graph(
        tmp_path,
        DART_SPEC,
        [str(main.resolve()), str(ordinary.resolve()), str(aliased.resolve())],
    )

    assert graph[str(main.resolve())]["imports"] == {
        str(ordinary.resolve()),
        str(aliased.resolve()),
    }
