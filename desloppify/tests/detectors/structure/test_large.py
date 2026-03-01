"""Tests for desloppify.engine.detectors.large — large file detection."""

from desloppify.engine.detectors.large import detect_large_files


class TestDetectLargeFiles:
    def test_file_over_threshold_detected(self, tmp_path):
        big = tmp_path / "big.py"
        big.write_text("\n".join(f"line_{i} = {i}" for i in range(600)))

        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [str(big)],
            threshold=500,
        )
        assert len(entries) == 1
        assert entries[0]["file"] == str(big)
        assert entries[0]["loc"] == 600
        assert total == 1

    def test_file_under_threshold_not_detected(self, tmp_path):
        small = tmp_path / "small.py"
        small.write_text("\n".join(f"line_{i}" for i in range(100)))

        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [str(small)],
            threshold=500,
        )
        assert entries == []
        assert total == 1

    def test_file_at_threshold_not_detected(self, tmp_path):
        """A file with exactly threshold lines should NOT be flagged (uses > not >=)."""
        exact = tmp_path / "exact.py"
        exact.write_text("\n".join(f"line_{i}" for i in range(500)))

        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [str(exact)],
            threshold=500,
        )
        assert entries == []

    def test_custom_threshold(self, tmp_path):
        f = tmp_path / "medium.py"
        f.write_text("\n".join(f"line_{i}" for i in range(50)))

        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [str(f)],
            threshold=30,
        )
        assert len(entries) == 1
        assert entries[0]["loc"] == 50

    def test_multiple_files_sorted_by_loc_descending(self, tmp_path):
        f1 = tmp_path / "big.py"
        f1.write_text("\n".join(f"line_{i}" for i in range(800)))
        f2 = tmp_path / "bigger.py"
        f2.write_text("\n".join(f"line_{i}" for i in range(1200)))

        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [str(f1), str(f2)],
            threshold=500,
        )
        assert len(entries) == 2
        assert entries[0]["loc"] > entries[1]["loc"]
        assert total == 2

    def test_empty_file_list(self, tmp_path):
        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [],
            threshold=500,
        )
        assert entries == []
        assert total == 0

    def test_nonexistent_file_skipped(self, tmp_path):
        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [str(tmp_path / "ghost.py")],
            threshold=500,
        )
        assert entries == []
        assert total == 1

    def test_relative_paths_resolve_against_scan_root(self, tmp_path):
        scan_root = tmp_path / "workspace"
        target = scan_root / "src" / "big.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(f"line_{i}" for i in range(600)))

        entries, total = detect_large_files(
            scan_root,
            file_finder=lambda _p: ["src/big.py"],
            threshold=500,
        )
        assert total == 1
        assert len(entries) == 1
        assert entries[0]["file"] == "src/big.py"

    def test_mixed_files(self, tmp_path):
        small = tmp_path / "small.py"
        small.write_text("\n".join(f"line_{i}" for i in range(100)))
        big = tmp_path / "big.py"
        big.write_text("\n".join(f"line_{i}" for i in range(600)))

        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [str(small), str(big)],
            threshold=500,
        )
        assert len(entries) == 1
        assert entries[0]["file"] == str(big)
        assert total == 2

    def test_entry_structure(self, tmp_path):
        f = tmp_path / "big.py"
        f.write_text("\n".join(f"line_{i}" for i in range(600)))

        entries, total = detect_large_files(
            tmp_path,
            file_finder=lambda p: [str(f)],
            threshold=500,
        )
        entry = entries[0]
        assert "file" in entry
        assert "loc" in entry
        assert isinstance(entry["loc"], int)
