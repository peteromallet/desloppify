"""Tests for test_coverage discovery and metrics internals."""

from __future__ import annotations

import math
import os
from unittest.mock import patch

from desloppify.engine.detectors.test_coverage import discovery as discovery_mod
from desloppify.engine.detectors.test_coverage.metrics import (
    _loc_weight,
    _quality_risk_level,
    _quality_threshold,
)

# ── _loc_weight ───────────────────────────────────────────


def test_loc_weight_small_file():
    assert _loc_weight(25) == math.sqrt(25)


def test_loc_weight_caps_at_50():
    assert _loc_weight(10000) == 50


def test_loc_weight_boundary_at_2500():
    # sqrt(2500) = 50, exactly at the cap
    assert _loc_weight(2500) == 50


def test_loc_weight_zero():
    assert _loc_weight(0) == 0.0


# ── _quality_risk_level ───────────────────────────────────


def test_quality_risk_high_importers():
    assert _quality_risk_level(loc=50, importer_count=10, complexity=0) == "high"


def test_quality_risk_high_complexity():
    assert _quality_risk_level(loc=50, importer_count=0, complexity=20) == "high"


def test_quality_risk_high_loc():
    assert _quality_risk_level(loc=400, importer_count=0, complexity=0) == "high"


def test_quality_risk_medium_importers():
    assert _quality_risk_level(loc=50, importer_count=4, complexity=0) == "medium"


def test_quality_risk_medium_complexity():
    assert _quality_risk_level(loc=50, importer_count=0, complexity=12) == "medium"


def test_quality_risk_medium_loc():
    assert _quality_risk_level(loc=200, importer_count=0, complexity=0) == "medium"


def test_quality_risk_low():
    assert _quality_risk_level(loc=50, importer_count=1, complexity=5) == "low"


def test_quality_risk_boundary_just_below_high():
    assert _quality_risk_level(loc=399, importer_count=9, complexity=19) == "medium"


def test_quality_risk_boundary_just_below_medium():
    assert _quality_risk_level(loc=199, importer_count=3, complexity=11) == "low"


# ── _quality_threshold ────────────────────────────────────


def test_quality_threshold_high():
    assert _quality_threshold("high") == 0.60


def test_quality_threshold_medium():
    assert _quality_threshold("medium") == 0.50


def test_quality_threshold_low():
    assert _quality_threshold("low") == 0.35


def test_quality_threshold_unknown_returns_low_default():
    assert _quality_threshold("unknown") == 0.35


# ── _normalize_graph_paths ────────────────────────────────


def test_normalize_graph_paths_converts_absolute_to_relative():
    root = str(discovery_mod.PROJECT_ROOT)
    sep = os.sep
    abs_key = root + sep + "src" + sep + "module.py"
    abs_import = root + sep + "src" + sep + "other.py"

    graph = {
        abs_key: {
            "imports": {abs_import},
            "importers": set(),
        }
    }

    result = discovery_mod._normalize_graph_paths(graph)

    expected_key = "src" + sep + "module.py"
    expected_import = "src" + sep + "other.py"
    assert expected_key in result
    assert expected_import in result[expected_key]["imports"]


def test_normalize_graph_paths_skips_already_relative():
    graph = {
        "src/module.py": {
            "imports": {"src/other.py"},
            "importers": set(),
        }
    }

    result = discovery_mod._normalize_graph_paths(graph)

    # Should return the original graph (or identical copy)
    assert "src/module.py" in result
    assert "src/other.py" in result["src/module.py"]["imports"]


def test_normalize_graph_paths_empty_graph():
    assert discovery_mod._normalize_graph_paths({}) == {}


def test_normalize_graph_paths_preserves_non_path_fields():
    root = str(discovery_mod.PROJECT_ROOT)
    sep = os.sep
    abs_key = root + sep + "mod.py"

    graph = {
        abs_key: {
            "imports": set(),
            "importer_count": 5,
            "extra_data": "preserved",
        }
    }

    result = discovery_mod._normalize_graph_paths(graph)

    norm_key = "mod.py"
    assert result[norm_key]["importer_count"] == 5
    assert result[norm_key]["extra_data"] == "preserved"


# ── _no_tests_findings ────────────────────────────────────


def test_no_tests_findings_basic_untested_module(tmp_path):
    f = tmp_path / "big_module.py"
    f.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    filepath = str(f)

    graph = {filepath: {"importer_count": 2}}

    with patch.object(
        discovery_mod, "_has_testable_logic", return_value=True
    ), patch.object(
        discovery_mod, "_is_runtime_entrypoint", return_value=False
    ):
        findings = discovery_mod._no_tests_findings({filepath}, graph, "python")

    assert len(findings) == 1
    finding = findings[0]
    assert finding["file"] == filepath
    assert finding["tier"] == 3
    assert finding["confidence"] == "high"
    assert finding["detail"]["kind"] == "untested_module"
    assert finding["detail"]["importer_count"] == 2


def test_no_tests_findings_critical_by_importers(tmp_path):
    f = tmp_path / "hub.py"
    f.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")
    filepath = str(f)

    graph = {filepath: {"importer_count": 10}}

    with patch.object(
        discovery_mod, "_has_testable_logic", return_value=True
    ), patch.object(
        discovery_mod, "_is_runtime_entrypoint", return_value=False
    ):
        findings = discovery_mod._no_tests_findings({filepath}, graph, "python")

    assert len(findings) == 1
    assert findings[0]["tier"] == 2
    assert findings[0]["detail"]["kind"] == "untested_critical"


def test_no_tests_findings_critical_by_complexity(tmp_path):
    f = tmp_path / "complex.py"
    f.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")
    filepath = str(f)

    graph = {filepath: {"importer_count": 0}}
    complexity_map = {filepath: 25.0}

    with patch.object(
        discovery_mod, "_has_testable_logic", return_value=True
    ), patch.object(
        discovery_mod, "_is_runtime_entrypoint", return_value=False
    ):
        findings = discovery_mod._no_tests_findings(
            {filepath}, graph, "python", complexity_map=complexity_map
        )

    assert len(findings) == 1
    assert findings[0]["tier"] == 2
    assert findings[0]["detail"]["kind"] == "untested_critical"
    assert findings[0]["detail"]["complexity_score"] == 25.0


def test_no_tests_findings_runtime_entrypoint(tmp_path):
    f = tmp_path / "index.ts"
    f.write_text("\n".join(f"line {i}" for i in range(50)) + "\n")
    filepath = str(f)

    graph = {filepath: {"importer_count": 0}}

    with patch.object(
        discovery_mod, "_has_testable_logic", return_value=True
    ), patch.object(
        discovery_mod, "_is_runtime_entrypoint", return_value=True
    ):
        findings = discovery_mod._no_tests_findings({filepath}, graph, "typescript")

    assert len(findings) == 1
    assert findings[0]["name"] == "runtime_entrypoint_no_direct_tests"
    assert findings[0]["tier"] == 3
    assert findings[0]["confidence"] == "medium"
    assert "entrypoint" in findings[0]["summary"].lower()


def test_no_tests_findings_sorted_by_loc_descending(tmp_path):
    files = []
    for i, loc in enumerate([10, 200, 50]):
        f = tmp_path / f"mod_{i}.py"
        f.write_text("\n".join(f"line {j}" for j in range(loc)) + "\n")
        files.append(str(f))

    graph = {f: {"importer_count": 0} for f in files}

    with patch.object(
        discovery_mod, "_has_testable_logic", return_value=True
    ), patch.object(
        discovery_mod, "_is_runtime_entrypoint", return_value=False
    ):
        findings = discovery_mod._no_tests_findings(set(files), graph, "python")

    locs = [finding["detail"]["loc"] for finding in findings]
    assert locs == sorted(locs, reverse=True)


def test_no_tests_findings_empty_scorable():
    with patch.object(
        discovery_mod, "_has_testable_logic", return_value=True
    ), patch.object(
        discovery_mod, "_is_runtime_entrypoint", return_value=False
    ):
        findings = discovery_mod._no_tests_findings(set(), {}, "python")

    assert findings == []


def test_no_tests_findings_capped_at_max_entries(tmp_path):
    files = set()
    graph = {}
    for i in range(60):
        f = tmp_path / f"mod_{i}.py"
        f.write_text("\n".join(f"line {j}" for j in range(20)) + "\n")
        filepath = str(f)
        files.add(filepath)
        graph[filepath] = {"importer_count": 0}

    with patch.object(
        discovery_mod, "_has_testable_logic", return_value=True
    ), patch.object(
        discovery_mod, "_is_runtime_entrypoint", return_value=False
    ):
        findings = discovery_mod._no_tests_findings(files, graph, "python")

    assert len(findings) <= discovery_mod._MAX_NO_TESTS_ENTRIES
