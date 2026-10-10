"""Statamic discovers native extension classes without application imports."""

from __future__ import annotations

import json

import pytest

from desloppify.base.runtime_state import RuntimeContext, runtime_scope
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)


def _source(tmp_path, directory):
    source = tmp_path / "app" / directory / "Example.php"
    source.parent.mkdir(parents=True)
    source.write_text("<?php\n" + "// extension implementation\n" * 20)
    graph = {str(source): {"importer_count": 0, "import_count": 0}}
    return source, graph


@pytest.mark.parametrize(
    "directory",
    ["Actions", "Dictionaries", "Fieldtypes", "Modifiers", "Scopes", "Tags", "Widgets"],
)
def test_statamic_discovery_keeps_extension_classes(tmp_path, directory):
    (tmp_path / "composer.json").write_text(
        json.dumps({"require": {"statamic/cms": "^6.0"}})
    )
    _, graph = _source(tmp_path, directory)
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        findings, total = detect_orphaned_files(tmp_path, graph, [".php"])
    assert total == 1
    assert findings == []


@pytest.mark.parametrize(
    "composer",
    [None, "invalid json", "[]", '{"require": {"laravel/framework": "*"}}'],
)
def test_same_directory_in_other_projects_remains_an_orphan(tmp_path, composer):
    if composer is not None:
        (tmp_path / "composer.json").write_text(composer)
    source, graph = _source(tmp_path, "Fieldtypes")
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        findings, _ = detect_orphaned_files(tmp_path, graph, [".php"])
    assert [row["file"] for row in findings] == [str(source)]


def test_statamic_does_not_exempt_ordinary_application_modules(tmp_path):
    (tmp_path / "composer.json").write_text(
        json.dumps({"require": {"statamic/cms": "^6.0"}})
    )
    source, graph = _source(tmp_path, "Services")
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        findings, _ = detect_orphaned_files(tmp_path, graph, [".php"])
    assert [row["file"] for row in findings] == [str(source)]


def test_statamic_detection_honors_framework_detection_option(tmp_path):
    (tmp_path / "composer.json").write_text(
        json.dumps({"require": {"statamic/cms": "^6.0"}})
    )
    source, graph = _source(tmp_path, "Fieldtypes")
    with runtime_scope(RuntimeContext(project_root=tmp_path)):
        findings, _ = detect_orphaned_files(
            tmp_path, graph, [".php"], OrphanedDetectionOptions(detect_frameworks=False)
        )
    assert [row["file"] for row in findings] == [str(source)]
