"""Tests for Python private-import detector."""

from __future__ import annotations

from pathlib import Path

from desloppify.lang.python.detectors.private_imports import detect_private_imports


def _graph_entry(*, imports: set[str] | None = None) -> dict:
    return {
        "imports": imports or set(),
        "importers": set(),
        "importer_count": 0,
        "import_count": 0,
    }


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)


def test_detects_cross_module_private_import(tmp_path: Path):
    target = _write(tmp_path / "shared_pkg" / "helpers.py", "VALUE = 1\n")
    source = _write(
        tmp_path / "consumer_pkg" / "service.py",
        "from shared_pkg.helpers import _secret\n",
    )

    dep_graph = {
        source: _graph_entry(imports={target}),
        target: _graph_entry(),
    }
    entries, files_checked = detect_private_imports(dep_graph)

    assert files_checked == 2
    assert len(entries) == 1
    assert "_secret" in entries[0]["summary"]


def test_skips_test_file_private_import(tmp_path: Path):
    target = _write(tmp_path / "pkg" / "helpers.py", "VALUE = 1\n")
    source = _write(tmp_path / "tests" / "test_service.py", "from pkg.helpers import _secret\n")

    dep_graph = {
        source: _graph_entry(imports={target}),
        target: _graph_entry(),
    }
    entries, files_checked = detect_private_imports(dep_graph)

    assert files_checked == 1
    assert entries == []
