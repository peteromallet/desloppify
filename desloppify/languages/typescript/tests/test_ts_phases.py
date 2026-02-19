"""Tests for TypeScript phase runners."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.languages.typescript.phases as phases


class _FakeLang:
    large_threshold = 777
    complexity_threshold = 33
    file_finder = staticmethod(lambda _path: [])
    complexity_map = {}
    props_threshold = 0
    zone_map = None


class _FakeCouplingLang:
    extensions = [".ts", ".tsx"]
    entry_patterns = ["main.ts", "/tests/"]
    barrel_names = {"index.ts", "index.tsx"}
    file_finder = staticmethod(lambda _path: [])
    zone_map = None
    get_area = staticmethod(lambda _f: "area")


def test_phase_structural_uses_lang_thresholds(monkeypatch, tmp_path: Path):
    """Structural phase should honor language-configured thresholds."""
    captured: dict[str, int] = {}

    def _fake_detect_large(path, *, file_finder, threshold=500):
        captured["large_threshold"] = threshold
        return [], 0

    def _fake_detect_complexity(path, *, signals, file_finder, threshold=15):
        captured["complexity_threshold"] = threshold
        return [], 0

    monkeypatch.setattr(
        "desloppify.engine.detectors.large.detect_large_files", _fake_detect_large
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.complexity.detect_complexity", _fake_detect_complexity
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.gods.detect_gods", lambda *a, **k: ([], 0)
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.flat_dirs.detect_flat_dirs", lambda *a, **k: ([], 0)
    )
    monkeypatch.setattr(
        "desloppify.languages.typescript.extractors.extract_ts_components", lambda _p: []
    )
    monkeypatch.setattr(
        "desloppify.languages.typescript.extractors.detect_passthrough_components",
        lambda _p: [],
    )
    monkeypatch.setattr(
        "desloppify.languages.typescript.detectors.concerns.detect_mixed_concerns",
        lambda _p: ([], 0),
    )
    monkeypatch.setattr(
        "desloppify.languages.typescript.detectors.props.detect_prop_interface_bloat",
        lambda _p, threshold=14: ([], 0),
    )

    findings, potentials = phases._phase_structural(tmp_path, _FakeLang())

    assert findings == []
    assert isinstance(findings, list)
    assert isinstance(potentials, dict)
    assert potentials["structural"] == 0
    assert {"structural", "props", "flat_dirs"}.issubset(set(potentials.keys()))
    assert len(captured) == 2
    assert set(captured.keys()) == {"large_threshold", "complexity_threshold"}
    assert captured["large_threshold"] == 777
    assert captured["complexity_threshold"] == 33


def test_phase_coupling_passes_orphaned_options(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "desloppify.languages.typescript.detectors.deps.build_dep_graph",
        lambda _path: {},
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.single_use.detect_single_use_abstractions",
        lambda _path, _graph, barrel_names: ([], 0),
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.coupling.detect_coupling_violations",
        lambda _path, _graph, shared_prefix, tools_prefix: ([], 0),
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.coupling.detect_cross_tool_imports",
        lambda _path, _graph, tools_prefix: ([], 0),
    )
    monkeypatch.setattr(
        "desloppify.languages.typescript.phases._make_boundary_findings",
        lambda single_entries, path, graph, lang, shared_prefix, tools_prefix: ([], 0),
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.graph.detect_cycles",
        lambda _graph: ([], 0),
    )

    def _fake_detect_orphaned_files(path, graph, extensions, options=None):
        captured["extensions"] = extensions
        captured["options"] = options
        return [], 0

    monkeypatch.setattr(
        "desloppify.engine.detectors.orphaned.detect_orphaned_files",
        _fake_detect_orphaned_files,
    )
    monkeypatch.setattr(
        "desloppify.languages.typescript.detectors.facade.detect_reexport_facades",
        lambda _graph: ([], 0),
    )
    monkeypatch.setattr(
        "desloppify.languages.typescript.detectors.patterns.detect_pattern_anomalies_result",
        lambda _path: SimpleNamespace(entries=[], population_size=0),
    )
    monkeypatch.setattr(
        "desloppify.engine.detectors.naming.detect_naming_inconsistencies",
        lambda _path, file_finder, skip_names, skip_dirs: ([], 0),
    )

    findings, potentials = phases._phase_coupling(tmp_path, _FakeCouplingLang())

    assert findings == []
    assert "orphaned" in potentials
    options = captured.get("options")
    assert options is not None
    assert isinstance(options, phases.orphaned_detector_mod.OrphanedDetectionOptions)
    assert options.extra_entry_patterns == _FakeCouplingLang.entry_patterns
    assert options.extra_barrel_names == _FakeCouplingLang.barrel_names
    assert callable(options.dynamic_import_finder)
    assert callable(options.alias_resolver)
