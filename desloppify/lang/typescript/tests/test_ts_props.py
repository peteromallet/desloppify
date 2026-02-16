"""Tests for desloppify.lang.typescript.detectors.props — prop interface bloat detection."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT at the tmp directory."""
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    import desloppify.utils as utils_mod
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    import desloppify.lang.typescript.detectors.props as det_mod
    monkeypatch.setattr(det_mod, "PROJECT_ROOT", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── detect_prop_interface_bloat ──────────────────────────────


class TestDetectPropInterfaceBloat:
    def test_detects_bloated_props_interface(self, tmp_path):
        """Interface with >14 props is flagged."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  prop{i}: string;" for i in range(20))
        _write(tmp_path, "Component.tsx", (
            f"interface ComponentProps {{\n{props}\n}}\n"
        ))
        entries, total = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 1
        assert entries[0]["interface"] == "ComponentProps"
        assert entries[0]["prop_count"] == 20
        assert entries[0]["kind"] == "props"
        assert total >= 1

    def test_small_interface_not_flagged(self, tmp_path):
        """Interface with <=14 props is not flagged."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  prop{i}: string;" for i in range(5))
        _write(tmp_path, "Component.tsx", (
            f"interface ButtonProps {{\n{props}\n}}\n"
        ))
        entries, total = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 0
        assert total >= 1

    def test_context_interface_detected(self, tmp_path):
        """Context-related interfaces are also checked."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  field{i}: string;" for i in range(16))
        _write(tmp_path, "context.tsx", (
            f"interface AppContextValue {{\n{props}\n}}\n"
        ))
        entries, _ = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 1
        assert entries[0]["kind"] == "context"

    def test_state_interface_detected(self, tmp_path):
        """State-related interfaces are also checked."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  field{i}: number;" for i in range(16))
        _write(tmp_path, "store.tsx", (
            f"interface EditorState {{\n{props}\n}}\n"
        ))
        entries, _ = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 1
        assert entries[0]["kind"] == "state"

    def test_non_props_interface_ignored(self, tmp_path):
        """Interfaces not matching Props/Context/State suffixes are ignored."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  field{i}: string;" for i in range(20))
        _write(tmp_path, "types.tsx", (
            f"interface UserData {{\n{props}\n}}\n"
        ))
        entries, total = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 0

    def test_type_alias_with_props_suffix(self, tmp_path):
        """Type aliases with Props suffix are also detected."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  prop{i}: string;" for i in range(16))
        _write(tmp_path, "Component.tsx", (
            f"type WidgetProps = {{\n{props}\n}};\n"
        ))
        entries, _ = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 1
        assert entries[0]["interface"] == "WidgetProps"

    def test_export_interface_detected(self, tmp_path):
        """Exported interfaces are also detected."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  prop{i}: string;" for i in range(16))
        _write(tmp_path, "Component.tsx", (
            f"export interface CardProps {{\n{props}\n}}\n"
        ))
        entries, _ = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 1
        assert entries[0]["interface"] == "CardProps"

    def test_empty_directory(self, tmp_path):
        """Empty directory returns no entries."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        entries, total = detect_prop_interface_bloat(tmp_path)
        assert entries == []
        assert total == 0

    def test_comments_not_counted_as_props(self, tmp_path):
        """Comment lines inside interfaces are not counted as props."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        real_props = "\n".join(f"  prop{i}: string;" for i in range(10))
        comments = "\n".join(f"  // comment line {i}" for i in range(10))
        _write(tmp_path, "Component.tsx", (
            f"interface TestProps {{\n{real_props}\n{comments}\n}}\n"
        ))
        entries, _ = detect_prop_interface_bloat(tmp_path)
        # Should only count the 10 real props, not the 10 comments
        assert len(entries) == 0

    def test_results_sorted_by_prop_count_descending(self, tmp_path):
        """Results sorted by prop_count in descending order."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props_15 = "\n".join(f"  p{i}: string;" for i in range(15))
        props_20 = "\n".join(f"  p{i}: string;" for i in range(20))
        _write(tmp_path, "small.tsx", f"interface SmallProps {{\n{props_15}\n}}\n")
        _write(tmp_path, "big.tsx", f"interface BigProps {{\n{props_20}\n}}\n")

        entries, _ = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 2
        assert entries[0]["prop_count"] >= entries[1]["prop_count"]

    def test_context_type_suffix(self, tmp_path):
        """Interfaces with ContextType suffix are detected."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  field{i}: string;" for i in range(16))
        _write(tmp_path, "ctx.tsx", (
            f"interface MyContextType {{\n{props}\n}}\n"
        ))
        entries, _ = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 1
        assert entries[0]["kind"] == "context"

    def test_state_value_suffix(self, tmp_path):
        """Interfaces with StateValue suffix are detected."""
        from desloppify.lang.typescript.detectors.props import detect_prop_interface_bloat

        props = "\n".join(f"  field{i}: string;" for i in range(16))
        _write(tmp_path, "store.tsx", (
            f"interface FormStateValue {{\n{props}\n}}\n"
        ))
        entries, _ = detect_prop_interface_bloat(tmp_path)
        assert len(entries) == 1
        assert entries[0]["kind"] == "state"
