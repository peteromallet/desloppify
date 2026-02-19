"""Focused tests for language contract validation rules."""

from __future__ import annotations

import pytest

from desloppify.languages.framework.base.types import DetectorPhase, LangConfig
from desloppify.languages.framework.contract_validation import validate_lang_contract


def _good_config(name: str = "dummy") -> LangConfig:
    return LangConfig(
        name=name,
        extensions=[".dm"],
        exclusions=[],
        default_src=".",
        build_dep_graph=lambda _p: {},
        entry_patterns=[],
        barrel_names=set(),
        phases=[DetectorPhase("phase", lambda _p, _l: ([], {}))],
        fixers={},
        detect_commands={"deps": lambda _a: None},
        extract_functions=lambda _p: [],
        file_finder=lambda _p: [],
        detect_markers=["dummy.toml"],
        zone_rules=[object()],
    )


def test_validate_lang_contract_accepts_valid_minimum():
    cfg = _good_config()
    result = validate_lang_contract("dummy", cfg)
    assert result is None
    assert cfg.name == "dummy"
    assert "deps" in cfg.detect_commands


def test_validate_lang_contract_rejects_non_snake_case_command_key():
    cfg = _good_config()
    cfg.detect_commands = {"single-use": lambda _a: None}

    with pytest.raises(ValueError, match="snake_case"):
        validate_lang_contract("dummy", cfg)


def test_validate_lang_contract_rejects_bad_runtime_option_specs_type():
    cfg = _good_config()
    cfg.runtime_option_specs = {"flag": object()}

    with pytest.raises(
        ValueError, match=r"runtime_option_specs\['flag'\] is not LangValueSpec"
    ):
        validate_lang_contract("dummy", cfg)
