"""Tests for desloppify.lang.typescript.detectors.patterns — pattern anomaly detection."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _set_project_root(tmp_path, monkeypatch):
    """Point PROJECT_ROOT at the tmp directory so file resolution works."""
    monkeypatch.setenv("DESLOPPIFY_ROOT", str(tmp_path))
    import desloppify.utils as utils_mod
    monkeypatch.setattr(utils_mod, "PROJECT_ROOT", tmp_path)
    import desloppify.lang.typescript.detectors.patterns as det_mod
    monkeypatch.setattr(det_mod, "PROJECT_ROOT", tmp_path)
    utils_mod._find_source_files_cached.cache_clear()


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ── _build_census ────────────────────────────────────────────


class TestBuildCensus:
    def test_detects_pattern_usage(self, tmp_path):
        """Census picks up pattern families from file content."""
        from desloppify.lang.typescript.detectors.patterns import _build_census

        _write(tmp_path, "src/tools/editor/main.ts", (
            "const settings = useAutoSaveSettings<Config>();\n"
        ))
        census = _build_census(tmp_path)
        assert len(census) > 0
        # At least one area should have tool_settings family with useAutoSaveSettings
        found = False
        for area, families in census.items():
            if "tool_settings" in families and "useAutoSaveSettings" in families["tool_settings"]:
                found = True
        assert found

    def test_empty_directory(self, tmp_path):
        """Empty directory returns empty census."""
        from desloppify.lang.typescript.detectors.patterns import _build_census

        census = _build_census(tmp_path)
        assert census == {}

    def test_complementary_patterns_tracked(self, tmp_path):
        """Complementary pattern families are included in census."""
        from desloppify.lang.typescript.detectors.patterns import _build_census

        _write(tmp_path, "src/tools/viewer/main.ts", (
            "const result = useQuery({ queryKey: ['data'] });\n"
            "const mutation = useMutation({ mutationFn: save });\n"
        ))
        census = _build_census(tmp_path)
        found_data_fetching = False
        for area, families in census.items():
            if "data_fetching" in families:
                found_data_fetching = True
                assert "useQuery" in families["data_fetching"]
                assert "useMutation" in families["data_fetching"]
        assert found_data_fetching


# ── detect_pattern_anomalies ─────────────────────────────────


class TestDetectPatternAnomalies:
    def test_returns_empty_for_too_few_areas(self, tmp_path):
        """With <5 areas, no anomalies should be reported."""
        from desloppify.lang.typescript.detectors.patterns import detect_pattern_anomalies

        _write(tmp_path, "src/tools/editor/main.ts", (
            "const s = useAutoSaveSettings<Config>();\n"
            "const p = usePersistentToolState<Config>();\n"
        ))
        anomalies, total_areas = detect_pattern_anomalies(tmp_path)
        # With just 1 area, should return empty
        assert anomalies == []

    def test_fragmentation_detected_with_enough_areas(self, tmp_path):
        """Fragmentation is flagged when an area uses >= threshold competing patterns."""
        from desloppify.lang.typescript.detectors.patterns import detect_pattern_anomalies

        # Create 6 areas (need >= 5 for meaningful analysis)
        # Each area is a distinct 2-level path: area{i}/sub/
        # Area 1 uses two competing tool_settings patterns (fragmentation)
        _write(tmp_path, "editor/sub/main.ts", (
            "const s = useAutoSaveSettings<Config>();\n"
            "const p = usePersistentToolState<Config>();\n"
        ))
        # Areas 2-6 use a single pattern (no fragmentation) so they're in the census
        for i in range(2, 7):
            _write(tmp_path, f"area{i}/sub/main.ts", (
                f"const s{i} = useAutoSaveSettings<Config>();\n"
            ))

        anomalies, total_areas = detect_pattern_anomalies(tmp_path)
        assert total_areas >= 5
        # The editor area should have a fragmentation anomaly
        frag = [a for a in anomalies if "editor" in a["area"]]
        assert len(frag) >= 1
        assert frag[0]["pattern_count"] >= 2

    def test_empty_directory(self, tmp_path):
        """Empty directory returns no anomalies."""
        from desloppify.lang.typescript.detectors.patterns import detect_pattern_anomalies

        anomalies, total_areas = detect_pattern_anomalies(tmp_path)
        assert anomalies == []
        assert total_areas == 0

    def test_complementary_patterns_not_flagged(self, tmp_path):
        """Complementary patterns should never produce anomalies."""
        from desloppify.lang.typescript.detectors.patterns import detect_pattern_anomalies

        # Create 6 areas, each using multiple complementary patterns
        for i in range(6):
            _write(tmp_path, f"src/tools/tool{i}/main.ts", (
                "const result = useQuery({ queryKey: ['data'] });\n"
                "const mutation = useMutation({ mutationFn: save });\n"
                "supabase.from('table').select('*');\n"
            ))

        anomalies, total_areas = detect_pattern_anomalies(tmp_path)
        # No anomalies from complementary families (data_fetching is complementary)
        data_anomalies = [a for a in anomalies if a["family"] == "data_fetching"]
        assert len(data_anomalies) == 0

    def test_results_sorted_by_pattern_count(self, tmp_path):
        """Anomalies should be sorted by pattern_count descending."""
        from desloppify.lang.typescript.detectors.patterns import detect_pattern_anomalies

        # Create 6 areas, some with varying fragmentation
        _write(tmp_path, "src/tools/editor/main.ts", (
            "const s = useAutoSaveSettings<Config>();\n"
            "const p = usePersistentToolState<Config>();\n"
            "const t = useToolSettings();\n"
        ))
        _write(tmp_path, "src/tools/viewer/main.ts", (
            "const s = useAutoSaveSettings<Config>();\n"
            "const p = usePersistentToolState<Config>();\n"
        ))
        for i in range(3, 7):
            _write(tmp_path, f"src/tools/tool{i}/main.ts", f"const x = {i};\n")

        anomalies, _ = detect_pattern_anomalies(tmp_path)
        if len(anomalies) >= 2:
            for i in range(len(anomalies) - 1):
                assert anomalies[i]["pattern_count"] >= anomalies[i + 1]["pattern_count"]


# ── PATTERN_FAMILIES structure ───────────────────────────────


class TestPatternFamilies:
    def test_all_families_have_type(self):
        """Every family must declare a type (competing or complementary)."""
        from desloppify.lang.typescript.detectors.patterns import PATTERN_FAMILIES
        for name, family in PATTERN_FAMILIES.items():
            assert "type" in family, f"{name} missing type"
            assert family["type"] in ("competing", "complementary"), f"{name} has invalid type"

    def test_competing_families_have_threshold(self):
        """Competing families must have a fragmentation_threshold."""
        from desloppify.lang.typescript.detectors.patterns import PATTERN_FAMILIES
        for name, family in PATTERN_FAMILIES.items():
            if family["type"] == "competing":
                assert "fragmentation_threshold" in family, f"{name} missing threshold"

    def test_all_families_have_patterns(self):
        """Every family must have at least one pattern."""
        from desloppify.lang.typescript.detectors.patterns import PATTERN_FAMILIES
        for name, family in PATTERN_FAMILIES.items():
            assert "patterns" in family, f"{name} missing patterns"
            assert len(family["patterns"]) >= 1, f"{name} has no patterns"
