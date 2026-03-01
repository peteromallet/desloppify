"""Direct tests for legacy compat.utils wrappers."""

from __future__ import annotations

from pathlib import Path

import pytest

import desloppify.compat.utils as compat_utils_mod


def test_tool_wrappers_honor_tool_dir_override(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def _fake_compute_tool_hash(*, tool_dir: Path) -> str:
        calls["hash_tool_dir"] = tool_dir
        return "hash-ok"

    def _fake_check_tool_staleness(state: dict, *, tool_dir: Path) -> str:
        calls["stale_state"] = state
        calls["stale_tool_dir"] = tool_dir
        return "stale-ok"

    tool_dir = tmp_path / "compat-tools"
    monkeypatch.setattr(compat_utils_mod._tooling, "compute_tool_hash", _fake_compute_tool_hash)
    monkeypatch.setattr(compat_utils_mod._tooling, "check_tool_staleness", _fake_check_tool_staleness)
    monkeypatch.setattr(compat_utils_mod, "TOOL_DIR", str(tool_dir))

    assert compat_utils_mod.compute_tool_hash() == "hash-ok"  # nosec B101
    assert compat_utils_mod.check_tool_staleness({"x": 1}) == "stale-ok"  # nosec B101
    assert calls["hash_tool_dir"] == tool_dir  # nosec B101
    assert calls["stale_tool_dir"] == tool_dir  # nosec B101
    assert calls["stale_state"] == {"x": 1}  # nosec B101


def test_legacy_discovery_exports_are_available() -> None:
    assert callable(compat_utils_mod.resolve_path)  # nosec B101
    assert callable(compat_utils_mod.find_source_files)  # nosec B101
    assert callable(compat_utils_mod.safe_write_text)  # nosec B101
    assert "compute_tool_hash" in compat_utils_mod.__all__  # nosec B101


def test_unknown_legacy_attr_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        getattr(compat_utils_mod, "definitely_missing_compat_symbol")
