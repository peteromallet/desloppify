from __future__ import annotations

import desloppify.languages.cxx as cxx_mod
import desloppify.languages.cxx.treesitter as cxx_treesitter
from desloppify.languages._framework.base.types import DetectorPhase
from desloppify.languages._framework.treesitter import C_SPEC, CPP_SPEC


def test_cxx_uses_full_plugin_config():
    cfg = cxx_mod.CxxConfig()
    assert cfg.name == "cxx"
    assert callable(cfg.build_dep_graph)
    assert callable(cfg.extract_functions)
    assert cfg.review_guidance


def test_cxx_keeps_cppcheck_phase():
    cfg = cxx_mod.CxxConfig()
    labels = {phase.label for phase in cfg.phases}
    assert "cppcheck" in labels


def test_cxx_includes_tree_sitter_phases(tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    sentinel = DetectorPhase("Tree-sitter sentinel", lambda *_args: ([], {}))

    def fake_phase(spec, *, spec_for_file=None):
        captured["spec_name"] = spec.grammar
        captured["spec_for_file"] = spec_for_file
        return sentinel

    monkeypatch.setattr(
        cxx_treesitter,
        "make_ast_smells_phase",
        fake_phase,
    )
    monkeypatch.setattr(
        "desloppify.languages._framework.treesitter.is_available", lambda: True
    )

    cfg = cxx_mod.CxxConfig()
    labels = {phase.label for phase in cfg.phases}

    assert captured["spec_name"] == "cpp"
    assert "Tree-sitter sentinel" in labels
    next(phase for phase in cfg.phases if phase.label == sentinel.label).run(
        tmp_path, cfg
    )
    select = captured["spec_for_file"]
    assert callable(select)
    assert select("native.c") is C_SPEC
    assert select("widget.cpp") is CPP_SPEC
    assert select("shared.h") is CPP_SPEC


def test_cxx_excludes_unused_imports_phase():
    cfg = cxx_mod.CxxConfig()
    labels = {phase.label for phase in cfg.phases}
    assert "Unused imports" not in labels


def test_cxx_keeps_non_ast_phases_without_optional_treesitter(monkeypatch):
    monkeypatch.setattr(
        "desloppify.languages._framework.treesitter.is_available", lambda: False
    )

    cfg = cxx_mod.CxxConfig()
    labels = {phase.label for phase in cfg.phases}

    assert "AST smells" not in labels
    assert "Responsibility cohesion" not in labels
    assert {
        "Structural analysis",
        "cppcheck",
        "Signature analysis",
        "Duplicates",
    } <= labels
