"""Direct coverage tests for base.config.schema helpers."""

from __future__ import annotations

import desloppify.base.config.schema as config_schema


def test_default_config_returns_deep_copied_mutables() -> None:
    cfg_a = config_schema.default_config()
    cfg_b = config_schema.default_config()
    cfg_a["exclude"].append("tmp/")
    cfg_a["ignore_metadata"]["k"] = {"note": "n"}
    cfg_a["languages"]["python"] = {"enabled": True}
    assert cfg_b["exclude"] == []
    assert cfg_b["ignore_metadata"] == {}
    assert cfg_b["languages"] == {}


def test_coerce_target_score_clamps_and_uses_fallback() -> None:
    assert config_schema.coerce_target_score(-5) == 0.0
    assert config_schema.coerce_target_score(120) == 100.0
    assert config_schema.coerce_target_score("99.5") == 99.5
    assert config_schema.coerce_target_score("bad", fallback=97.0) == 97.0


def test_target_strict_score_from_config_handles_missing_values() -> None:
    assert config_schema.target_strict_score_from_config(None) == 85.0
    assert config_schema.target_strict_score_from_config({"target_strict_score": "96"}) == 96.0
    assert config_schema.target_strict_score_from_config({"target_strict_score": None}) == 85.0


def test_private_coerce_target_strict_score_reports_validity() -> None:
    assert config_schema._coerce_target_strict_score("42") == (42, True)
    assert config_schema._coerce_target_strict_score("bad") == (0, False)
    assert config_schema._coerce_target_strict_score(150) == (150, False)
