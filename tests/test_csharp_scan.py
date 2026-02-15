"""Smoke tests for C# scan pipeline."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from desloppify.lang.csharp import CSharpConfig
from desloppify.lang.csharp.phases import _apply_csharp_actionability_gates
from desloppify.plan import generate_findings
from desloppify.utils import rel


def _production_zone_overrides(path: Path, config: CSharpConfig) -> dict[str, str]:
    """Treat fixture files as production so detectors are not zone-suppressed."""
    return {rel(filepath): "production" for filepath in config.file_finder(path)}


def _signal_rich_area(filepath: str) -> str:
    """Area mapper that ignores the tests/fixtures prefix."""
    normalized = filepath.replace("\\", "/")
    marker = "/signal_rich/"
    if marker in normalized:
        local = normalized.split(marker, 1)[1]
        return local.rsplit("/", 1)[0] if "/" in local else local
    return normalized


def test_csharp_scan_pipeline_runs_on_fixture():
    path = (Path("tests") / "fixtures" / "csharp" / "simple_app").resolve()
    findings, potentials = generate_findings(path, include_slow=False, lang=CSharpConfig())
    assert isinstance(findings, list)
    assert isinstance(potentials, dict)
    assert "structural" in potentials


def test_csharp_objective_profile_skips_subjective_review():
    path = (Path("tests") / "fixtures" / "csharp" / "simple_app").resolve()
    _, potentials = generate_findings(path, include_slow=False, lang=CSharpConfig(), profile="objective")
    assert "subjective_review" not in potentials


def test_csharp_full_profile_keeps_subjective_review():
    path = (Path("tests") / "fixtures" / "csharp" / "simple_app").resolve()
    _, potentials = generate_findings(path, include_slow=False, lang=CSharpConfig(), profile="full")
    assert "subjective_review" in potentials


def test_csharp_signal_rich_fixture_emits_meaningful_findings():
    path = (Path("tests") / "fixtures" / "csharp" / "signal_rich").resolve()
    config = CSharpConfig()
    config.get_area = _signal_rich_area
    zone_overrides = _production_zone_overrides(path, config)
    findings, _potentials = generate_findings(
        path,
        include_slow=False,
        lang=config,
        profile="objective",
        zone_overrides=zone_overrides,
    )

    by_detector = Counter(f["detector"] for f in findings)
    assert by_detector["security"] >= 1
    assert by_detector["single_use"] >= 1
    assert by_detector["orphaned"] >= 1
    assert by_detector["structural"] >= 1

    orphan = next(f for f in findings if f["detector"] == "orphaned")
    assert orphan["confidence"] == "medium"
    assert orphan["detail"]["corroboration_count"] >= 2

    single_use = next(f for f in findings if f["detector"] == "single_use")
    assert single_use["confidence"] == "low"


def test_csharp_actionability_gate_downgrades_without_corroboration():
    lang = SimpleNamespace(
        _complexity_map={},
        large_threshold=500,
        complexity_threshold=20,
    )
    findings = [{
        "detector": "orphaned",
        "file": "src/Foo.cs",
        "confidence": "medium",
        "detail": {"loc": 80},
    }]
    entries = [{"file": "src/Foo.cs", "loc": 80, "import_count": 1}]

    _apply_csharp_actionability_gates(findings, entries, lang)

    assert findings[0]["confidence"] == "low"
    assert findings[0]["detail"]["corroboration_count"] == 0


def test_csharp_actionability_gate_keeps_medium_with_multiple_signals():
    lang = SimpleNamespace(
        _complexity_map={"src/Foo.cs": 25},
        large_threshold=500,
        complexity_threshold=20,
    )
    findings = [{
        "detector": "single_use",
        "file": "src/Foo.cs",
        "confidence": "medium",
        "detail": {"loc": 650},
    }]
    entries = [{"file": "src/Foo.cs", "loc": 650, "import_count": 6}]

    _apply_csharp_actionability_gates(findings, entries, lang)

    assert findings[0]["confidence"] == "medium"
    assert findings[0]["detail"]["corroboration_count"] == 3
