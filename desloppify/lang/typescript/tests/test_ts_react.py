"""Tests for desloppify.lang.typescript.detectors.react — React anti-pattern detection."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT at the tmp directory so file resolution works."""
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    import desloppify.utils as utils_mod
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    import desloppify.lang.typescript.detectors.react as det_mod
    monkeypatch.setattr(det_mod, "PROJECT_ROOT", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── detect_state_sync ────────────────────────────────────────


class TestDetectStateSync:
    def test_detects_useeffect_only_calling_setters(self, tmp_path):
        """useEffect whose only statements are useState setters is flagged."""
        from desloppify.lang.typescript.detectors.react import detect_state_sync

        _write(tmp_path, "Component.tsx", (
            "import { useState, useEffect } from 'react';\n"
            "function Component({ value }) {\n"
            "  const [derived, setDerived] = useState(0);\n"
            "  useEffect(() => {\n"
            "    setDerived(value * 2);\n"
            "  }, [value]);\n"
            "  return <div>{derived}</div>;\n"
            "}\n"
        ))
        entries, total_effects = detect_state_sync(tmp_path)
        assert len(entries) == 1
        assert "setDerived" in entries[0]["setters"]
        assert total_effects >= 1

    def test_skips_useeffect_with_non_setter_statements(self, tmp_path):
        """useEffect that does more than just set state should not be flagged."""
        from desloppify.lang.typescript.detectors.react import detect_state_sync

        _write(tmp_path, "Component.tsx", (
            "import { useState, useEffect } from 'react';\n"
            "function Component({ value }) {\n"
            "  const [data, setData] = useState(null);\n"
            "  useEffect(() => {\n"
            "    fetchData(value).then(setData);\n"
            "  }, [value]);\n"
            "  return <div>{data}</div>;\n"
            "}\n"
        ))
        entries, _ = detect_state_sync(tmp_path)
        assert len(entries) == 0

    def test_skips_file_without_usestate(self, tmp_path):
        """Files without useState should not produce any entries."""
        from desloppify.lang.typescript.detectors.react import detect_state_sync

        _write(tmp_path, "Component.tsx", (
            "import { useEffect } from 'react';\n"
            "function Component() {\n"
            "  useEffect(() => {\n"
            "    document.title = 'Hello';\n"
            "  }, []);\n"
            "  return <div>hi</div>;\n"
            "}\n"
        ))
        entries, _ = detect_state_sync(tmp_path)
        assert len(entries) == 0

    def test_multiple_setters_in_one_effect(self, tmp_path):
        """useEffect calling multiple setters from the same component."""
        from desloppify.lang.typescript.detectors.react import detect_state_sync

        _write(tmp_path, "Component.tsx", (
            "import { useState, useEffect } from 'react';\n"
            "function Component({ value }) {\n"
            "  const [a, setA] = useState(0);\n"
            "  const [b, setB] = useState(0);\n"
            "  useEffect(() => {\n"
            "    setA(value);\n"
            "    setB(value * 2);\n"
            "  }, [value]);\n"
            "  return <div>{a} {b}</div>;\n"
            "}\n"
        ))
        entries, _ = detect_state_sync(tmp_path)
        assert len(entries) == 1
        assert set(entries[0]["setters"]) == {"setA", "setB"}

    def test_empty_directory_returns_empty(self, tmp_path):
        """Empty directory returns no entries and zero effects."""
        from desloppify.lang.typescript.detectors.react import detect_state_sync

        entries, total = detect_state_sync(tmp_path)
        assert entries == []
        assert total == 0


# ── detect_context_nesting ───────────────────────────────────


class TestDetectContextNesting:
    def test_detects_deep_provider_nesting(self, tmp_path):
        """Files with >5 nested providers should be flagged."""
        from desloppify.lang.typescript.detectors.react import detect_context_nesting

        providers = [
            "AuthProvider", "ThemeProvider", "QueryProvider",
            "NotificationProvider", "ModalProvider", "ToastProvider",
        ]
        open_tags = "\n".join(f"  <{p}>" for p in providers)
        close_tags = "\n".join(f"  </{p}>" for p in reversed(providers))
        _write(tmp_path, "App.tsx", (
            f"function App() {{\n"
            f"  return (\n"
            f"{open_tags}\n"
            f"    <MainContent />\n"
            f"{close_tags}\n"
            f"  );\n"
            f"}}\n"
        ))
        entries, total_files = detect_context_nesting(tmp_path)
        assert len(entries) == 1
        assert entries[0]["depth"] == 6
        assert total_files == 1

    def test_shallow_nesting_not_flagged(self, tmp_path):
        """Files with <=5 providers should not be flagged."""
        from desloppify.lang.typescript.detectors.react import detect_context_nesting

        _write(tmp_path, "App.tsx", (
            "function App() {\n"
            "  return (\n"
            "    <AuthProvider>\n"
            "      <ThemeProvider>\n"
            "        <MainContent />\n"
            "      </ThemeProvider>\n"
            "    </AuthProvider>\n"
            "  );\n"
            "}\n"
        ))
        entries, _ = detect_context_nesting(tmp_path)
        assert len(entries) == 0

    def test_self_closing_providers_ignored(self, tmp_path):
        """Self-closing Provider tags should not increase nesting depth."""
        from desloppify.lang.typescript.detectors.react import detect_context_nesting

        _write(tmp_path, "App.tsx", (
            "function App() {\n"
            "  return (\n"
            "    <AuthProvider />\n"
            "    <ThemeProvider />\n"
            "    <MainContent />\n"
            "  );\n"
            "}\n"
        ))
        entries, _ = detect_context_nesting(tmp_path)
        assert len(entries) == 0

    def test_results_sorted_by_depth_descending(self, tmp_path):
        """Results should be sorted by depth in descending order."""
        from desloppify.lang.typescript.detectors.react import detect_context_nesting

        providers_6 = ["A1Provider", "A2Provider", "A3Provider",
                       "A4Provider", "A5Provider", "A6Provider"]
        providers_8 = ["B1Provider", "B2Provider", "B3Provider", "B4Provider",
                       "B5Provider", "B6Provider", "B7Provider", "B8Provider"]

        # File with 6 providers
        open6 = "\n".join(f"  <{p}>" for p in providers_6)
        close6 = "\n".join(f"  </{p}>" for p in reversed(providers_6))
        _write(tmp_path, "Small.tsx", f"function Small() {{\n  return (\n{open6}\n    <X />\n{close6}\n  );\n}}\n")

        # File with 8 providers
        open8 = "\n".join(f"  <{p}>" for p in providers_8)
        close8 = "\n".join(f"  </{p}>" for p in reversed(providers_8))
        _write(tmp_path, "Big.tsx", f"function Big() {{\n  return (\n{open8}\n    <X />\n{close8}\n  );\n}}\n")

        entries, _ = detect_context_nesting(tmp_path)
        assert len(entries) == 2
        assert entries[0]["depth"] >= entries[1]["depth"]


# ── detect_hook_return_bloat ─────────────────────────────────


class TestDetectHookReturnBloat:
    def test_detects_hook_with_many_return_fields(self, tmp_path):
        """Hooks returning objects with >12 fields should be flagged."""
        from desloppify.lang.typescript.detectors.react import detect_hook_return_bloat

        fields = ", ".join(f"field{i}" for i in range(15))
        _write(tmp_path, "useMyHook.tsx", (
            f"export function useMyHook() {{\n"
            f"  const field0 = 1;\n"
            f"  const field1 = 2;\n"
            f"  const field2 = 3;\n"
            f"  const field3 = 4;\n"
            f"  const field4 = 5;\n"
            f"  const field5 = 6;\n"
            f"  const field6 = 7;\n"
            f"  const field7 = 8;\n"
            f"  const field8 = 9;\n"
            f"  const field9 = 10;\n"
            f"  const field10 = 11;\n"
            f"  const field11 = 12;\n"
            f"  const field12 = 13;\n"
            f"  const field13 = 14;\n"
            f"  const field14 = 15;\n"
            f"  return {{ {fields} }};\n"
            f"}}\n"
        ))
        entries, total_hooks = detect_hook_return_bloat(tmp_path)
        assert len(entries) == 1
        assert entries[0]["hook"] == "useMyHook"
        assert entries[0]["field_count"] == 15
        assert total_hooks >= 1

    def test_hook_with_few_fields_not_flagged(self, tmp_path):
        """Hooks with <=12 fields should not be flagged."""
        from desloppify.lang.typescript.detectors.react import detect_hook_return_bloat

        _write(tmp_path, "useSmall.tsx", (
            "export function useSmall() {\n"
            "  const a = 1;\n"
            "  const b = 2;\n"
            "  return { a, b };\n"
            "}\n"
        ))
        entries, _ = detect_hook_return_bloat(tmp_path)
        assert len(entries) == 0

    def test_non_hook_function_ignored(self, tmp_path):
        """Functions not named use* should be ignored."""
        from desloppify.lang.typescript.detectors.react import detect_hook_return_bloat

        fields = ", ".join(f"f{i}" for i in range(20))
        _write(tmp_path, "utils.tsx", (
            f"export function buildConfig() {{\n"
            f"  return {{ {fields} }};\n"
            f"}}\n"
        ))
        entries, total_hooks = detect_hook_return_bloat(tmp_path)
        assert len(entries) == 0
        assert total_hooks == 0

    def test_results_sorted_by_field_count_descending(self, tmp_path):
        """Results should be sorted by field_count in descending order."""
        from desloppify.lang.typescript.detectors.react import detect_hook_return_bloat

        fields_13 = ", ".join(f"a{i}" for i in range(13))
        fields_20 = ", ".join(f"b{i}" for i in range(20))

        body_13 = "\n".join(f"  const a{i} = {i};" for i in range(13))
        body_20 = "\n".join(f"  const b{i} = {i};" for i in range(20))

        _write(tmp_path, "useSmaller.tsx", (
            f"export function useSmaller() {{\n{body_13}\n  return {{ {fields_13} }};\n}}\n"
        ))
        _write(tmp_path, "useBigger.tsx", (
            f"export function useBigger() {{\n{body_20}\n  return {{ {fields_20} }};\n}}\n"
        ))
        entries, _ = detect_hook_return_bloat(tmp_path)
        assert len(entries) == 2
        assert entries[0]["field_count"] >= entries[1]["field_count"]


# ── _count_return_fields (helper) ────────────────────────────


class TestCountReturnFields:
    def test_counts_comma_separated_fields(self):
        from desloppify.lang.typescript.detectors.react import _count_return_fields

        body = "function x() {\n  return { a, b, c };\n}"
        count = _count_return_fields(body)
        assert count == 3

    def test_single_field(self):
        from desloppify.lang.typescript.detectors.react import _count_return_fields

        body = "function x() {\n  return { a };\n}"
        count = _count_return_fields(body)
        assert count == 1

    def test_empty_return_object(self):
        from desloppify.lang.typescript.detectors.react import _count_return_fields

        body = "function x() {\n  return {};\n}"
        count = _count_return_fields(body)
        assert count == 0

    def test_no_return_statement(self):
        from desloppify.lang.typescript.detectors.react import _count_return_fields

        body = "function x() {\n  console.log('hi');\n}"
        count = _count_return_fields(body)
        assert count is None

    def test_nested_objects_not_counted(self):
        from desloppify.lang.typescript.detectors.react import _count_return_fields

        body = "function x() {\n  return { a, nested: { x, y }, b };\n}"
        count = _count_return_fields(body)
        # Top-level fields: a, nested: {...}, b = 3 (commas at depth 1)
        assert count == 3
