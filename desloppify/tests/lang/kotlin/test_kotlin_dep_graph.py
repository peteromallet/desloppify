"""Tests for Kotlin dependency graph construction (imports + same-package refs)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from desloppify.languages._framework.treesitter import KOTLIN_SPEC
from desloppify.languages._framework.treesitter.imports.graph import ts_build_dep_graph


def _write(path: Path, relpath: str, content: str) -> str:
    file_path = path / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return str(file_path)


def test_same_package_reference_counts_as_importer(tmp_path):
    """A same-package reference without an import rescues the declaring file."""
    controller = _write(
        tmp_path,
        "src/main/kotlin/com/acme/web/ThingController.kt",
        """
        package com.acme.web

        import org.springframework.web.bind.annotation.RestController

        @RestController
        class ThingController {
            fun get(): ThingResponse = ThingResponse(id = "1")
        }
        """,
    )
    dto = _write(
        tmp_path,
        "src/main/kotlin/com/acme/web/ThingResponse.kt",
        """
        package com.acme.web

        data class ThingResponse(val id: String)
        """,
    )

    graph = ts_build_dep_graph(tmp_path, KOTLIN_SPEC, [controller, dto])

    assert graph[dto]["importers"] == {controller}
    assert graph[dto]["importer_count"] == 1
    # Same-package references must not register as outgoing imports, so
    # cycle detection stays purely import-based.
    assert graph[controller]["imports"] == set()


def test_same_package_without_reference_is_still_orphan_candidate(tmp_path):
    """Files sharing a package but never referenced gain no importers."""
    used = _write(
        tmp_path,
        "src/main/kotlin/com/acme/web/Used.kt",
        """
        package com.acme.web

        class Used
        """,
    )
    dead = _write(
        tmp_path,
        "src/main/kotlin/com/acme/web/Dead.kt",
        """
        package com.acme.web

        class Dead
        """,
    )

    graph = ts_build_dep_graph(tmp_path, KOTLIN_SPEC, [used, dead])

    assert graph[dead]["importer_count"] == 0
    assert graph[used]["importer_count"] == 0


def test_explicit_import_still_resolves_alongside_package_edges(tmp_path):
    """Regular cross-package imports keep working when package_query is set."""
    service = _write(
        tmp_path,
        "src/main/kotlin/com/acme/app/ThingService.kt",
        """
        package com.acme.app

        import com.acme.domain.Thing

        class ThingService {
            fun load(): Thing = Thing()
        }
        """,
    )
    model = _write(
        tmp_path,
        "src/main/kotlin/com/acme/domain/Thing.kt",
        """
        package com.acme.domain

        class Thing
        """,
    )

    graph = ts_build_dep_graph(tmp_path, KOTLIN_SPEC, [service, model])

    assert graph[model]["importers"] == {service}
    assert graph[service]["imports"] == {model}
