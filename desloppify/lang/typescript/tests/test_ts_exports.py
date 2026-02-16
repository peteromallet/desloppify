"""Tests for desloppify.lang.typescript.detectors.exports — dead export detection."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT and SRC_PATH at the tmp directory."""
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    import desloppify.utils as utils_mod
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(utils_mod, "SRC_PATH", tmp_path)
    import desloppify.lang.typescript.detectors.exports as det_mod
    monkeypatch.setattr(det_mod, "SRC_PATH", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── EXPORT_DECL_RE ───────────────────────────────────────────


class TestExportDeclRe:
    def test_matches_export_const(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("export const myValue = 42;")
        assert m is not None
        assert m.group(1) == "myValue"

    def test_matches_export_function(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("export function doStuff() {}")
        assert m is not None
        assert m.group(1) == "doStuff"

    def test_matches_export_class(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("export class MyService {}")
        assert m is not None
        assert m.group(1) == "MyService"

    def test_matches_export_interface(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("export interface UserProps {}")
        assert m is not None
        assert m.group(1) == "UserProps"

    def test_matches_export_type(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("export type UserId = string;")
        assert m is not None
        assert m.group(1) == "UserId"

    def test_matches_export_enum(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("export enum Status { Active, Inactive }")
        assert m is not None
        assert m.group(1) == "Status"

    def test_matches_export_declare(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("export declare function setup(): void;")
        assert m is not None
        assert m.group(1) == "setup"

    def test_no_match_default_export(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("export default function App() {}")
        # "default" does not match any of the keywords in the regex
        assert m is None

    def test_no_match_non_export(self):
        from desloppify.lang.typescript.detectors.exports import EXPORT_DECL_RE
        m = EXPORT_DECL_RE.search("const internalValue = 42;")
        assert m is None


# ── detect_dead_exports ──────────────────────────────────────


class TestDetectDeadExports:
    def test_finds_dead_export(self, tmp_path):
        """An exported symbol not imported anywhere else is dead."""
        from desloppify.lang.typescript.detectors.exports import detect_dead_exports

        _write(tmp_path, "utils.ts", "export const deadHelper = () => null;\n")
        _write(tmp_path, "main.ts", "const x = 1;\n")

        entries, total = detect_dead_exports(tmp_path)
        dead_names = {e["name"] for e in entries}
        assert "deadHelper" in dead_names
        assert total >= 1

    def test_live_export_not_flagged(self, tmp_path):
        """An exported symbol imported by another file is not dead."""
        from desloppify.lang.typescript.detectors.exports import detect_dead_exports

        _write(tmp_path, "utils.ts", "export const liveHelper = () => 1;\n")
        _write(tmp_path, "main.ts", "import { liveHelper } from './utils';\nconsole.log(liveHelper());\n")

        entries, _ = detect_dead_exports(tmp_path)
        dead_names = {e["name"] for e in entries}
        assert "liveHelper" not in dead_names

    def test_index_files_excluded(self, tmp_path):
        """Exports in index.ts/index.tsx files are not flagged (re-exports)."""
        from desloppify.lang.typescript.detectors.exports import detect_dead_exports

        _write(tmp_path, "components/index.ts", "export const Component = 'comp';\n")
        _write(tmp_path, "main.ts", "const x = 1;\n")

        entries, _ = detect_dead_exports(tmp_path)
        dead_names = {e["name"] for e in entries}
        assert "Component" not in dead_names

    def test_short_names_excluded(self, tmp_path):
        """Export names with <=2 characters are excluded (too common for false positives)."""
        from desloppify.lang.typescript.detectors.exports import detect_dead_exports

        _write(tmp_path, "tiny.ts", "export const ab = 1;\n")
        _write(tmp_path, "other.ts", "const x = 1;\n")

        entries, _ = detect_dead_exports(tmp_path)
        dead_names = {e["name"] for e in entries}
        assert "ab" not in dead_names

    def test_empty_directory(self, tmp_path):
        """Empty directory returns no entries."""
        from desloppify.lang.typescript.detectors.exports import detect_dead_exports

        entries, total = detect_dead_exports(tmp_path)
        assert entries == []
        assert total == 0

    def test_multiple_dead_exports_in_one_file(self, tmp_path):
        """Multiple dead exports in one file are all detected."""
        from desloppify.lang.typescript.detectors.exports import detect_dead_exports

        _write(tmp_path, "unused.ts", (
            "export const deadOne = 1;\n"
            "export const deadTwo = 2;\n"
            "export function deadThree() {}\n"
        ))
        _write(tmp_path, "other.ts", "const x = 1;\n")

        entries, total = detect_dead_exports(tmp_path)
        dead_names = {e["name"] for e in entries}
        assert "deadOne" in dead_names
        assert "deadTwo" in dead_names
        assert "deadThree" in dead_names

    def test_export_used_by_multiple_importers(self, tmp_path):
        """Export referenced by multiple files is not flagged."""
        from desloppify.lang.typescript.detectors.exports import detect_dead_exports

        _write(tmp_path, "shared.ts", "export const sharedUtil = () => 1;\n")
        _write(tmp_path, "a.ts", "import { sharedUtil } from './shared';\nsharedUtil();\n")
        _write(tmp_path, "b.ts", "import { sharedUtil } from './shared';\nsharedUtil();\n")

        entries, _ = detect_dead_exports(tmp_path)
        dead_names = {e["name"] for e in entries}
        assert "sharedUtil" not in dead_names
