"""External test-file discovery tests for shared transitive phases."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import desloppify.languages._framework.base.shared_phases as shared_phases_mod


class TestFindExternalTestFiles:
    def test_finds_test_files_outside_scanned_path(self, tmp_path):
        """Test files in PROJECT_ROOT/tests/ are discovered."""
        # Set up project structure
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("pass")
        (tests_dir / "test_bar.py").write_text("pass")
        (tests_dir / "readme.md").write_text("not a test")

        mock_lang = MagicMock()
        mock_lang.external_test_dirs = ["tests"]
        mock_lang.test_file_extensions = [".py"]
        mock_lang.extensions = [".py"]

        with patch(
            "desloppify.languages._framework.base.shared_phases.get_project_root",
            return_value=tmp_path,
        ):
            result = shared_phases_mod.find_external_test_files(src_dir, mock_lang)

        assert len(result) == 2
        filenames = {os.path.basename(f) for f in result}
        assert "test_foo.py" in filenames
        assert "test_bar.py" in filenames

    def test_skips_dirs_inside_scanned_path(self, tmp_path):
        """Test dirs that are inside the scanned path are skipped."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        tests_inside = src_dir / "tests"
        tests_inside.mkdir()
        (tests_inside / "test_inner.py").write_text("pass")

        mock_lang = MagicMock()
        mock_lang.external_test_dirs = ["src/tests"]
        mock_lang.test_file_extensions = [".py"]
        mock_lang.extensions = [".py"]

        with patch(
            "desloppify.languages._framework.base.shared_phases.get_project_root",
            return_value=tmp_path,
        ):
            result = shared_phases_mod.find_external_test_files(src_dir, mock_lang)

        assert len(result) == 0

    def test_missing_test_dir(self, tmp_path):
        """Non-existent test dir is silently skipped."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        mock_lang = MagicMock()
        mock_lang.external_test_dirs = ["nonexistent"]
        mock_lang.test_file_extensions = [".py"]

        with patch(
            "desloppify.languages._framework.base.shared_phases.get_project_root",
            return_value=tmp_path,
        ):
            result = shared_phases_mod.find_external_test_files(src_dir, mock_lang)

        assert result == set()

    def test_uses_lang_extensions_as_fallback(self, tmp_path):
        """When test_file_extensions is falsy, falls back to extensions."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.ts").write_text("pass")

        mock_lang = MagicMock()
        mock_lang.external_test_dirs = ["tests"]
        mock_lang.test_file_extensions = None
        mock_lang.extensions = [".ts", ".tsx"]

        with patch(
            "desloppify.languages._framework.base.shared_phases.get_project_root",
            return_value=tmp_path,
        ):
            result = shared_phases_mod.find_external_test_files(src_dir, mock_lang)

        assert len(result) == 1
        assert any("test_foo.ts" in f for f in result)

    def test_uses_default_test_dirs(self, tmp_path):
        """When external_test_dirs is falsy, defaults to [tests, test]."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        tests_dir = tmp_path / "test"
        tests_dir.mkdir()
        (tests_dir / "check.py").write_text("pass")

        mock_lang = MagicMock()
        mock_lang.external_test_dirs = None
        mock_lang.test_file_extensions = [".py"]

        with patch(
            "desloppify.languages._framework.base.shared_phases.get_project_root",
            return_value=tmp_path,
        ):
            result = shared_phases_mod.find_external_test_files(src_dir, mock_lang)

        assert len(result) == 1
