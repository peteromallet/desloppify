"""Tests for desloppify.languages.go.detectors.deps — Go dependency graph builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from desloppify.languages.go.detectors.deps import (
    _extract_imports,
    build_dep_graph,
)


# ── _extract_imports ────────────────────────────────────────


def test_extract_single_import():
    content = 'package main\n\nimport "fmt"\n'
    assert _extract_imports(content) == ["fmt"]


def test_extract_single_import_with_alias():
    content = 'package main\n\nimport f "fmt"\n'
    assert _extract_imports(content) == ["fmt"]


def test_extract_grouped_imports():
    content = 'package main\n\nimport (\n    "fmt"\n    "os"\n)\n'
    imports = _extract_imports(content)
    assert "fmt" in imports
    assert "os" in imports
    assert len(imports) == 2


def test_extract_grouped_imports_with_aliases():
    content = 'package main\n\nimport (\n    f "fmt"\n    . "os"\n    "strings"\n)\n'
    imports = _extract_imports(content)
    assert "fmt" in imports
    assert "os" in imports
    assert "strings" in imports
    assert len(imports) == 3


def test_extract_mixed_imports():
    content = 'package main\n\nimport "log"\n\nimport (\n    "fmt"\n    "os"\n)\n'
    imports = _extract_imports(content)
    assert set(imports) == {"log", "fmt", "os"}


def test_extract_no_imports():
    content = "package main\n\nfunc main() {}\n"
    assert _extract_imports(content) == []


def test_extract_blank_lines_in_group():
    content = 'package main\n\nimport (\n    "fmt"\n\n    "os"\n)\n'
    imports = _extract_imports(content)
    assert "fmt" in imports
    assert "os" in imports


# ── build_dep_graph ─────────────────────────────────────────


def _write(tmp_path: Path, name: str, content: str) -> str:
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return str(f)


def test_build_graph_empty_project(tmp_path):
    with patch(
        "desloppify.languages.go.detectors.deps.find_go_files",
        return_value=[],
    ):
        graph = build_dep_graph(tmp_path)
    assert graph == {}


def test_build_graph_no_local_imports(tmp_path):
    filepath = _write(
        tmp_path,
        "main.go",
        'package main\n\nimport "fmt"\n\nfunc main() { fmt.Println("hi") }\n',
    )
    with patch(
        "desloppify.languages.go.detectors.deps.find_go_files",
        return_value=[filepath],
    ):
        graph = build_dep_graph(tmp_path)
    assert filepath in graph
    assert graph[filepath]["import_count"] == 0


def test_build_graph_local_import(tmp_path):
    """When go.mod exists and imports resolve, edges should appear."""
    # Set up go.mod
    (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")

    # Create package files
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    pkg_file = _write(pkg_dir, "lib.go", "package pkg\n\nfunc Helper() {}\n")
    main_file = _write(
        tmp_path,
        "main.go",
        'package main\n\nimport "example.com/myapp/pkg"\n\nfunc main() { pkg.Helper() }\n',
    )

    with patch(
        "desloppify.languages.go.detectors.deps.find_go_files",
        return_value=[main_file, pkg_file],
    ):
        graph = build_dep_graph(tmp_path)

    # main.go should import pkg/lib.go
    assert graph[main_file]["import_count"] >= 1
    assert pkg_file in graph[main_file]["imports"]
    # pkg/lib.go should be imported by main.go
    assert main_file in graph[pkg_file]["importers"]
    assert graph[pkg_file]["importer_count"] >= 1


def test_build_graph_external_imports_ignored(tmp_path):
    """External imports (not matching go.mod module) should not create edges."""
    (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")

    main_file = _write(
        tmp_path,
        "main.go",
        'package main\n\nimport (\n    "fmt"\n    "github.com/other/lib"\n)\n\nfunc main() {}\n',
    )

    with patch(
        "desloppify.languages.go.detectors.deps.find_go_files",
        return_value=[main_file],
    ):
        graph = build_dep_graph(tmp_path)

    assert graph[main_file]["import_count"] == 0


def test_build_graph_counts_correct(tmp_path):
    """Verify import_count and importer_count are set by finalize_graph."""
    (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")

    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    pkg_file = _write(pkg_dir, "lib.go", "package pkg\n\nfunc F() {}\n")
    a_file = _write(
        tmp_path,
        "a.go",
        'package main\n\nimport "example.com/myapp/pkg"\n\nfunc a() { pkg.F() }\n',
    )
    b_file = _write(
        tmp_path,
        "b.go",
        'package main\n\nimport "example.com/myapp/pkg"\n\nfunc b() { pkg.F() }\n',
    )

    with patch(
        "desloppify.languages.go.detectors.deps.find_go_files",
        return_value=[a_file, b_file, pkg_file],
    ):
        graph = build_dep_graph(tmp_path)

    # pkg_file should have 2 importers (cross-package)
    assert graph[pkg_file]["importer_count"] == 2
    # Each main file should have 1 import
    assert graph[a_file]["import_count"] == 1
    assert graph[b_file]["import_count"] == 1


def test_same_package_files_not_orphaned(tmp_path):
    """Files in the same package get implicit edges so they aren't orphaned."""
    lib_file = _write(tmp_path, "lib.go", "package mylib\n\nfunc Helper() {}\n")
    util_file = _write(tmp_path, "util.go", "package mylib\n\nfunc Util() {}\n")

    with patch(
        "desloppify.languages.go.detectors.deps.find_go_files",
        return_value=[lib_file, util_file],
    ):
        graph = build_dep_graph(tmp_path)

    # Both files should have at least one importer (each other)
    assert graph[lib_file]["importer_count"] >= 1
    assert graph[util_file]["importer_count"] >= 1


def test_different_packages_same_dir_no_edges(tmp_path):
    """Files with different package names in the same dir don't get linked."""
    main_file = _write(tmp_path, "main.go", "package main\n\nfunc main() {}\n")
    lib_file = _write(tmp_path, "lib.go", "package lib\n\nfunc F() {}\n")

    with patch(
        "desloppify.languages.go.detectors.deps.find_go_files",
        return_value=[main_file, lib_file],
    ):
        graph = build_dep_graph(tmp_path)

    # Different packages — no implicit edges
    assert graph[main_file]["importer_count"] == 0
    assert graph[lib_file]["importer_count"] == 0
