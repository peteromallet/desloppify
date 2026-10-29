"""Contracts for file-specific Tree-sitter specifications in shared phases."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from desloppify.languages._framework.treesitter import CPP_SPEC
from desloppify.languages._framework.treesitter.analysis import cohesion, smells
from desloppify.languages._framework.treesitter.phases import (
    make_ast_smells_phase,
    make_cohesion_phase,
)


@dataclass
class _Resolver:
    """A valid callable resolver need not be hashable."""

    def __call__(self, spec: str, source: str, root: str) -> str | None:
        return None


@pytest.mark.parametrize("factory", [make_ast_smells_phase, make_cohesion_phase])
@pytest.mark.parametrize("dispatch", [False, True])
def test_specs_do_not_require_hashable_resolvers(
    tmp_path, monkeypatch, factory, dispatch
):
    files = ["native.c", "widget.cpp", "shared.h"]
    spec = replace(CPP_SPEC, resolve_import=_Resolver())
    calls = []

    def detect(file_list, file_spec):
        calls.append((file_list, file_spec))
        return []

    def detect_cohesion(file_list, file_spec):
        return detect(file_list, file_spec), len(file_list)

    monkeypatch.setattr(smells, "detect_empty_catches", detect)
    monkeypatch.setattr(smells, "detect_unreachable_code", detect)
    monkeypatch.setattr(cohesion, "detect_responsibility_cohesion", detect_cohesion)
    phase = factory(spec, spec_for_file=(lambda _: spec) if dispatch else None)

    assert phase.run(tmp_path, SimpleNamespace(file_finder=lambda _: files)) == ([], {})
    assert calls == [(files, spec)] * (2 if factory is make_ast_smells_phase else 1)


@pytest.mark.parametrize("factory", [make_ast_smells_phase, make_cohesion_phase])
def test_empty_file_list_does_not_initialize_parsers(tmp_path, monkeypatch, factory):
    def unavailable(_grammar):
        raise AssertionError("Empty scans must not initialize a parser")

    for module in ("smells", "cohesion"):
        monkeypatch.setattr(
            f"desloppify.languages._framework.treesitter.analysis.{module}._get_parser",
            unavailable,
        )

    assert factory(CPP_SPEC).run(
        tmp_path, SimpleNamespace(file_finder=lambda _: [])
    ) == ([], {})
