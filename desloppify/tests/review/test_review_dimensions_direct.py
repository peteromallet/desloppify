"""Direct tests for review dimension guidance helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import desloppify.intelligence.review.dimensions.data as dimensions_data_mod
import desloppify.intelligence.review.dimensions.lang as dimensions_mod
import desloppify.intelligence.review.dimensions.metadata as dimensions_metadata_mod
import desloppify.intelligence.review.dimensions.selection as dimensions_selection_mod
import desloppify.intelligence.review.dimensions.validation as dimensions_validation_mod
import desloppify.languages as lang_mod
from desloppify.intelligence.review.dimensions.file import DEFAULT_DIMENSIONS


def test_collect_holistic_dims_by_lang_filters_empty_entries(monkeypatch):
    monkeypatch.setattr(dimensions_mod, "available_langs", lambda: ["python", "typescript"])
    monkeypatch.setattr(
        dimensions_mod,
        "get_lang",
        lambda name: SimpleNamespace(
            holistic_review_dimensions=(
                ["logic_clarity", "contracts"] if name == "python" else []
            )
        ),
    )

    collected = dimensions_mod._collect_holistic_dims_by_lang()
    assert collected == {"python": ["logic_clarity", "contracts"]}


def test_collect_lang_guidance_and_get_lang_guidance_cache(monkeypatch):
    monkeypatch.setattr(dimensions_mod, "available_langs", lambda: ["python"])
    monkeypatch.setattr(
        dimensions_mod,
        "get_lang",
        lambda _name: SimpleNamespace(review_guidance={"patterns": ["check x"]}),
    )

    collected = dimensions_mod._collect_lang_guidance()
    assert collected == {"python": {"patterns": ["check x"]}}

    original = dict(dimensions_mod.LANG_GUIDANCE)
    dimensions_mod.LANG_GUIDANCE.clear()
    try:
        first = dimensions_mod.get_lang_guidance("python")
        second = dimensions_mod.get_lang_guidance("python")
        assert first == {"patterns": ["check x"]}
        assert second == first
        assert dimensions_mod.LANG_GUIDANCE["python"] == first
    finally:
        dimensions_mod.LANG_GUIDANCE.clear()
        dimensions_mod.LANG_GUIDANCE.update(original)


def test_dimensions_schema_validation_rejects_bad_prompt_shape(monkeypatch):
    def _bad_payload(_filename: str) -> dict:
        return {
            "default_dimensions": ["naming_quality"],
            "dimension_prompts": {
                "naming_quality": {
                    "description": "names",
                    "look_for": "not-a-list",
                    "skip": ["ok"],
                },
            },
            "system_prompt": "x" * 120,
        }

    monkeypatch.setattr(dimensions_data_mod, "_load_json_payload", _bad_payload)
    dimensions_data_mod.load_dimensions.cache_clear()
    try:
        with pytest.raises(ValueError, match="look_for"):
            dimensions_data_mod.load_dimensions()
    finally:
        dimensions_data_mod.load_dimensions.cache_clear()


def test_dimensions_validation_requires_prompt_for_each_default_dimension(monkeypatch):
    def _bad_payload(_filename: str) -> dict:
        return {
            "default_dimensions": ["cross_module_architecture", "error_consistency"],
            "dimension_prompts": {
                "cross_module_architecture": {
                    "description": "arch",
                    "look_for": ["a"],
                    "skip": ["b"],
                },
            },
            "system_prompt": "x" * 120,
        }

    monkeypatch.setattr(dimensions_data_mod, "_load_json_payload", _bad_payload)
    dimensions_data_mod.load_dimensions.cache_clear()
    try:
        with pytest.raises(ValueError, match="missing prompts"):
            dimensions_data_mod.load_dimensions()
    finally:
        dimensions_data_mod.load_dimensions.cache_clear()


def test_resolve_per_file_dimensions_precedence():
    resolved = dimensions_selection_mod.resolve_per_file_dimensions(
        cli_dimensions=["logic_clarity"],
        config_dimensions=["naming_quality"],
    )
    assert resolved == ["logic_clarity"]

    resolved = dimensions_selection_mod.resolve_per_file_dimensions(
        cli_dimensions=None,
        config_dimensions=["naming_quality"],
    )
    assert resolved == ["naming_quality"]

    resolved = dimensions_selection_mod.resolve_per_file_dimensions(
        cli_dimensions=None,
        config_dimensions=None,
    )
    assert resolved == DEFAULT_DIMENSIONS


def test_resolve_holistic_dimensions_precedence(monkeypatch):
    monkeypatch.setattr(
        dimensions_selection_mod,
        "HOLISTIC_DIMENSIONS_BY_LANG",
        {"python": ["dependency_health"]},
    )
    monkeypatch.setattr(
        dimensions_selection_mod,
        "DIMENSIONS",
        ["cross_module_architecture"],
    )

    resolved = dimensions_selection_mod.resolve_holistic_dimensions(
        lang_name="python",
        cli_dimensions=["test_strategy"],
    )
    assert resolved == ["test_strategy"]

    resolved = dimensions_selection_mod.resolve_holistic_dimensions(
        lang_name="python",
        cli_dimensions=None,
    )
    assert resolved == ["dependency_health"]

    resolved = dimensions_selection_mod.resolve_holistic_dimensions(
        lang_name="go",
        cli_dimensions=None,
    )
    assert resolved == ["cross_module_architecture"]


def test_load_dimensions_for_lang_override_replaces_dimension_list(
    tmp_path, monkeypatch
):
    shared_dir = tmp_path / "review_data"
    lang_dir = tmp_path / "lang_data"
    shared_dir.mkdir(parents=True)
    (lang_dir / "python" / "review_data").mkdir(parents=True)

    shared_payload = {
        "default_dimensions": ["shared_dim"],
        "dimension_prompts": {
            "shared_dim": {
                "description": "shared desc",
                "look_for": ["x"],
                "skip": ["y"],
            }
        },
        "system_prompt": "s" * 120,
    }
    # Override fully replaces the dimension list and removes the shared prompt entry.
    override_payload = {
        "default_dimensions": ["lang_dim"],
        "dimension_prompts": {
            "lang_dim": {
                "description": "lang desc",
                "look_for": ["a"],
                "skip": ["b"],
            }
        },
        "dimension_prompts_remove": ["shared_dim"],
    }
    (shared_dir / "dimensions.json").write_text(json.dumps(shared_payload))
    (lang_dir / "python" / "review_data" / "dimensions.override.json").write_text(
        json.dumps(override_payload)
    )

    monkeypatch.setattr(dimensions_data_mod, "_DATA_DIR", shared_dir)
    monkeypatch.setattr(dimensions_data_mod, "_LANG_DIR", lang_dir)
    dimensions_data_mod.load_dimensions_for_lang.cache_clear()
    try:
        dims, prompts, _ = dimensions_data_mod.load_dimensions_for_lang("python")
    finally:
        dimensions_data_mod.load_dimensions_for_lang.cache_clear()

    assert dims == ["lang_dim"]
    assert "lang_dim" in prompts
    assert "shared_dim" not in prompts


def test_load_dimensions_for_lang_falls_back_to_shared(tmp_path, monkeypatch):
    shared_dir = tmp_path / "review_data"
    lang_dir = tmp_path / "lang_data"
    shared_dir.mkdir(parents=True)
    (lang_dir / "python").mkdir(parents=True)

    shared_payload = {
        "default_dimensions": ["shared_dim"],
        "dimension_prompts": {
            "shared_dim": {
                "description": "shared desc",
                "look_for": ["x"],
                "skip": ["y"],
            }
        },
        "system_prompt": "s" * 120,
    }
    (shared_dir / "dimensions.json").write_text(json.dumps(shared_payload))

    monkeypatch.setattr(dimensions_data_mod, "_DATA_DIR", shared_dir)
    monkeypatch.setattr(dimensions_data_mod, "_LANG_DIR", lang_dir)
    dimensions_data_mod.load_dimensions_for_lang.cache_clear()
    try:
        dims, prompts, _ = dimensions_data_mod.load_dimensions_for_lang("python")
    finally:
        dimensions_data_mod.load_dimensions_for_lang.cache_clear()

    assert dims == ["shared_dim"]
    assert "shared_dim" in prompts


def test_load_dimensions_for_lang_applies_override_patch(
    tmp_path, monkeypatch
):
    shared_dir = tmp_path / "review_data"
    lang_dir = tmp_path / "lang_data"
    shared_dir.mkdir(parents=True)
    (lang_dir / "python" / "review_data").mkdir(parents=True)

    shared_payload = {
        "default_dimensions": ["shared_dim"],
        "dimension_prompts": {
            "shared_dim": {
                "description": "shared desc",
                "look_for": ["x"],
                "skip": ["y"],
            }
        },
        "system_prompt": "s" * 120,
    }
    override_payload = {
        "default_dimensions_append": ["lang_dim"],
        "dimension_prompts": {
            "lang_dim": {
                "description": "lang desc",
                "look_for": ["a"],
                "skip": ["b"],
            }
        },
        "system_prompt_append": "lang-tail",
    }
    (shared_dir / "dimensions.json").write_text(json.dumps(shared_payload))
    (
        lang_dir / "python" / "review_data" / "dimensions.override.json"
    ).write_text(json.dumps(override_payload))

    monkeypatch.setattr(dimensions_data_mod, "_DATA_DIR", shared_dir)
    monkeypatch.setattr(dimensions_data_mod, "_LANG_DIR", lang_dir)
    dimensions_data_mod.load_dimensions_for_lang.cache_clear()
    try:
        dims, prompts, system_prompt = (
            dimensions_data_mod.load_dimensions_for_lang("python")
        )
    finally:
        dimensions_data_mod.load_dimensions_for_lang.cache_clear()

    assert dims == ["shared_dim", "lang_dim"]
    assert "shared_dim" in prompts
    assert "lang_dim" in prompts
    assert system_prompt.endswith("lang-tail")


def test_load_dimensions_for_lang_override_remove_and_append(
    tmp_path, monkeypatch
):
    shared_dir = tmp_path / "review_data"
    lang_dir = tmp_path / "lang_data"
    shared_dir.mkdir(parents=True)
    (lang_dir / "python" / "review_data").mkdir(parents=True)

    shared_payload = {
        "default_dimensions": ["a", "b"],
        "dimension_prompts": {
            "a": {"description": "A", "look_for": ["x"], "skip": ["y"]},
            "b": {"description": "B", "look_for": ["x"], "skip": ["y"]},
        },
        "system_prompt": "h" * 120,
    }
    override_payload = {
        "default_dimensions_remove": ["b"],
        "default_dimensions_append": ["c"],
        "dimension_prompts": {
            "c": {"description": "C", "look_for": ["x"], "skip": ["y"]},
        },
    }
    (shared_dir / "dimensions.json").write_text(json.dumps(shared_payload))
    (
        lang_dir / "python" / "review_data" / "dimensions.override.json"
    ).write_text(json.dumps(override_payload))

    monkeypatch.setattr(dimensions_data_mod, "_DATA_DIR", shared_dir)
    monkeypatch.setattr(dimensions_data_mod, "_LANG_DIR", lang_dir)
    dimensions_data_mod.load_dimensions_for_lang.cache_clear()
    try:
        dims, prompts, _ = dimensions_data_mod.load_dimensions_for_lang("python")
    finally:
        dimensions_data_mod.load_dimensions_for_lang.cache_clear()

    assert dims == ["a", "c"]
    assert "a" in prompts
    assert "c" in prompts


def test_parse_dimensions_payload_supports_meta_enabled_defaults():
    payload = {
        "dimension_prompts": {
            "structure_signal": {
                "description": "Structure signal quality",
                "look_for": ["flat root"],
                "skip": ["tiny repos"],
                "meta": {
                    "enabled_by_default": True,
                    "display_name": "Structure Signal",
                    "weight": 4.5,
                    "reset_on_scan": True,
                },
            }
        },
        "system_prompt": "x" * 120,
    }

    dims, prompts, _ = dimensions_validation_mod.parse_dimensions_payload(
        payload, context_prefix="test_payload"
    )

    assert dims == ["structure_signal"]
    assert prompts["structure_signal"]["meta"]["enabled_by_default"] is True
    assert prompts["structure_signal"]["meta"]["display_name"] == "Structure Signal"
    assert prompts["structure_signal"]["meta"]["weight"] == 4.5


def test_load_dimensions_for_lang_meta_enabled_dimension_requires_no_append(
    tmp_path, monkeypatch
):
    shared_dir = tmp_path / "review_data"
    lang_dir = tmp_path / "lang_data"
    shared_dir.mkdir(parents=True)
    (lang_dir / "python" / "review_data").mkdir(parents=True)

    shared_payload = {
        "default_dimensions": ["shared_dim"],
        "dimension_prompts": {
            "shared_dim": {
                "description": "shared desc",
                "look_for": ["x"],
                "skip": ["y"],
            }
        },
        "system_prompt": "s" * 120,
    }
    override_payload = {
        "dimension_prompts": {
            "lang_structure_nav": {
                "description": "lang nav",
                "look_for": ["z"],
                "skip": ["w"],
                "meta": {
                    "enabled_by_default": True,
                    "display_name": "Lang Structure Nav",
                    "weight": 3.2,
                },
            }
        }
    }
    (shared_dir / "dimensions.json").write_text(json.dumps(shared_payload))
    (
        lang_dir / "python" / "review_data" / "dimensions.override.json"
    ).write_text(json.dumps(override_payload))

    monkeypatch.setattr(dimensions_data_mod, "_DATA_DIR", shared_dir)
    monkeypatch.setattr(dimensions_data_mod, "_LANG_DIR", lang_dir)
    dimensions_data_mod.load_dimensions_for_lang.cache_clear()
    try:
        dims, prompts, _ = dimensions_data_mod.load_dimensions_for_lang("python")
    finally:
        dimensions_data_mod.load_dimensions_for_lang.cache_clear()

    assert dims == ["shared_dim", "lang_structure_nav"]
    assert prompts["lang_structure_nav"]["meta"]["weight"] == 3.2


def test_dimension_metadata_uses_prompt_meta_overrides(monkeypatch):
    payload = (
        ["custom_dimension"],
        {
            "custom_dimension": {
                "description": "custom",
                "look_for": ["x"],
                "skip": ["y"],
                "meta": {
                    "enabled_by_default": True,
                    "display_name": "Custom Dimension",
                    "weight": 7.5,
                    "reset_on_scan": False,
                },
            }
        },
        "p" * 120,
    )

    monkeypatch.setattr(
        dimensions_metadata_mod,
        "load_dimensions",
        lambda: payload,
    )
    monkeypatch.setattr(dimensions_metadata_mod, "_available_languages", lambda: [])
    dimensions_metadata_mod.load_subjective_dimension_metadata.cache_clear()
    try:
        assert (
            dimensions_metadata_mod.dimension_display_name("custom_dimension")
            == "Custom Dimension"
        )
        assert dimensions_metadata_mod.dimension_weight("custom_dimension") == 7.5
        assert (
            "custom_dimension"
            not in dimensions_metadata_mod.resettable_default_dimensions()
        )
    finally:
        dimensions_metadata_mod.load_subjective_dimension_metadata.cache_clear()


def test_dimension_metadata_can_override_weight_per_language(monkeypatch):
    shared_payload = (
        ["shared_dimension"],
        {
            "shared_dimension": {
                "description": "shared",
                "look_for": ["x"],
                "skip": ["y"],
                "meta": {
                    "enabled_by_default": True,
                    "display_name": "Shared Dimension",
                    "weight": 2.0,
                },
            }
        },
        "p" * 120,
    )
    lang_payload = (
        ["shared_dimension"],
        {
            "shared_dimension": {
                "description": "shared",
                "look_for": ["x"],
                "skip": ["y"],
                "meta": {
                    "enabled_by_default": True,
                    "display_name": "Shared Dimension (Py)",
                    "weight": 6.0,
                },
            }
        },
        "p" * 120,
    )

    monkeypatch.setattr(
        dimensions_metadata_mod, "load_dimensions", lambda: shared_payload
    )
    monkeypatch.setattr(
        dimensions_metadata_mod,
        "load_dimensions_for_lang",
        lambda _lang: lang_payload,
    )
    monkeypatch.setattr(dimensions_metadata_mod, "_available_languages", lambda: [])
    dimensions_metadata_mod.load_subjective_dimension_metadata.cache_clear()
    dimensions_metadata_mod.load_subjective_dimension_metadata_for_lang.cache_clear()
    try:
        assert dimensions_metadata_mod.dimension_weight("shared_dimension") == 2.0
        assert (
            dimensions_metadata_mod.dimension_weight(
                "shared_dimension", lang_name="python"
            )
            == 6.0
        )
        assert (
            dimensions_metadata_mod.dimension_display_name(
                "shared_dimension", lang_name="python"
            )
            == "Shared Dimension (Py)"
        )
    finally:
        dimensions_metadata_mod.load_subjective_dimension_metadata.cache_clear()
        dimensions_metadata_mod.load_subjective_dimension_metadata_for_lang.cache_clear()
