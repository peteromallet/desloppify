"""Tests for framework phase builder helpers and treesitter phase factories."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from desloppify.languages._framework.base.phase_builders import (
    detector_phase_boilerplate_duplication,
    detector_phase_duplicates,
    detector_phase_security,
    detector_phase_signature,
    detector_phase_subjective_review,
    detector_phase_test_coverage,
    shared_subjective_duplicates_tail,
)
from desloppify.languages._framework.base.types import DetectorPhase

# ── Individual factory functions ──────────────────────────────


def test_detector_phase_test_coverage_returns_correct_label():
    phase = detector_phase_test_coverage()
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "Test coverage"
    assert phase.slow is False


def test_detector_phase_security_returns_correct_label():
    phase = detector_phase_security()
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "Security"
    assert phase.slow is False


def test_detector_phase_signature_returns_correct_label():
    phase = detector_phase_signature()
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "Signature analysis"
    assert phase.slow is False


def test_detector_phase_subjective_review_returns_correct_label():
    phase = detector_phase_subjective_review()
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "Subjective review"
    assert phase.slow is False


def test_detector_phase_duplicates_is_slow():
    phase = detector_phase_duplicates()
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "Duplicates"
    assert phase.slow is True


def test_detector_phase_boilerplate_duplication_is_slow():
    phase = detector_phase_boilerplate_duplication()
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "Boilerplate duplication"
    assert phase.slow is True


# ── All factory functions produce callable run ────────────────


def test_all_factories_produce_callable_run():
    factories = [
        detector_phase_test_coverage,
        detector_phase_security,
        detector_phase_signature,
        detector_phase_subjective_review,
        detector_phase_duplicates,
        detector_phase_boilerplate_duplication,
    ]
    for factory in factories:
        phase = factory()
        assert callable(phase.run), f"{factory.__name__} produced non-callable run"


# ── shared_subjective_duplicates_tail ─────────────────────────


def test_shared_tail_default_has_three_phases():
    """Default tail: subjective review, boilerplate duplication, duplicates."""
    phases = shared_subjective_duplicates_tail()
    assert len(phases) == 3
    assert phases[0].label == "Subjective review"
    assert phases[1].label == "Boilerplate duplication"
    assert phases[2].label == "Duplicates"


def test_shared_tail_with_pre_duplicates_inserts_in_middle():
    """Extra phases go between subjective review and boilerplate duplication."""
    custom = DetectorPhase("Custom detector", lambda p, lang: ([], {}))
    phases = shared_subjective_duplicates_tail(pre_duplicates=[custom])
    assert len(phases) == 4
    assert phases[0].label == "Subjective review"
    assert phases[1].label == "Custom detector"
    assert phases[2].label == "Boilerplate duplication"
    assert phases[3].label == "Duplicates"


def test_shared_tail_with_multiple_pre_duplicates():
    """Multiple pre_duplicates are inserted in order."""
    custom_a = DetectorPhase("Alpha", lambda p, lang: ([], {}))
    custom_b = DetectorPhase("Beta", lambda p, lang: ([], {}))
    phases = shared_subjective_duplicates_tail(pre_duplicates=[custom_a, custom_b])
    assert len(phases) == 5
    labels = [p.label for p in phases]
    assert labels == [
        "Subjective review",
        "Alpha",
        "Beta",
        "Boilerplate duplication",
        "Duplicates",
    ]


def test_shared_tail_empty_pre_duplicates_same_as_default():
    """Empty list for pre_duplicates behaves like None."""
    phases = shared_subjective_duplicates_tail(pre_duplicates=[])
    assert len(phases) == 3


def test_shared_tail_slow_flags():
    """Last two phases (boilerplate duplication + duplicates) are slow."""
    phases = shared_subjective_duplicates_tail()
    assert phases[0].slow is False  # subjective review
    assert phases[1].slow is True   # boilerplate duplication
    assert phases[2].slow is True   # duplicates


# ── Treesitter phase factories ────────────────────────────────


def test_make_ast_smells_phase_label():
    from desloppify.languages._framework.treesitter.phases import make_ast_smells_phase

    spec = MagicMock()
    phase = make_ast_smells_phase(spec)
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "AST smells"
    assert phase.slow is False


def test_make_cohesion_phase_label():
    from desloppify.languages._framework.treesitter.phases import make_cohesion_phase

    spec = MagicMock()
    phase = make_cohesion_phase(spec)
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "Responsibility cohesion"


def test_make_unused_imports_phase_label():
    from desloppify.languages._framework.treesitter.phases import (
        make_unused_imports_phase,
    )

    spec = MagicMock()
    phase = make_unused_imports_phase(spec)
    assert isinstance(phase, DetectorPhase)
    assert phase.label == "Unused imports"


def test_make_ast_smells_phase_run_with_no_findings():
    """Run an AST smells phase when detectors return empty results."""
    from desloppify.languages._framework.treesitter.phases import make_ast_smells_phase

    spec = MagicMock()
    phase = make_ast_smells_phase(spec)

    mock_lang = MagicMock()
    mock_lang.file_finder.return_value = ["/tmp/test.cs"]

    with patch(
        "desloppify.languages._framework.treesitter._smells.detect_empty_catches",
        return_value=[],
    ), patch(
        "desloppify.languages._framework.treesitter._smells.detect_unreachable_code",
        return_value=[],
    ):
        findings, potentials = phase.run("/tmp", mock_lang)
    assert findings == []
    assert potentials == {}


def test_make_ast_smells_phase_run_with_catches_and_unreachable():
    """Run an AST smells phase that finds empty catches and unreachable code."""
    from desloppify.languages._framework.treesitter.phases import make_ast_smells_phase

    spec = MagicMock()
    phase = make_ast_smells_phase(spec)

    mock_lang = MagicMock()
    mock_lang.file_finder.return_value = ["/tmp/test.cs"]

    catches = [{"file": "/tmp/test.cs", "line": 10, "type": "catch"}]
    unreachable = [{"file": "/tmp/test.cs", "line": 20, "after": "return"}]

    with patch(
        "desloppify.languages._framework.treesitter._smells.detect_empty_catches",
        return_value=catches,
    ), patch(
        "desloppify.languages._framework.treesitter._smells.detect_unreachable_code",
        return_value=unreachable,
    ):
        findings, potentials = phase.run("/tmp", mock_lang)

    assert len(findings) == 2
    assert potentials["empty_catch"] == 1
    assert potentials["unreachable_code"] == 1
    # Check finding content
    assert findings[0]["detector"] == "smells"
    assert "empty_catch" in findings[0]["id"]
    assert findings[1]["detector"] == "smells"
    assert "unreachable_code" in findings[1]["id"]


def test_make_cohesion_phase_run_with_entries():
    """Run a cohesion phase that finds low-cohesion files."""
    from desloppify.languages._framework.treesitter.phases import make_cohesion_phase

    spec = MagicMock()
    phase = make_cohesion_phase(spec)

    mock_lang = MagicMock()
    mock_lang.file_finder.return_value = ["/tmp/big_file.cs"]

    entries = [{
        "file": "/tmp/big_file.cs",
        "families": ["network", "database", "ui", "auth"],
        "component_count": 4,
        "function_count": 20,
    }]

    with patch(
        "desloppify.languages._framework.treesitter._cohesion.detect_responsibility_cohesion",
        return_value=(entries, 1),
    ):
        findings, potentials = phase.run("/tmp", mock_lang)

    assert len(findings) == 1
    assert potentials["responsibility_cohesion"] == 1
    assert findings[0]["detector"] == "responsibility_cohesion"
    assert "disconnected function clusters" in findings[0]["summary"]
    assert findings[0]["detail"]["cluster_count"] == 4
    assert findings[0]["detail"]["family"] == "network, database, ui, auth"


def test_make_unused_imports_phase_run_with_entries():
    """Run an unused imports phase that finds unused imports."""
    from desloppify.languages._framework.treesitter.phases import (
        make_unused_imports_phase,
    )

    spec = MagicMock()
    phase = make_unused_imports_phase(spec)

    mock_lang = MagicMock()
    mock_lang.file_finder.return_value = ["/tmp/test.go"]

    entries = [
        {"file": "/tmp/test.go", "line": 3, "name": "fmt"},
        {"file": "/tmp/test.go", "line": 4, "name": "os"},
    ]

    with patch(
        "desloppify.languages._framework.treesitter._unused_imports.detect_unused_imports",
        return_value=entries,
    ):
        findings, potentials = phase.run("/tmp", mock_lang)

    assert len(findings) == 2
    assert potentials["unused_imports"] == 2
    assert findings[0]["detector"] == "unused"
    assert "fmt" in findings[0]["summary"]
    assert "os" in findings[1]["summary"]


def test_all_treesitter_phases_returns_empty_when_unavailable():
    """When tree-sitter is not installed, return empty list."""
    with patch(
        "desloppify.languages._framework.treesitter.is_available",
        return_value=False,
    ):
        from desloppify.languages._framework.treesitter.phases import (
            all_treesitter_phases,
        )
        result = all_treesitter_phases("go")
    assert result == []


def test_all_treesitter_phases_returns_empty_for_unknown_spec():
    """When spec_name is not in TREESITTER_SPECS, return empty list."""
    with patch(
        "desloppify.languages._framework.treesitter.is_available",
        return_value=True,
    ), patch(
        "desloppify.languages._framework.treesitter._specs.TREESITTER_SPECS",
        {},
    ):
        from desloppify.languages._framework.treesitter.phases import (
            all_treesitter_phases,
        )
        result = all_treesitter_phases("nonexistent_lang")
    assert result == []


def test_all_treesitter_phases_includes_imports_when_import_query():
    """When spec has import_query, result includes unused imports phase."""
    mock_spec = MagicMock()
    mock_spec.function_query = "(some_query)"
    mock_spec.import_query = "(import_query)"

    with patch(
        "desloppify.languages._framework.treesitter.is_available",
        return_value=True,
    ), patch(
        "desloppify.languages._framework.treesitter._specs.TREESITTER_SPECS",
        {"test_lang": mock_spec},
    ):
        from desloppify.languages._framework.treesitter.phases import (
            all_treesitter_phases,
        )
        result = all_treesitter_phases("test_lang")

    assert len(result) == 3
    labels = [p.label for p in result]
    assert "AST smells" in labels
    assert "Responsibility cohesion" in labels
    assert "Unused imports" in labels


def test_all_treesitter_phases_excludes_imports_when_no_import_query():
    """When spec has no import_query, result excludes unused imports phase."""
    mock_spec = MagicMock()
    mock_spec.function_query = "(some_query)"
    mock_spec.import_query = ""

    with patch(
        "desloppify.languages._framework.treesitter.is_available",
        return_value=True,
    ), patch(
        "desloppify.languages._framework.treesitter._specs.TREESITTER_SPECS",
        {"test_lang": mock_spec},
    ):
        from desloppify.languages._framework.treesitter.phases import (
            all_treesitter_phases,
        )
        result = all_treesitter_phases("test_lang")

    assert len(result) == 2
    labels = [p.label for p in result]
    assert "AST smells" in labels
    assert "Responsibility cohesion" in labels
    assert "Unused imports" not in labels
