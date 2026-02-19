"""Direct tests for shared facade detector helpers."""

from __future__ import annotations

from desloppify.languages.framework.facade_common import detect_reexport_facades_common


def test_detect_reexport_facades_common_filters_by_importers_and_shapes_entries():
    graph = {
        "a.py": {"importer_count": 0},
        "b.py": {"importer_count": 3},
        "c.py": {"importer_count": 1},
    }

    def fake_is_facade(path: str) -> dict | None:
        if path == "a.py":
            return {"loc": 10, "imports_from": ["pkg.a"]}
        if path == "c.py":
            return {"loc": 20, "imports_from": ["pkg.c"]}
        return None

    entries, total_checked = detect_reexport_facades_common(
        graph,
        is_facade_fn=fake_is_facade,
        max_importers=2,
    )

    assert total_checked == 3
    assert len(entries) == 2
    assert entries[0]["file"] == "a.py"
    assert entries[0]["kind"] == "file"
    assert entries[1]["file"] == "c.py"
    assert entries[1]["importers"] == 1
