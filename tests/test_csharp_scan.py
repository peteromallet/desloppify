"""Smoke tests for C# scan pipeline."""

from pathlib import Path

from desloppify.lang.csharp import CSharpConfig
from desloppify.plan import generate_findings


def test_csharp_scan_pipeline_runs_on_fixture():
    path = (Path("tests") / "fixtures" / "csharp" / "simple_app").resolve()
    findings, potentials = generate_findings(path, include_slow=False, lang=CSharpConfig())
    assert isinstance(findings, list)
    assert isinstance(potentials, dict)
    assert "structural" in potentials
