"""Tests for desloppify.engine.detectors.naming — naming convention inconsistency detection."""

import os

import desloppify.engine.detectors.naming as naming_mod
import desloppify.utils as utils_mod
from desloppify.engine.detectors.naming import (
    _classify_convention,
    detect_naming_inconsistencies,
)


class TestClassifyConvention:
    def test_kebab_case(self):
        assert _classify_convention("my-component.tsx") == "kebab-case"

    def test_pascal_case(self):
        assert _classify_convention("MyComponent.tsx") == "PascalCase"

    def test_camel_case(self):
        assert _classify_convention("myComponent.tsx") == "camelCase"

    def test_snake_case(self):
        assert _classify_convention("my_module.py") == "snake_case"

    def test_flat_lower(self):
        assert _classify_convention("utils.py") == "flat_lower"

    def test_unclassifiable(self):
        """Filenames that don't match any pattern return None."""
        # Mixed case with hyphens doesn't match any convention
        assert _classify_convention("My-Component.tsx") is None

    def test_empty_stem(self):
        assert _classify_convention(".gitignore") is None

    def test_kebab_with_uppercase_not_kebab(self):
        """Kebab requires all lowercase."""
        assert _classify_convention("My-Component.tsx") != "kebab-case"

    def test_no_extension(self):
        assert _classify_convention("Makefile") == "PascalCase"

    def test_snake_case_no_ext(self):
        assert _classify_convention("my_script") == "snake_case"


class TestDetectNamingInconsistencies:
    def _build_files(self, tmp_path, dir_name, filenames):
        """Create files in a subdirectory and return their paths."""
        d = tmp_path / dir_name
        d.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in filenames:
            f = d / name
            f.write_text("")
            paths.append(str(f))
        return paths

    def test_consistent_dir_no_findings(self, tmp_path):
        """A directory with a single convention should produce no findings."""
        files = self._build_files(
            tmp_path, "components", [f"my-component-{i}.tsx" for i in range(10)]
        )
        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: files,
        )
        assert entries == []

    def test_mixed_conventions_detected(self, tmp_path, monkeypatch):
        """A directory with significant minority convention should be flagged."""
        # Majority: kebab-case (15 files)
        kebab_files = [f"comp-{i}.tsx" for i in range(15)]
        # Minority: PascalCase (6 files) — meets both >=5 and >=15% thresholds
        pascal_files = [f"Comp{i}.tsx" for i in range(6)]
        files = self._build_files(tmp_path, "components", kebab_files + pascal_files)

        # We need to make rel() work — monkeypatch PROJECT_ROOT
        monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(naming_mod, "rel", lambda p: os.path.relpath(p, tmp_path))

        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: files,
        )
        assert len(entries) == 1
        assert entries[0]["majority"] == "kebab-case"
        assert entries[0]["minority"] == "PascalCase"
        assert entries[0]["minority_count"] == 6

    def test_minority_below_absolute_threshold(self, tmp_path, monkeypatch):
        """A minority with < 5 files should NOT be flagged."""
        kebab_files = [f"comp-{i}.tsx" for i in range(20)]
        pascal_files = [f"Comp{i}.tsx" for i in range(4)]  # only 4
        files = self._build_files(tmp_path, "components", kebab_files + pascal_files)

        monkeypatch.setattr(naming_mod, "rel", lambda p: os.path.relpath(p, tmp_path))

        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: files,
        )
        assert entries == []

    def test_minority_below_proportional_threshold(self, tmp_path, monkeypatch):
        """A minority < 15% of total should NOT be flagged."""
        # 50 kebab + 5 pascal = 55 total; 5/55 = 9% < 15%
        kebab_files = [f"comp-{i}.tsx" for i in range(50)]
        pascal_files = [f"Comp{i}.tsx" for i in range(5)]
        files = self._build_files(tmp_path, "components", kebab_files + pascal_files)

        monkeypatch.setattr(naming_mod, "rel", lambda p: os.path.relpath(p, tmp_path))

        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: files,
        )
        assert entries == []

    def test_skip_names_excluded(self, tmp_path, monkeypatch):
        """Files in skip_names should be excluded from analysis."""
        kebab_files = [f"comp-{i}.tsx" for i in range(15)]
        # These would normally be flagged but are skipped
        pascal_files = [f"Comp{i}.tsx" for i in range(6)]
        skip = {f"Comp{i}.tsx" for i in range(6)}
        files = self._build_files(tmp_path, "components", kebab_files + pascal_files)

        monkeypatch.setattr(naming_mod, "rel", lambda p: os.path.relpath(p, tmp_path))

        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: files,
            skip_names=skip,
        )
        assert entries == []

    def test_skip_dirs_excluded(self, tmp_path, monkeypatch):
        """Directories in skip_dirs should be excluded from analysis."""
        files = self._build_files(
            tmp_path,
            "generated",
            [f"comp-{i}.tsx" for i in range(15)] + [f"Comp{i}.tsx" for i in range(6)],
        )

        monkeypatch.setattr(naming_mod, "rel", lambda p: os.path.relpath(p, tmp_path))

        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: files,
            skip_dirs={"generated"},
        )
        assert entries == []

    def test_empty_file_list(self, tmp_path):
        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: [],
        )
        assert entries == []
        assert total == 0

    def test_entry_structure(self, tmp_path, monkeypatch):
        kebab_files = [f"comp-{i}.tsx" for i in range(15)]
        pascal_files = [f"Comp{i}.tsx" for i in range(6)]
        files = self._build_files(tmp_path, "src", kebab_files + pascal_files)

        monkeypatch.setattr(naming_mod, "rel", lambda p: os.path.relpath(p, tmp_path))

        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: files,
        )
        assert len(entries) == 1
        entry = entries[0]
        assert "directory" in entry
        assert "majority" in entry
        assert "majority_count" in entry
        assert "minority" in entry
        assert "minority_count" in entry
        assert "total_files" in entry
        assert "outliers" in entry
        assert isinstance(entry["outliers"], list)

    def test_outliers_capped_at_10(self, tmp_path, monkeypatch):
        """Outliers list should contain at most 10 entries."""
        kebab_files = [f"comp-{i}.tsx" for i in range(30)]
        pascal_files = [f"Comp{i}.tsx" for i in range(15)]
        files = self._build_files(tmp_path, "src", kebab_files + pascal_files)

        monkeypatch.setattr(naming_mod, "rel", lambda p: os.path.relpath(p, tmp_path))

        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: files,
        )
        assert len(entries) == 1
        assert len(entries[0]["outliers"]) <= 10

    def test_sorted_by_minority_count_descending(self, tmp_path, monkeypatch):
        """Entries should be sorted by minority count descending."""
        # Dir 1: 15 kebab + 6 pascal
        d1_files = self._build_files(
            tmp_path,
            "dir1",
            [f"comp-{i}.tsx" for i in range(15)] + [f"Comp{i}.tsx" for i in range(6)],
        )
        # Dir 2: 15 kebab + 10 pascal
        d2_files = self._build_files(
            tmp_path,
            "dir2",
            [f"comp-{i}.tsx" for i in range(15)] + [f"Comp{i}.tsx" for i in range(10)],
        )

        monkeypatch.setattr(naming_mod, "rel", lambda p: os.path.relpath(p, tmp_path))

        entries, total = detect_naming_inconsistencies(
            tmp_path,
            file_finder=lambda p: d1_files + d2_files,
        )
        assert len(entries) == 2
        assert entries[0]["minority_count"] >= entries[1]["minority_count"]
