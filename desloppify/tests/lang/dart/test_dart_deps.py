"""Tests for Dart dependency graph parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.languages.dart.detectors.deps import build_dep_graph


def _write(path: Path, relpath: str, content: str) -> Path:
    file_path = path / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


def test_build_dep_graph_resolves_relative_and_package_self_imports(tmp_path):
    _write(tmp_path, "pubspec.yaml", "name: sample_app\n")
    a = _write(
        tmp_path,
        "lib/a.dart",
        "import 'b.dart';\nimport 'package:sample_app/src/c.dart';\n",
    )
    b = _write(tmp_path, "lib/b.dart", "import 'dart:io';\n")
    c = _write(tmp_path, "lib/src/c.dart", "")

    with patch("desloppify.utils.PROJECT_ROOT", tmp_path):
        graph = build_dep_graph(tmp_path / "lib")

    a_key = str(a.resolve())
    b_key = str(b.resolve())
    c_key = str(c.resolve())
    assert a_key in graph
    assert b_key in graph
    assert c_key in graph
    assert graph[a_key]["imports"] == {b_key, c_key}
    assert graph[b_key]["importers"] == {a_key}
    assert graph[c_key]["importers"] == {a_key}


def test_build_dep_graph_ignores_external_package_imports(tmp_path):
    _write(tmp_path, "pubspec.yaml", "name: sample_app\n")
    main = _write(
        tmp_path,
        "lib/main.dart",
        "import 'package:flutter/material.dart';\nimport 'package:sample_app/lib2.dart';\n",
    )
    lib2 = _write(tmp_path, "lib/lib2.dart", "")

    with patch("desloppify.utils.PROJECT_ROOT", tmp_path):
        graph = build_dep_graph(tmp_path / "lib")

    main_key = str(main.resolve())
    lib2_key = str(lib2.resolve())
    assert graph[main_key]["imports"] == {lib2_key}
