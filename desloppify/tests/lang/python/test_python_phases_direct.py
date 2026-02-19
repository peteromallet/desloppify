"""Direct tests for Python phase module exports/constants."""

from __future__ import annotations

from pathlib import Path

import desloppify.languages.python.phases as phases


def test_python_phase_constant_shapes():
    assert isinstance(phases.PY_COMPLEXITY_SIGNALS, list)
    assert isinstance(phases.PY_GOD_RULES, list)
    assert "cli.py" in phases.PY_ENTRY_PATTERNS
    assert "__init__.py" in phases.PY_SKIP_NAMES


def test_python_phase_functions_are_callable():
    phase_funcs = [
        phases._phase_unused,
        phases._phase_structural,
        phases._phase_responsibility_cohesion,
        phases._phase_coupling,
        phases._phase_smells,
        phases._phase_mutable_state,
        phases._phase_layer_violation,
        phases._phase_dict_keys,
    ]
    for fn in phase_funcs:
        assert callable(fn)
    assert isinstance(Path("."), Path)
