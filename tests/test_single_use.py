"""Tests for desloppify.detectors.single_use — single-use abstraction detection."""

import pytest

from desloppify.detectors.single_use import detect_single_use_abstractions


def _make_graph_entry(importers: set[str]) -> dict:
    return {
        "imports": set(),
        "importers": importers,
        "import_count": 0,
        "importer_count": len(importers),
    }


class TestDetectSingleUseAbstractions:
    def test_file_with_one_importer_detected(self, tmp_path):
        """A file imported by exactly one other file should be detected."""
        target = tmp_path / "helper.py"
        # Create a file with 50 lines (within 20-300 range)
        target.write_text("\n".join(f"line_{i} = {i}" for i in range(50)))

        graph = {
            str(target): _make_graph_entry({str(tmp_path / "main.py")}),
        }
        entries, total = detect_single_use_abstractions(tmp_path, graph, barrel_names=set())
        assert len(entries) == 1
        assert entries[0]["file"] == str(target)
        assert entries[0]["loc"] == 50
        assert "sole_importer" in entries[0]

    def test_file_with_zero_importers_not_detected(self, tmp_path):
        """A file with zero importers is orphaned, not single-use."""
        target = tmp_path / "orphan.py"
        target.write_text("\n".join(f"line_{i} = {i}" for i in range(50)))

        graph = {
            str(target): _make_graph_entry(set()),
        }
        entries, total = detect_single_use_abstractions(tmp_path, graph, barrel_names=set())
        assert entries == []

    def test_file_with_two_importers_not_detected(self, tmp_path):
        """A file with 2+ importers should not be flagged."""
        target = tmp_path / "shared.py"
        target.write_text("\n".join(f"line_{i} = {i}" for i in range(50)))

        importers = {str(tmp_path / "a.py"), str(tmp_path / "b.py")}
        graph = {
            str(target): _make_graph_entry(importers),
        }
        entries, total = detect_single_use_abstractions(tmp_path, graph, barrel_names=set())
        assert entries == []

    def test_barrel_files_skipped(self, tmp_path):
        """Barrel files (e.g., index.ts, __init__.py) should be skipped."""
        target = tmp_path / "index.ts"
        target.write_text("\n".join(f"export line {i}" for i in range(50)))

        graph = {
            str(target): _make_graph_entry({str(tmp_path / "main.ts")}),
        }
        entries, total = detect_single_use_abstractions(
            tmp_path, graph, barrel_names={"index.ts"}
        )
        assert entries == []

    def test_file_too_small_excluded(self, tmp_path):
        """Files under 20 LOC should not be flagged (too small to matter)."""
        target = tmp_path / "tiny.py"
        target.write_text("\n".join(f"line_{i}" for i in range(10)))

        graph = {
            str(target): _make_graph_entry({str(tmp_path / "main.py")}),
        }
        entries, total = detect_single_use_abstractions(tmp_path, graph, barrel_names=set())
        assert entries == []
        # But it should still count as a candidate
        assert total == 1

    def test_file_too_large_excluded(self, tmp_path):
        """Files over 300 LOC should not be flagged."""
        target = tmp_path / "huge.py"
        target.write_text("\n".join(f"line_{i}" for i in range(350)))

        graph = {
            str(target): _make_graph_entry({str(tmp_path / "main.py")}),
        }
        entries, total = detect_single_use_abstractions(tmp_path, graph, barrel_names=set())
        assert entries == []
        assert total == 1

    def test_empty_graph(self, tmp_path):
        entries, total = detect_single_use_abstractions(tmp_path, {}, barrel_names=set())
        assert entries == []
        assert total == 0

    def test_nonexistent_file_skipped(self, tmp_path):
        """Files that don't exist on disk should be silently skipped."""
        graph = {
            str(tmp_path / "ghost.py"): _make_graph_entry({str(tmp_path / "main.py")}),
        }
        entries, total = detect_single_use_abstractions(tmp_path, graph, barrel_names=set())
        assert entries == []

    def test_entry_contains_loc_and_sole_importer(self, tmp_path):
        """Entries should contain loc/import metadata and sole importer."""
        target = tmp_path / "util.py"
        target.write_text("\n".join(f"line_{i} = {i}" for i in range(50)))
        importer = str(tmp_path / "consumer.py")

        graph = {
            str(target): _make_graph_entry({importer}),
        }
        entries, total = detect_single_use_abstractions(tmp_path, graph, barrel_names=set())
        assert len(entries) == 1
        assert entries[0]["loc"] == 50
        assert "sole_importer" in entries[0]
        assert "import_count" in entries[0]
        assert entries[0]["import_count"] == 0
        assert "reason" in entries[0]

    def test_sorted_by_loc_descending(self, tmp_path):
        """Results should be sorted by LOC descending."""
        small = tmp_path / "small.py"
        small.write_text("\n".join(f"line_{i}" for i in range(30)))
        large = tmp_path / "large.py"
        large.write_text("\n".join(f"line_{i}" for i in range(100)))

        graph = {
            str(small): _make_graph_entry({str(tmp_path / "a.py")}),
            str(large): _make_graph_entry({str(tmp_path / "b.py")}),
        }
        entries, total = detect_single_use_abstractions(tmp_path, graph, barrel_names=set())
        assert len(entries) == 2
        assert entries[0]["loc"] > entries[1]["loc"]
