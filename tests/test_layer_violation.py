"""Tests for layer violation detector import resolution and default rules."""

from __future__ import annotations

from pathlib import Path

from desloppify.detectors.layer_violation import detect_layer_violations


def _write(root: Path, rel_path: str, content: str) -> str:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return rel_path


def test_detects_relative_import_from_detectors_to_review(tmp_path):
    rel_path = _write(
        tmp_path,
        "desloppify/detectors/review_coverage.py",
        "from ..review import prepare_review\n",
    )
    entries, total = detect_layer_violations(tmp_path, lambda _p: [rel_path])
    assert total == 1
    assert len(entries) == 1
    assert entries[0]["source_pkg"] == "detectors"
    assert entries[0]["target_pkg"] == "desloppify.review"


def test_detects_relative_importfrom_without_module(tmp_path):
    rel_path = _write(
        tmp_path,
        "desloppify/detectors/coverage.py",
        "from .. import review\n",
    )
    entries, _ = detect_layer_violations(tmp_path, lambda _p: [rel_path])
    assert len(entries) == 1
    assert entries[0]["target_pkg"] == "desloppify.review"


def test_ignores_non_forbidden_relative_import(tmp_path):
    rel_path = _write(
        tmp_path,
        "desloppify/detectors/graph.py",
        "from .helpers import parse_graph\n",
    )
    entries, _ = detect_layer_violations(tmp_path, lambda _p: [rel_path])
    assert entries == []
