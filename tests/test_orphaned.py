"""Tests for desloppify.detectors.orphaned — orphaned file detection."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from desloppify.detectors.orphaned import (
    _is_dynamically_imported,
    detect_orphaned_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _graph_entry(
    *,
    imports: set[str] | None = None,
    importer_count: int = 0,
    importers: list[str] | None = None,
) -> dict:
    """Build a minimal graph node dict."""
    return {
        "imports": imports or set(),
        "importer_count": importer_count,
        "importers": importers or [],
    }


def _write_file(path: Path, lines: int = 20) -> Path:
    """Write a dummy file with the given number of lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"line {i}" for i in range(lines)))
    return path


# ===================================================================
# _is_dynamically_imported
# ===================================================================

class TestIsDynamicallyImported:
    """Unit tests for the _is_dynamically_imported helper."""

    @patch("desloppify.detectors.orphaned.rel")
    def test_direct_relative_path_match(self, mock_rel):
        """File matches when its relative path (no ext) equals the target."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        targets = {"src/utils/helpers"}
        assert _is_dynamically_imported(filepath, targets) is True

    @patch("desloppify.detectors.orphaned.rel")
    def test_stem_match(self, mock_rel):
        """File matches when its stem equals the target."""
        filepath = "/project/src/config.ts"
        mock_rel.return_value = "src/config.ts"
        targets = {"config"}
        assert _is_dynamically_imported(filepath, targets) is True

    @patch("desloppify.detectors.orphaned.rel")
    def test_target_with_leading_dot_slash(self, mock_rel):
        """Leading ./ is stripped from targets before matching."""
        filepath = "/project/src/foo.ts"
        mock_rel.return_value = "src/foo.ts"
        targets = {"./src/foo"}
        assert _is_dynamically_imported(filepath, targets) is True

    @patch("desloppify.detectors.orphaned.rel")
    def test_with_alias_resolver(self, mock_rel):
        """Alias resolver transforms the target before matching."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        targets = {"@/utils/helpers"}

        def resolver(t: str) -> str:
            return t.replace("@/", "src/")

        assert _is_dynamically_imported(filepath, targets, alias_resolver=resolver) is True

    @patch("desloppify.detectors.orphaned.rel")
    def test_no_match_returns_false(self, mock_rel):
        """Returns False when no target matches."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        targets = {"totally/different", "unrelated"}
        assert _is_dynamically_imported(filepath, targets) is False

    @patch("desloppify.detectors.orphaned.rel")
    def test_empty_targets_returns_false(self, mock_rel):
        """Returns False when the target set is empty."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        assert _is_dynamically_imported(filepath, set()) is False

    @patch("desloppify.detectors.orphaned.rel")
    def test_basename_match_via_trailing_slash(self, mock_rel):
        """Matches target ending with /filename."""
        filepath = "/project/src/deep/nested/widget.ts"
        mock_rel.return_value = "src/deep/nested/widget.ts"
        targets = {"components/widget"}
        # stem "widget" == target ending "widget" after split
        assert _is_dynamically_imported(filepath, targets) is True

    @patch("desloppify.detectors.orphaned.rel")
    def test_full_filename_match(self, mock_rel):
        """Matches when target ends with /filename.ext."""
        filepath = "/project/src/utils/helpers.ts"
        mock_rel.return_value = "src/utils/helpers.ts"
        targets = {"stuff/helpers.ts"}
        assert _is_dynamically_imported(filepath, targets) is True


# ===================================================================
# detect_orphaned_files
# ===================================================================

class TestDetectOrphanedFiles:
    """Integration tests for detect_orphaned_files using tmp_path."""

    def test_files_with_importers_not_orphaned(self, tmp_path):
        """Files with importer_count > 0 should not appear in results."""
        f1 = _write_file(tmp_path / "used.py", lines=50)
        f2 = _write_file(tmp_path / "unused.py", lines=50)

        graph = {
            str(f1): _graph_entry(importer_count=3, importers=["a", "b", "c"]),
            str(f2): _graph_entry(importer_count=0),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(f2)

    def test_entry_pattern_match_excluded(self, tmp_path):
        """Files matching entry_patterns are not reported as orphaned."""
        f1 = _write_file(tmp_path / "main.py", lines=30)
        f2 = _write_file(tmp_path / "app.py", lines=30)
        f3 = _write_file(tmp_path / "orphan.py", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
            str(f2): _graph_entry(importer_count=0),
            str(f3): _graph_entry(importer_count=0),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(
                tmp_path, graph, [".py"],
                extra_entry_patterns=["main", "app"],
            )

        assert total == 3
        assert len(entries) == 1
        assert entries[0]["file"] == str(f3)

    def test_barrel_names_excluded(self, tmp_path):
        """Files matching barrel_names are not reported as orphaned."""
        f1 = _write_file(tmp_path / "index.ts", lines=30)
        f2 = _write_file(tmp_path / "orphan.ts", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
            str(f2): _graph_entry(importer_count=0),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(
                tmp_path, graph, [".ts"],
                extra_barrel_names={"index.ts"},
            )

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(f2)

    def test_small_files_suppressed(self, tmp_path):
        """Files with fewer than 10 lines are suppressed."""
        f_small = _write_file(tmp_path / "tiny.py", lines=5)
        f_big = _write_file(tmp_path / "large.py", lines=50)

        graph = {
            str(f_small): _graph_entry(importer_count=0),
            str(f_big): _graph_entry(importer_count=0),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(f_big)
        assert entries[0]["loc"] == 50

    def test_dynamically_imported_files_excluded(self, tmp_path):
        """Files found by the dynamic_import_finder are not orphaned."""
        f1 = _write_file(tmp_path / "lazy.py", lines=30)
        f2 = _write_file(tmp_path / "orphan.py", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
            str(f2): _graph_entry(importer_count=0),
        }

        def mock_dynamic_finder(path, extensions):
            return {"lazy"}

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(
                tmp_path, graph, [".py"],
                dynamic_import_finder=mock_dynamic_finder,
            )

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["file"] == str(f2)

    def test_results_sorted_by_loc_descending(self, tmp_path):
        """Results are sorted by LOC descending (largest files first)."""
        f_small = _write_file(tmp_path / "small.py", lines=20)
        f_medium = _write_file(tmp_path / "medium.py", lines=50)
        f_large = _write_file(tmp_path / "large.py", lines=100)

        graph = {
            str(f_small): _graph_entry(importer_count=0),
            str(f_medium): _graph_entry(importer_count=0),
            str(f_large): _graph_entry(importer_count=0),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 3
        assert len(entries) == 3
        assert entries[0]["loc"] == 100
        assert entries[1]["loc"] == 50
        assert entries[2]["loc"] == 20

    def test_returns_entries_and_total_files(self, tmp_path):
        """Return value is (entries_list, total_files_in_graph)."""
        f1 = _write_file(tmp_path / "a.py", lines=15)
        f2 = _write_file(tmp_path / "b.py", lines=15)
        f3 = _write_file(tmp_path / "c.py", lines=15)

        graph = {
            str(f1): _graph_entry(importer_count=2),
            str(f2): _graph_entry(importer_count=0),
            str(f3): _graph_entry(importer_count=1),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 3
        assert len(entries) == 1
        assert entries[0]["file"] == str(f2)

    def test_empty_graph(self, tmp_path):
        """Empty graph returns empty entries and zero total."""
        entries, total = detect_orphaned_files(tmp_path, {}, [".py"])
        assert entries == []
        assert total == 0

    def test_all_files_have_importers(self, tmp_path):
        """When every file is imported, nothing is orphaned."""
        f1 = _write_file(tmp_path / "a.py", lines=50)
        f2 = _write_file(tmp_path / "b.py", lines=50)

        graph = {
            str(f1): _graph_entry(importer_count=1),
            str(f2): _graph_entry(importer_count=5),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert entries == []
        assert total == 2

    def test_unreadable_file_treated_as_zero_loc(self, tmp_path):
        """Files that can't be read get loc=0 and are suppressed (< 10)."""
        nonexistent = tmp_path / "ghost.py"

        graph = {
            str(nonexistent): _graph_entry(importer_count=0),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert total == 1
        assert entries == []  # suppressed because loc=0 < 10

    def test_dynamic_finder_with_alias_resolver(self, tmp_path):
        """Dynamic import finder + alias resolver together exclude files."""
        f1 = _write_file(tmp_path / "src" / "utils" / "helpers.py", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
        }

        def mock_dynamic_finder(path, extensions):
            return {"@/utils/helpers"}

        def mock_alias_resolver(target):
            return target.replace("@/", "src/")

        rel_path = str(Path("src/utils/helpers.py"))
        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(
                tmp_path, graph, [".py"],
                dynamic_import_finder=mock_dynamic_finder,
                alias_resolver=mock_alias_resolver,
            )

        assert total == 1
        assert entries == []  # excluded by dynamic import with alias resolution

    def test_no_dynamic_finder_skips_check(self, tmp_path):
        """When dynamic_import_finder is None, dynamic check is skipped entirely."""
        f1 = _write_file(tmp_path / "orphan.py", lines=30)

        graph = {
            str(f1): _graph_entry(importer_count=0),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(
                tmp_path, graph, [".py"],
                dynamic_import_finder=None,
            )

        assert len(entries) == 1
        assert entries[0]["file"] == str(f1)

    def test_entry_has_file_and_loc_keys(self, tmp_path):
        """Each entry includes file/loc plus corroboration metadata."""
        f1 = _write_file(tmp_path / "orphan.py", lines=25)

        graph = {
            str(f1): _graph_entry(importer_count=0),
        }

        with patch("desloppify.detectors.orphaned.rel", side_effect=lambda p: str(Path(p).relative_to(tmp_path))):
            entries, total = detect_orphaned_files(tmp_path, graph, [".py"])

        assert len(entries) == 1
        assert set(entries[0].keys()) == {"file", "loc", "import_count"}
        assert entries[0]["loc"] == 25
        assert entries[0]["import_count"] == 0
