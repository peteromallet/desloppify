"""Tests for TypeScript phase runners."""

from __future__ import annotations

from pathlib import Path

import desloppify.lang.typescript.phases as phases


class _FakeLang:
    large_threshold = 777
    complexity_threshold = 33
    file_finder = staticmethod(lambda _path: [])
    _complexity_map = {}
    _props_threshold = 0
    _zone_map = None


def test_phase_structural_uses_lang_thresholds(monkeypatch, tmp_path: Path):
    """Structural phase should honor language-configured thresholds."""
    captured: dict[str, int] = {}

    def _fake_detect_large(path, *, file_finder, threshold=500):
        captured["large_threshold"] = threshold
        return [], 0

    def _fake_detect_complexity(path, *, signals, file_finder, threshold=15):
        captured["complexity_threshold"] = threshold
        return [], 0

    monkeypatch.setattr("desloppify.detectors.large.detect_large_files", _fake_detect_large)
    monkeypatch.setattr("desloppify.detectors.complexity.detect_complexity", _fake_detect_complexity)
    monkeypatch.setattr("desloppify.detectors.gods.detect_gods", lambda *a, **k: ([], 0))
    monkeypatch.setattr("desloppify.detectors.flat_dirs.detect_flat_dirs", lambda *a, **k: ([], 0))
    monkeypatch.setattr("desloppify.lang.typescript.extractors.extract_ts_components", lambda _p: [])
    monkeypatch.setattr(
        "desloppify.lang.typescript.extractors.detect_passthrough_components",
        lambda _p: [],
    )
    monkeypatch.setattr("desloppify.lang.typescript.detectors.concerns.detect_mixed_concerns", lambda _p: ([], 0))
    monkeypatch.setattr(
        "desloppify.lang.typescript.detectors.props.detect_prop_interface_bloat",
        lambda _p, threshold=14: ([], 0),
    )

    findings, potentials = phases._phase_structural(tmp_path, _FakeLang())

    assert findings == []
    assert potentials["structural"] == 0
    assert captured["large_threshold"] == 777
    assert captured["complexity_threshold"] == 33
