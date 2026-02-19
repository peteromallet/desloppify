"""Tests for Dart test-coverage language hooks."""

from __future__ import annotations

from unittest.mock import patch

import desloppify.languages.dart.test_coverage as dart_cov


def test_strip_test_markers_for_dart():
    assert dart_cov.strip_test_markers("service_test.dart") == "service.dart"
    assert dart_cov.strip_test_markers("service.dart") is None


def test_parse_test_import_specs_extracts_imports():
    content = (
        "import 'package:app/service.dart';\n"
        "import '../helpers/mock.dart';\n"
    )
    specs = dart_cov.parse_test_import_specs(content)
    assert specs == ["package:app/service.dart", "../helpers/mock.dart"]


def test_map_test_to_source_prefers_lib_path(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: app\n")
    source = tmp_path / "lib" / "service.dart"
    source.parent.mkdir(parents=True)
    source.write_text("class Service {}")

    test_path = tmp_path / "test" / "service_test.dart"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("import 'package:test/test.dart';")

    production = {str(source.resolve())}
    with patch("desloppify.languages.dart.test_coverage.PROJECT_ROOT", tmp_path):
        mapped = dart_cov.map_test_to_source(str(test_path), production)

    assert mapped == str(source.resolve())


def test_resolve_import_spec_handles_relative_import(tmp_path):
    test_file = tmp_path / "test" / "service_test.dart"
    source = tmp_path / "lib" / "service.dart"
    source.parent.mkdir(parents=True)
    source.write_text("class Service {}")
    test_file.parent.mkdir(parents=True)
    test_file.write_text("import '../lib/service.dart';")

    production = {str(source.resolve())}
    with patch("desloppify.languages.dart.test_coverage.PROJECT_ROOT", tmp_path):
        resolved = dart_cov.resolve_import_spec(
            "../lib/service.dart", str(test_file), production
        )

    assert resolved == str(source.resolve())
