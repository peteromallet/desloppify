"""Tests for desloppify.engine.detectors.flat_dirs — flat directory detection."""

from desloppify.engine.detectors.flat_dirs import detect_flat_dirs


class TestDetectFlatDirs:
    def test_dir_over_threshold_detected(self, tmp_path):
        d = tmp_path / "components"
        d.mkdir()
        files = []
        for i in range(25):
            f = d / f"comp_{i}.tsx"
            f.write_text(f"export const Comp{i} = () => null;")
            files.append(str(f))

        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: files,
            threshold=20,
        )
        assert len(entries) == 1
        assert entries[0]["directory"] == str(d)
        assert entries[0]["file_count"] == 25
        assert total == 1

    def test_dir_under_threshold_not_detected(self, tmp_path):
        d = tmp_path / "utils"
        d.mkdir()
        files = []
        for i in range(5):
            f = d / f"util_{i}.py"
            f.write_text(f"x = {i}")
            files.append(str(f))

        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: files,
            threshold=20,
        )
        assert entries == []
        assert total == 1

    def test_dir_at_threshold_detected(self, tmp_path):
        """A dir with exactly threshold files SHOULD be flagged (uses >=)."""
        d = tmp_path / "exact"
        d.mkdir()
        files = []
        for i in range(20):
            f = d / f"file_{i}.py"
            f.write_text(f"x = {i}")
            files.append(str(f))

        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: files,
            threshold=20,
        )
        assert len(entries) == 1
        assert entries[0]["file_count"] == 20

    def test_custom_threshold(self, tmp_path):
        d = tmp_path / "small_dir"
        d.mkdir()
        files = []
        for i in range(5):
            f = d / f"file_{i}.py"
            f.write_text(f"x = {i}")
            files.append(str(f))

        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: files,
            threshold=3,
        )
        assert len(entries) == 1

    def test_multiple_dirs(self, tmp_path):
        d1 = tmp_path / "dir1"
        d1.mkdir()
        d2 = tmp_path / "dir2"
        d2.mkdir()
        files = []
        for i in range(25):
            f = d1 / f"file_{i}.py"
            f.write_text(f"x = {i}")
            files.append(str(f))
        for i in range(30):
            f = d2 / f"file_{i}.py"
            f.write_text(f"x = {i}")
            files.append(str(f))

        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: files,
            threshold=20,
        )
        assert len(entries) == 2
        assert total == 2
        # Sorted by file_count descending
        assert entries[0]["file_count"] >= entries[1]["file_count"]

    def test_empty_file_list(self, tmp_path):
        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: [],
            threshold=20,
        )
        assert entries == []
        assert total == 0

    def test_files_across_many_dirs(self, tmp_path):
        """Many directories each with few files should not trigger."""
        files = []
        for d_idx in range(10):
            d = tmp_path / f"dir_{d_idx}"
            d.mkdir()
            for f_idx in range(3):
                f = d / f"file_{f_idx}.py"
                f.write_text(f"x = {f_idx}")
                files.append(str(f))

        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: files,
            threshold=20,
        )
        assert entries == []
        assert total == 10

    def test_entry_structure(self, tmp_path):
        d = tmp_path / "components"
        d.mkdir()
        files = []
        for i in range(25):
            f = d / f"comp_{i}.tsx"
            f.write_text(f"export const Comp{i} = () => null;")
            files.append(str(f))

        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: files,
            threshold=20,
        )
        entry = entries[0]
        assert "directory" in entry
        assert "file_count" in entry
        assert isinstance(entry["file_count"], int)

    def test_sorted_by_file_count_descending(self, tmp_path):
        d1 = tmp_path / "small"
        d1.mkdir()
        d2 = tmp_path / "large"
        d2.mkdir()
        files = []
        for i in range(22):
            f = d1 / f"f_{i}.py"
            f.write_text("")
            files.append(str(f))
        for i in range(40):
            f = d2 / f"f_{i}.py"
            f.write_text("")
            files.append(str(f))

        entries, total = detect_flat_dirs(
            tmp_path,
            file_finder=lambda p: files,
            threshold=20,
        )
        assert entries[0]["file_count"] > entries[1]["file_count"]
