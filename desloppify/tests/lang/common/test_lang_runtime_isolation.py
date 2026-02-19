"""Tests for LangConfig/LangRun runtime isolation."""

from __future__ import annotations

from pathlib import Path

from desloppify.engine.planning.scan import PlanScanOptions, generate_findings
from desloppify.languages.framework.base.types import DetectorPhase
from desloppify.languages.framework.runtime import (
    LangRun,
    LangRunOverrides,
    make_lang_run,
)
from desloppify.languages.python import PythonConfig


def test_make_lang_run_instances_do_not_share_runtime_state() -> None:
    config = PythonConfig()

    run_a = make_lang_run(
        config,
        overrides=LangRunOverrides(
            runtime_settings={"alpha": 1},
            runtime_options={"beta": "x"},
        ),
    )
    run_b = make_lang_run(config)

    run_a.zone_map = {"a.py": "production"}
    run_a.dep_graph = {"a.py": {"imports": set(), "importers": set()}}
    run_a.complexity_map["a.py"] = 99
    run_a.review_cache["a.py"] = {"reviewed_at": "2026-01-01T00:00:00+00:00"}
    run_a.state.runtime_settings["alpha"] = 2
    run_a.state.runtime_options["beta"] = "y"

    assert run_b.zone_map is None
    assert run_b.dep_graph is None
    assert run_b.complexity_map == {}
    assert run_b.review_cache == {}
    assert run_b.runtime_setting("alpha", None) is None
    assert run_b.runtime_option("beta", None) is None

    assert run_a.complexity_map is not run_b.complexity_map
    assert run_a.review_cache is not run_b.review_cache
    assert run_a.state.runtime_settings is not run_b.state.runtime_settings
    assert run_a.state.runtime_options is not run_b.state.runtime_options


def test_generate_findings_keeps_runtime_fields_off_lang_config(tmp_path: Path) -> None:
    config = PythonConfig()
    source = tmp_path / "sample.py"
    source.write_text("def f():\n    return 1\n")

    def _runtime_mutation_phase(_path: Path, lang: LangRun):
        lang.zone_map = {str(source): "production"}
        lang.dep_graph = {str(source): {"imports": set(), "importers": set()}}
        lang.complexity_map[str(source)] = 1.0
        lang.review_cache[str(source)] = {"reviewed_at": "2026-01-01T00:00:00+00:00"}
        return [], {}

    config.phases = [DetectorPhase("RuntimeMutation", _runtime_mutation_phase)]
    config.file_finder = lambda _path: [str(source)]
    config.zone_rules = []

    findings, potentials = generate_findings(
        tmp_path,
        lang=config,
        options=PlanScanOptions(include_slow=False, profile="objective"),
    )

    assert findings == []
    assert potentials == {}

    for attr in (
        "zone_map",
        "dep_graph",
        "complexity_map",
        "review_cache",
        "review_max_age_days",
        "runtime_settings",
        "runtime_options",
    ):
        assert attr not in config.__dict__, (
            f"LangConfig unexpectedly mutated with {attr}"
        )
