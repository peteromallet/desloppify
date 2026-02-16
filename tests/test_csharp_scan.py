"""Smoke tests for C# scan pipeline."""

from collections import Counter
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from desloppify.lang.csharp import CSharpConfig
from desloppify.lang.csharp.phases import _apply_csharp_actionability_gates
from desloppify.plan import generate_findings


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


def test_csharp_signal_rich_fixture_emits_meaningful_findings(tmp_path):
    fixture = (Path("tests") / "fixtures" / "csharp" / "signal_rich").resolve()
    path = (tmp_path / "signal_rich").resolve()
    shutil.copytree(fixture, path)
    config = CSharpConfig()
    config.get_area = _signal_rich_area
    findings, _potentials = generate_findings(
        path,
        include_slow=False,
        lang=config,
        profile="objective",
    )

    by_detector = Counter(f["detector"] for f in findings)
    assert by_detector["security"] >= 1
    assert by_detector["single_use"] >= 1
    assert by_detector["orphaned"] >= 1
    assert by_detector["structural"] >= 1

    orphan = next(f for f in findings if f["detector"] == "orphaned")
    assert orphan["confidence"] == "medium"
    assert orphan["detail"]["corroboration_count"] >= 2
    assert "corroboration_min_required" in orphan["detail"]
    assert "import_count" in orphan["detail"]
    assert "complexity_score" in orphan["detail"]

    single_use = next(f for f in findings if f["detector"] == "single_use")
    assert single_use["confidence"] == "low"
    assert "corroboration_count" in single_use["detail"]
    assert "corroboration_min_required" in single_use["detail"]
    assert "import_count" in single_use["detail"]


def test_csharp_signal_rich_fixture_findings_are_deterministic(tmp_path):
    fixture = (Path("tests") / "fixtures" / "csharp" / "signal_rich").resolve()
    path = (tmp_path / "signal_rich").resolve()
    shutil.copytree(fixture, path)

    cfg_a = CSharpConfig()
    cfg_a.get_area = _signal_rich_area
    findings_a, _ = generate_findings(path, include_slow=False, lang=cfg_a, profile="objective")

    cfg_b = CSharpConfig()
    cfg_b.get_area = _signal_rich_area
    findings_b, _ = generate_findings(path, include_slow=False, lang=cfg_b, profile="objective")

    def _stable_projection(findings: list[dict]) -> list[tuple]:
        return sorted(
            (
                f["id"],
                f["detector"],
                f["file"],
                f["tier"],
                f["confidence"],
                f["summary"],
            )
            for f in findings
        )

    assert _stable_projection(findings_a) == _stable_projection(findings_b)


def test_csharp_actionability_gate_downgrades_without_corroboration():
    settings = {}
    lang = SimpleNamespace(
        _complexity_map={},
        large_threshold=500,
        complexity_threshold=20,
        runtime_setting=lambda key, default=None: settings.get(key, default),
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
    settings = {}
    lang = SimpleNamespace(
        _complexity_map={"src/Foo.cs": 25},
        large_threshold=500,
        complexity_threshold=20,
        runtime_setting=lambda key, default=None: settings.get(key, default),
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


def test_csharp_actionability_gate_respects_configurable_signal_minimum():
    settings = {
        "high_fanout_threshold": 7,
        "corroboration_min_signals": 3,
    }
    lang = SimpleNamespace(
        _complexity_map={"src/Foo.cs": 25},
        large_threshold=500,
        complexity_threshold=20,
        runtime_setting=lambda key, default=None: settings.get(key, default),
    )
    findings = [{
        "detector": "single_use",
        "file": "src/Foo.cs",
        "confidence": "medium",
        "detail": {"loc": 650},
    }]
    entries = [{"file": "src/Foo.cs", "loc": 650, "import_count": 6}]

    _apply_csharp_actionability_gates(findings, entries, lang)

    assert findings[0]["detail"]["corroboration_count"] == 2
    assert findings[0]["detail"]["corroboration_min_required"] == 3
    assert findings[0]["confidence"] == "low"


def test_csharp_scan_uses_roslyn_cmd_override_from_lang_config(monkeypatch):
    path = (Path("tests") / "fixtures" / "csharp" / "simple_app").resolve()
    program = (path / "Program.cs").resolve()
    greeter = (path / "Services" / "Greeter.cs").resolve()
    payload = json.dumps(
        {
            "files": [
                {"file": str(program), "imports": [str(greeter)]},
                {"file": str(greeter), "imports": []},
            ]
        }
    ).encode("utf-8")

    class _Proc:
        returncode = 0
        stdout = payload
        stderr = b""

    captured: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr("desloppify.lang.csharp.detectors.deps.subprocess.run", _fake_run)

    config = CSharpConfig()
    config.set_runtime_context(options={"roslyn_cmd": "override-roslyn --json"})
    findings, potentials = generate_findings(path, include_slow=False, lang=config, profile="objective")

    assert findings is not None
    assert "cycles" in potentials
    cmd = captured["args"][0]
    assert isinstance(cmd, list)
    assert cmd[0] == "override-roslyn"
