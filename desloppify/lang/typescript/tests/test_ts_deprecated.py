"""Tests for desloppify.lang.typescript.detectors.deprecated — @deprecated symbol detection."""

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
    import desloppify.lang.typescript.detectors.deprecated as det_mod
    monkeypatch.setattr(det_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(det_mod, "SRC_PATH", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── _extract_deprecated_symbol ───────────────────────────────


class TestExtractDeprecatedSymbol:
    def test_inline_jsdoc_top_level_const(self, tmp_path):
        """Inline JSDoc @deprecated on top-level const is extracted."""
        from desloppify.lang.typescript.detectors.deprecated import _extract_deprecated_symbol

        _write(tmp_path, "old.ts", "/** @deprecated Use newThing instead */ export const oldThing = 1;\n")
        symbol, kind = _extract_deprecated_symbol(
            str(tmp_path / "old.ts"), 1,
            "/** @deprecated Use newThing instead */ export const oldThing = 1;"
        )
        assert symbol == "oldThing"
        assert kind == "top-level"

    def test_inline_jsdoc_property(self, tmp_path):
        """Inline JSDoc @deprecated on a property is extracted as property kind."""
        from desloppify.lang.typescript.detectors.deprecated import _extract_deprecated_symbol

        _write(tmp_path, "types.ts", (
            "interface Config {\n"
            "  /** @deprecated */ oldField?: string;\n"
            "  newField: string;\n"
            "}\n"
        ))
        symbol, kind = _extract_deprecated_symbol(
            str(tmp_path / "types.ts"), 2,
            "  /** @deprecated */ oldField?: string;"
        )
        assert symbol == "oldField"
        assert kind == "property"

    def test_multiline_jsdoc_function(self, tmp_path):
        """Multi-line JSDoc @deprecated on function is extracted."""
        from desloppify.lang.typescript.detectors.deprecated import _extract_deprecated_symbol

        _write(tmp_path, "api.ts", (
            "/**\n"
            " * @deprecated Use newFetch instead\n"
            " */\n"
            "export function oldFetch() { return null; }\n"
        ))
        symbol, kind = _extract_deprecated_symbol(
            str(tmp_path / "api.ts"), 2,
            " * @deprecated Use newFetch instead"
        )
        assert symbol == "oldFetch"
        assert kind == "top-level"

    def test_multiline_jsdoc_interface(self, tmp_path):
        """Multi-line JSDoc @deprecated on interface is extracted."""
        from desloppify.lang.typescript.detectors.deprecated import _extract_deprecated_symbol

        _write(tmp_path, "types.ts", (
            "/**\n"
            " * @deprecated Use NewType instead\n"
            " */\n"
            "export interface OldType {\n"
            "  field: string;\n"
            "}\n"
        ))
        symbol, kind = _extract_deprecated_symbol(
            str(tmp_path / "types.ts"), 2,
            " * @deprecated Use NewType instead"
        )
        assert symbol == "OldType"
        assert kind == "top-level"

    def test_inline_comment_deprecation(self, tmp_path):
        """// @deprecated on same line as a property is extracted."""
        from desloppify.lang.typescript.detectors.deprecated import _extract_deprecated_symbol

        _write(tmp_path, "types.ts", (
            "interface Config {\n"
            "  shotImageEntryId?: string; // @deprecated\n"
            "}\n"
        ))
        symbol, kind = _extract_deprecated_symbol(
            str(tmp_path / "types.ts"), 2,
            "  shotImageEntryId?: string; // @deprecated"
        )
        assert symbol == "shotImageEntryId"
        assert kind == "property"

    def test_returns_none_for_unresolvable(self, tmp_path):
        """Returns (None, 'unknown') when the symbol cannot be determined."""
        from desloppify.lang.typescript.detectors.deprecated import _extract_deprecated_symbol

        _write(tmp_path, "weird.ts", "@deprecated\n\n\n")
        symbol, kind = _extract_deprecated_symbol(
            str(tmp_path / "weird.ts"), 1, "@deprecated"
        )
        assert symbol is None
        assert kind == "unknown"


# ── detect_deprecated ────────────────────────────────────────


class TestDetectDeprecated:
    def test_finds_deprecated_annotations(self, tmp_path):
        """detect_deprecated finds files with @deprecated JSDoc tags."""
        from desloppify.lang.typescript.detectors.deprecated import detect_deprecated

        _write(tmp_path, "old.ts", (
            "/**\n"
            " * @deprecated Use newHelper instead\n"
            " */\n"
            "export function oldHelper() { return null; }\n"
        ))
        entries, count = detect_deprecated(tmp_path)
        assert len(entries) >= 1
        assert entries[0]["symbol"] == "oldHelper"
        assert entries[0]["kind"] == "top-level"

    def test_deduplicates_same_symbol_in_file(self, tmp_path):
        """Same symbol with multiple @deprecated annotations in one file is deduplicated."""
        from desloppify.lang.typescript.detectors.deprecated import detect_deprecated

        _write(tmp_path, "dupes.ts", (
            "/**\n"
            " * @deprecated\n"
            " * @deprecated (duplicate)\n"
            " */\n"
            "export function oldThing() {}\n"
        ))
        entries, _ = detect_deprecated(tmp_path)
        symbols = [e["symbol"] for e in entries if e["symbol"] == "oldThing"]
        assert len(symbols) <= 1

    def test_empty_directory(self, tmp_path):
        """Empty directory returns no entries."""
        from desloppify.lang.typescript.detectors.deprecated import detect_deprecated

        entries, count = detect_deprecated(tmp_path)
        assert entries == []
        assert count == 0

    def test_file_without_deprecated(self, tmp_path):
        """Files without @deprecated produce no entries."""
        from desloppify.lang.typescript.detectors.deprecated import detect_deprecated

        _write(tmp_path, "clean.ts", "export function activeHelper() { return 1; }\n")
        entries, _ = detect_deprecated(tmp_path)
        assert entries == []

    def test_distinguishes_top_level_and_property(self, tmp_path):
        """Entries correctly classify top-level vs property deprecations."""
        from desloppify.lang.typescript.detectors.deprecated import detect_deprecated

        _write(tmp_path, "mixed.ts", (
            "/**\n"
            " * @deprecated Use new API\n"
            " */\n"
            "export function oldFunc() {}\n"
            "\n"
            "interface Config {\n"
            "  /** @deprecated */ oldProp?: string;\n"
            "}\n"
        ))
        entries, _ = detect_deprecated(tmp_path)
        kinds = {e["kind"] for e in entries}
        assert "top-level" in kinds
        assert "property" in kinds
