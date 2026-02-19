"""Direct tests for dev scaffold template builders."""

from __future__ import annotations

import desloppify.app.commands.dev_scaffold_templates as templates_mod


def test_build_scaffold_files_contains_expected_paths():
    files = templates_mod.build_scaffold_files(
        lang_name="ruby",
        class_name="RubyConfig",
        extensions=[".rb"],
        markers=["Gemfile"],
        default_src="lib",
    )

    assert files["detectors/__init__.py"] == ""
    assert files["fixers/__init__.py"] == ""
    assert files["review_data/per_file_dimensions.override.json"] == "{}\n"
    assert files["review_data/holistic_dimensions.override.json"] == "{}\n"
    assert "build_dep_graph" in files["detectors/deps.py"]


def test_init_template_registers_language_and_defaults():
    files = templates_mod.build_scaffold_files(
        lang_name="swift",
        class_name="SwiftConfig",
        extensions=[".swift"],
        markers=["Package.swift"],
        default_src="Sources",
    )

    init_py = files["__init__.py"]
    assert '@register_lang("swift")' in init_py
    assert "class SwiftConfig(LangConfig):" in init_py
    assert "default_src='Sources'" in init_py
    assert "detect_markers=['Package.swift']" in init_py
    assert "from ..base.types import DetectorPhase, LangConfig" in init_py
    assert "from ..base.phase_builders import (" in init_py

    phases_py = files["phases.py"]
    assert "from ..base.types import LangConfig" in phases_py
