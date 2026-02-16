"""Tests for TypeScript re-export facade detection."""

from __future__ import annotations

from desloppify.lang.typescript.detectors.facade import detect_reexport_facades, is_ts_facade


def _make_graph_entry(importer_count: int = 0) -> dict:
    return {
        "imports": set(),
        "importers": set(),
        "import_count": 0,
        "importer_count": importer_count,
    }


class TestIsTsFacade:
    def test_pure_reexport(self, tmp_path):
        f = tmp_path / "index.ts"
        f.write_text("export { foo, bar } from './module';\nexport * from './other';\n")
        result = is_ts_facade(str(f))
        assert result is not None
        assert "./module" in result["imports_from"]
        assert "./other" in result["imports_from"]

    def test_file_with_logic_not_facade(self, tmp_path):
        f = tmp_path / "real.ts"
        f.write_text("export { foo } from './module';\nconst x = 1;\n")
        result = is_ts_facade(str(f))
        assert result is None

    def test_type_reexport(self, tmp_path):
        f = tmp_path / "types.ts"
        f.write_text("export type { MyType } from './types';\n")
        result = is_ts_facade(str(f))
        assert result is not None

    def test_comments_allowed(self, tmp_path):
        f = tmp_path / "index.ts"
        f.write_text("// Re-exports\nexport { foo } from './module';\n")
        result = is_ts_facade(str(f))
        assert result is not None

    def test_empty_file_not_facade(self, tmp_path):
        f = tmp_path / "empty.ts"
        f.write_text("")
        result = is_ts_facade(str(f))
        assert result is None

    def test_nonexistent_file(self):
        result = is_ts_facade("/nonexistent/path/index.ts")
        assert result is None


class TestDetectReexportFacades:
    def test_facade_file_detected(self, tmp_path):
        f = tmp_path / "index.ts"
        f.write_text("export { foo } from './module';\nexport * from './other';\n")

        graph = {str(f): _make_graph_entry(importer_count=0)}
        entries, total = detect_reexport_facades(graph)
        assert len(entries) == 1
        assert entries[0]["kind"] == "file"
        assert total == 1

    def test_non_facade_file_not_detected(self, tmp_path):
        f = tmp_path / "real.ts"
        f.write_text("export { foo } from './module';\nconst x = 1;\n")

        graph = {str(f): _make_graph_entry(importer_count=1)}
        entries, total = detect_reexport_facades(graph)
        assert entries == []
        assert total == 1

    def test_too_many_importers_excluded(self, tmp_path):
        f = tmp_path / "index.ts"
        f.write_text("export * from './core';\n")

        graph = {str(f): _make_graph_entry(importer_count=5)}
        entries, total = detect_reexport_facades(graph, max_importers=2)
        assert entries == []
        assert total == 1

    def test_custom_max_importers(self, tmp_path):
        f = tmp_path / "index.ts"
        f.write_text("export * from './core';\n")

        graph = {str(f): _make_graph_entry(importer_count=3)}
        entries, total = detect_reexport_facades(graph, max_importers=3)
        assert len(entries) == 1
        assert total == 1

    def test_empty_graph(self):
        entries, total = detect_reexport_facades({})
        assert entries == []
        assert total == 0
