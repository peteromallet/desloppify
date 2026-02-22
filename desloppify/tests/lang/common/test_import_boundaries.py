"""Import boundary and layering regression tests."""

from __future__ import annotations

import ast
from pathlib import Path


def _module_name_from_import(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        if not node.names:
            return ""
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    return ""


def test_detectors_layer_does_not_import_lang_layer():
    detector_dir = Path("desloppify/engine/detectors")
    offenders: list[tuple[str, str]] = []

    for py_file in sorted(detector_dir.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            module_name = _module_name_from_import(node)
            if module_name.startswith("desloppify.languages"):
                offenders.append((str(py_file), module_name))

    assert offenders == [], f"detectors imported lang modules: {offenders}"


def test_review_cmd_uses_split_modules():
    entrypoint_src = Path("desloppify/app/commands/review/entrypoint.py").read_text()
    assert "from .batch import _do_run_batches" in entrypoint_src
    assert "from .import_cmd import do_import" in entrypoint_src
    assert "from .prepare import do_prepare" in entrypoint_src
    # registry imports directly from entrypoint (no cmd.py indirection)
    registry_src = Path("desloppify/app/commands/registry.py").read_text()
    assert "review.entrypoint import cmd_review" in registry_src


def test_scan_reporting_aggregator_uses_split_modules():
    src = Path("desloppify/app/commands/scan/scan_reporting_dimensions.py").read_text()
    assert "scan_reporting_presentation as presentation_mod" in src
    assert "scan_reporting_subjective import" in src


def test_scan_subjective_paths_aggregator_removed():
    assert not Path(
        "desloppify/app/commands/scan/scan_reporting_subjective_paths.py"
    ).exists()


def test_cli_parser_uses_group_module():
    src = Path("desloppify/app/cli_support/parser.py").read_text()
    assert "parser_groups import" in src
