"""Tests for the generic language plugin system."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from desloppify.languages._framework.generic import (
    _make_generic_fixer,
    capability_report,
    generic_lang,
    make_file_finder,
    make_tool_phase,
    parse_cargo,
    parse_gnu,
    parse_golangci,
    parse_json,
    parse_rubocop,
)


@pytest.fixture
def _cleanup_registry():
    """Auto-cleanup generic plugins registered during a test."""
    from desloppify.languages._framework import registry_state

    before = set(registry_state.all_keys())
    yield
    for name in set(registry_state.all_keys()) - before:
        registry_state.remove(name)


# ── Output parser tests ──────────────────────────────────


class TestParseGnu:
    def test_extracts_file_line_message(self):
        output = "src/main.go:42: undefined: foo\nsrc/util.go:10: unused variable\n"
        entries = parse_gnu(output, Path("."))
        assert len(entries) == 2
        assert entries[0] == {"file": "src/main.go", "line": 42, "message": "undefined: foo"}
        assert entries[1] == {"file": "src/util.go", "line": 10, "message": "unused variable"}

    def test_handles_col_number(self):
        output = "src/main.go:42:5: error: something wrong\n"
        entries = parse_gnu(output, Path("."))
        assert len(entries) == 1
        assert entries[0]["file"] == "src/main.go"
        assert entries[0]["line"] == 42
        assert entries[0]["message"] == "error: something wrong"

    def test_skips_non_matching_lines(self):
        output = "Running checks...\nsrc/main.go:42: error\nDone.\n"
        entries = parse_gnu(output, Path("."))
        assert len(entries) == 1

    def test_empty_output(self):
        assert parse_gnu("", Path(".")) == []


class TestParseGolangci:
    def test_extracts_issues(self):
        data = {
            "Issues": [
                {
                    "Pos": {"Filename": "main.go", "Line": 10, "Column": 5},
                    "Text": "unused variable",
                }
            ]
        }
        entries = parse_golangci(json.dumps(data), Path("."))
        assert len(entries) == 1
        assert entries[0] == {"file": "main.go", "line": 10, "message": "unused variable"}

    def test_handles_empty_issues(self):
        entries = parse_golangci(json.dumps({"Issues": []}), Path("."))
        assert entries == []

    def test_handles_null_issues(self):
        entries = parse_golangci(json.dumps({"Issues": None}), Path("."))
        assert entries == []

    def test_invalid_json(self):
        assert parse_golangci("not json", Path(".")) == []


class TestParseJson:
    def test_extracts_with_field_aliases(self):
        data = [
            {"file": "a.swift", "line": 1, "message": "warning"},
            {"filename": "b.swift", "line_no": 2, "text": "error"},
            {"path": "c.swift", "row": 3, "reason": "hint"},
        ]
        entries = parse_json(json.dumps(data), Path("."))
        assert len(entries) == 3
        assert entries[0] == {"file": "a.swift", "line": 1, "message": "warning"}
        assert entries[1] == {"file": "b.swift", "line": 2, "message": "error"}
        assert entries[2] == {"file": "c.swift", "line": 3, "message": "hint"}

    def test_skips_items_without_file(self):
        data = [{"line": 1, "message": "no file"}]
        entries = parse_json(json.dumps(data), Path("."))
        assert entries == []

    def test_invalid_json(self):
        assert parse_json("not json", Path(".")) == []

    def test_non_array(self):
        assert parse_json(json.dumps({"key": "value"}), Path(".")) == []


class TestParseRubocop:
    def test_flattens_offenses(self):
        data = {
            "files": [
                {
                    "path": "app/models/user.rb",
                    "offenses": [
                        {
                            "location": {"line": 5, "column": 1},
                            "message": "Line too long",
                        },
                        {
                            "location": {"line": 10},
                            "message": "Missing frozen string",
                        },
                    ],
                },
                {
                    "path": "app/models/post.rb",
                    "offenses": [
                        {
                            "location": {"line": 1},
                            "message": "Use def with parentheses",
                        }
                    ],
                },
            ]
        }
        entries = parse_rubocop(json.dumps(data), Path("."))
        assert len(entries) == 3
        assert entries[0] == {"file": "app/models/user.rb", "line": 5, "message": "Line too long"}
        assert entries[2] == {
            "file": "app/models/post.rb",
            "line": 1,
            "message": "Use def with parentheses",
        }

    def test_empty_files(self):
        assert parse_rubocop(json.dumps({"files": []}), Path(".")) == []

    def test_invalid_json(self):
        assert parse_rubocop("not json", Path(".")) == []


class TestParseCargo:
    def test_extracts_compiler_messages(self):
        lines = [
            json.dumps(
                {
                    "reason": "compiler-message",
                    "message": {
                        "spans": [{"file_name": "src/main.rs", "line_start": 42}],
                        "rendered": "warning: unused variable\n  --> src/main.rs:42:5\n",
                    },
                }
            ),
            json.dumps({"reason": "build-script-executed"}),
        ]
        entries = parse_cargo("\n".join(lines), Path("."))
        assert len(entries) == 1
        assert entries[0]["file"] == "src/main.rs"
        assert entries[0]["line"] == 42
        assert "unused variable" in entries[0]["message"]

    def test_skips_non_compiler_messages(self):
        line = json.dumps({"reason": "build-finished", "success": True})
        assert parse_cargo(line, Path(".")) == []

    def test_empty_output(self):
        assert parse_cargo("", Path(".")) == []


# ── make_tool_phase tests ─────────────────────────────────


class TestMakeToolPhase:
    def test_missing_tool_returns_no_findings(self):
        phase = make_tool_phase("test", "nonexistent_tool_xyz_123", "gnu", "test_id", 2)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            findings, signals = phase.run(Path("."), None)
        assert findings == []
        assert signals == {}

    def test_timeout_returns_no_findings(self):
        phase = make_tool_phase("test", "sleep 999", "gnu", "test_id", 2)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
            findings, signals = phase.run(Path("."), None)
        assert findings == []
        assert signals == {}

    def test_gnu_output_produces_findings(self):
        phase = make_tool_phase("test", "fake", "gnu", "test_lint", 2)
        mock_result = subprocess.CompletedProcess(
            args="fake",
            returncode=1,
            stdout="src/foo.go:10: something wrong\nsrc/bar.go:20: another issue\n",
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result):
            findings, signals = phase.run(Path("."), None)
        assert len(findings) == 2
        assert signals == {"test_lint": 2}
        assert findings[0]["detector"] == "test_lint"
        assert findings[0]["summary"] == "something wrong"

    def test_empty_output_returns_empty(self):
        phase = make_tool_phase("test", "fake", "gnu", "test_id", 2)
        mock_result = subprocess.CompletedProcess(
            args="fake", returncode=0, stdout="", stderr=""
        )
        with patch("subprocess.run", return_value=mock_result):
            findings, signals = phase.run(Path("."), None)
        assert findings == []
        assert signals == {}


# ── generic_lang registration tests ──────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestGenericLang:
    def test_registers_and_resolves(self):
        from desloppify.languages._framework import registry_state
        from desloppify.languages._framework.base.types import LangConfig

        cfg = generic_lang(
            name="test_generic_lang_1",
            extensions=[".test1"],
            tools=[
                {"label": "test tool", "cmd": "echo ok", "fmt": "gnu", "id": "test_tool", "tier": 2}
            ],
        )
        assert isinstance(cfg, LangConfig)
        assert registry_state.is_registered("test_generic_lang_1")
        assert registry_state.get("test_generic_lang_1") is cfg

    def test_get_lang_returns_instance(self):
        from desloppify.languages._framework.base.types import LangConfig
        from desloppify.languages._framework.resolution import get_lang

        cfg = generic_lang(
            name="test_generic_lang_2",
            extensions=[".test2"],
            tools=[
                {"label": "test tool", "cmd": "echo ok", "fmt": "gnu", "id": "test_tool_2", "tier": 2}
            ],
        )
        resolved = get_lang("test_generic_lang_2")
        assert resolved is cfg
        assert isinstance(resolved, LangConfig)

    def test_integration_depth_set(self):
        cfg = generic_lang(
            name="test_generic_lang_3",
            extensions=[".test3"],
            tools=[
                {"label": "t", "cmd": "echo", "fmt": "gnu", "id": "t_id", "tier": 2}
            ],
            depth="minimal",
        )
        assert cfg.integration_depth == "minimal"


# ── Stub tests ────────────────────────────────────────────


class TestStubs:
    def test_make_file_finder_returns_callable(self):
        finder = make_file_finder([".go"])
        assert callable(finder)

    def test_file_finder_finds_files(self, tmp_path):
        (tmp_path / "main.go").write_text("package main")
        (tmp_path / "test.py").write_text("pass")
        finder = make_file_finder([".go"])
        result = finder(tmp_path)
        assert isinstance(result, list)


# ── Langs command tests ───────────────────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestLangsCommand:
    def test_all_builtin_langs_discoverable(self):
        """All 5 full plugins and generic plugins should be available."""
        from desloppify.languages import available_langs

        names = available_langs()
        for full_lang in ["python", "typescript", "csharp", "dart", "gdscript"]:
            assert full_lang in names, f"{full_lang} not found in {names}"
        for generic_lang_name in ["go", "rust", "ruby"]:
            assert generic_lang_name in names, f"{generic_lang_name} not found in {names}"
        assert len(names) > 10, f"Expected >10 languages, got {len(names)}: {names}"

    def test_langs_hides_shared_phases_from_tool_list(self):
        from desloppify.app.commands.langs import _get_tool_labels

        cfg = generic_lang(
            name="test_langs_hide_1",
            extensions=[".x"],
            tools=[{"label": "xlint", "cmd": "echo", "fmt": "gnu", "id": "xlint_id", "tier": 2}],
        )
        labels = _get_tool_labels(cfg)
        assert "xlint" in labels
        assert "Security" not in labels
        assert "Subjective review" not in labels
        assert "Boilerplate duplication" not in labels
        assert "Duplicates" not in labels

    def test_langs_shows_auto_fix_suffix(self):
        from desloppify.app.commands.langs import _get_tool_labels

        cfg = generic_lang(
            name="test_langs_fix_1",
            extensions=[".x"],
            tools=[{
                "label": "xlint", "cmd": "echo", "fmt": "gnu",
                "id": "xlint_fix_id", "tier": 2, "fix_cmd": "xlint --fix",
            }],
        )
        labels = _get_tool_labels(cfg)
        assert "(auto-fix)" in labels

    def test_langs_no_auto_fix_suffix_without_fixers(self):
        from desloppify.app.commands.langs import _get_tool_labels

        cfg = generic_lang(
            name="test_langs_nofix_1",
            extensions=[".x"],
            tools=[{"label": "xlint", "cmd": "echo", "fmt": "gnu", "id": "xlint_nofix_id", "tier": 2}],
        )
        labels = _get_tool_labels(cfg)
        assert "(auto-fix)" not in labels


# ── Dynamic registration tests ──────────────────────────


class TestDynamicRegistration:
    def test_register_detector_adds_to_detectors_dict(self):
        from desloppify.core.registry import DETECTORS, DetectorMeta, register_detector

        name = "_test_reg_det_1"
        register_detector(DetectorMeta(
            name=name, display="test", dimension="Code quality",
            action_type="manual_fix", guidance="test guidance",
        ))
        assert name in DETECTORS
        assert DETECTORS[name].display == "test"
        del DETECTORS[name]

    def test_register_detector_appends_to_display_order(self):
        from desloppify.core.registry import (
            DETECTORS,
            DetectorMeta,
            _DISPLAY_ORDER,
            register_detector,
        )

        name = "_test_reg_det_2"
        register_detector(DetectorMeta(
            name=name, display="test", dimension="Code quality",
            action_type="manual_fix", guidance="test",
        ))
        assert name in _DISPLAY_ORDER
        del DETECTORS[name]
        _DISPLAY_ORDER.remove(name)

    def test_register_scoring_policy_rebuilds_dimensions(self):
        from desloppify.engine._scoring.policy.core import (
            DETECTOR_SCORING_POLICIES,
            DIMENSIONS,
            DetectorScoringPolicy,
            FILE_BASED_DETECTORS,
            register_scoring_policy,
        )

        name = "_test_reg_pol_1"
        register_scoring_policy(DetectorScoringPolicy(
            detector=name, dimension="Code quality", tier=3, file_based=True,
        ))
        assert name in FILE_BASED_DETECTORS
        cq = next(d for d in DIMENSIONS if d.name == "Code quality")
        assert name in cq.detectors
        del DETECTOR_SCORING_POLICIES[name]

    def test_register_detector_auto_refreshes_narrative(self):
        """register_detector should auto-refresh DETECTOR_TOOLS via callback."""
        from desloppify.core.registry import DETECTORS, DetectorMeta, register_detector
        from desloppify.intelligence.narrative._constants import DETECTOR_TOOLS

        name = "_test_auto_refresh_1"
        register_detector(DetectorMeta(
            name=name, display="test", dimension="Code quality",
            action_type="manual_fix", guidance="auto refresh test",
        ))
        # Should be in DETECTOR_TOOLS without any manual refresh call
        assert name in DETECTOR_TOOLS
        assert DETECTOR_TOOLS[name]["guidance"] == "auto refresh test"
        del DETECTORS[name]


# ── Scoring integration tests ────────────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestScoringIntegration:
    def test_generic_findings_contribute_to_code_quality_dimension(self):
        from desloppify.engine._scoring.policy.core import DIMENSIONS

        generic_lang(
            name="test_scoring_1",
            extensions=[".x"],
            tools=[{"label": "t", "cmd": "echo", "fmt": "gnu", "id": "test_score_det_1", "tier": 2}],
        )
        cq = next(d for d in DIMENSIONS if d.name == "Code quality")
        assert "test_score_det_1" in cq.detectors

    def test_generic_findings_score_with_correct_tier(self):
        from desloppify.engine._scoring.policy.core import DETECTOR_SCORING_POLICIES

        generic_lang(
            name="test_scoring_2",
            extensions=[".x"],
            tools=[{"label": "t", "cmd": "echo", "fmt": "gnu", "id": "test_score_det_2", "tier": 3}],
        )
        policy = DETECTOR_SCORING_POLICIES["test_score_det_2"]
        assert policy.tier == 3
        assert policy.file_based is True


# ── Narrative integration tests ──────────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestNarrativeIntegration:
    def test_generic_detector_appears_in_detector_tools(self):
        from desloppify.intelligence.narrative._constants import DETECTOR_TOOLS

        generic_lang(
            name="test_narrative_1",
            extensions=[".x"],
            tools=[{"label": "narr tool", "cmd": "echo", "fmt": "gnu", "id": "test_narr_det_1", "tier": 2}],
        )
        assert "test_narr_det_1" in DETECTOR_TOOLS
        assert DETECTOR_TOOLS["test_narr_det_1"]["action_type"] == "manual_fix"

    def test_generic_detector_with_fixer_has_auto_fix_action(self):
        from desloppify.intelligence.narrative._constants import DETECTOR_TOOLS

        generic_lang(
            name="test_narrative_2",
            extensions=[".x"],
            tools=[{
                "label": "narr tool", "cmd": "echo", "fmt": "gnu",
                "id": "test_narr_det_2", "tier": 2, "fix_cmd": "echo --fix",
            }],
        )
        assert DETECTOR_TOOLS["test_narr_det_2"]["action_type"] == "auto_fix"
        assert "test-narr-det-2" in DETECTOR_TOOLS["test_narr_det_2"]["fixers"]


# ── Shared phases tests ──────────────────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestSharedPhases:
    def test_generic_plugin_has_security_phase(self):
        cfg = generic_lang(
            name="test_phases_1",
            extensions=[".x"],
            tools=[{"label": "t", "cmd": "echo", "fmt": "gnu", "id": "test_ph_1", "tier": 2}],
        )
        assert "Security" in [p.label for p in cfg.phases]

    def test_generic_plugin_has_subjective_review_phase(self):
        cfg = generic_lang(
            name="test_phases_2",
            extensions=[".x"],
            tools=[{"label": "t", "cmd": "echo", "fmt": "gnu", "id": "test_ph_2", "tier": 2}],
        )
        assert "Subjective review" in [p.label for p in cfg.phases]

    def test_generic_plugin_has_boilerplate_duplication_phase(self):
        cfg = generic_lang(
            name="test_phases_3",
            extensions=[".x"],
            tools=[{"label": "t", "cmd": "echo", "fmt": "gnu", "id": "test_ph_3", "tier": 2}],
        )
        assert "Boilerplate duplication" in [p.label for p in cfg.phases]

    def test_generic_plugin_has_duplicates_phase(self):
        cfg = generic_lang(
            name="test_phases_4",
            extensions=[".x"],
            tools=[{"label": "t", "cmd": "echo", "fmt": "gnu", "id": "test_ph_4", "tier": 2}],
        )
        assert "Duplicates" in [p.label for p in cfg.phases]

    def test_generic_plugin_phase_order_tool_before_shared(self):
        cfg = generic_lang(
            name="test_phases_5",
            extensions=[".x"],
            tools=[{"label": "mytool", "cmd": "echo", "fmt": "gnu", "id": "test_ph_5", "tier": 2}],
        )
        labels = [p.label for p in cfg.phases]
        assert labels.index("mytool") < labels.index("Security")


# ── Fixer tests ──────────────────────────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestFixers:
    def test_fix_cmd_creates_fixer_config(self):
        from desloppify.languages._framework.base.types import FixerConfig

        cfg = generic_lang(
            name="test_fixer_1",
            extensions=[".x"],
            tools=[{
                "label": "fixlint", "cmd": "echo", "fmt": "gnu",
                "id": "test_fixer_det_1", "tier": 2, "fix_cmd": "fixlint --fix",
            }],
        )
        assert "test-fixer-det-1" in cfg.fixers
        fixer = cfg.fixers["test-fixer-det-1"]
        assert isinstance(fixer, FixerConfig)
        assert fixer.detector == "test_fixer_det_1"
        assert fixer.label == "Fix fixlint issues"

    def test_tool_without_fix_cmd_has_no_fixer(self):
        cfg = generic_lang(
            name="test_fixer_2",
            extensions=[".x"],
            tools=[{"label": "nofixlint", "cmd": "echo", "fmt": "gnu", "id": "test_fixer_det_2", "tier": 2}],
        )
        assert cfg.fixers == {}

    def test_fixer_name_uses_dash_convention(self):
        cfg = generic_lang(
            name="test_fixer_3",
            extensions=[".x"],
            tools=[{
                "label": "t", "cmd": "echo", "fmt": "gnu",
                "id": "some_lint_tool", "tier": 2, "fix_cmd": "some-lint --fix",
            }],
        )
        assert "some-lint-tool" in cfg.fixers

    def test_fixer_dry_run_returns_entries(self):
        tool = {
            "label": "t", "cmd": "echo", "fmt": "gnu",
            "id": "test_fixer_dry", "tier": 2, "fix_cmd": "echo --fix",
        }
        fixer = _make_generic_fixer(tool)
        entries = [{"file": "a.x", "line": 1}, {"file": "b.x", "line": 2}]
        result = fixer.fix(entries, dry_run=True, path=Path("."))
        assert len(result.entries) == 2
        assert result.entries[0]["file"] == "a.x"

    def test_fixer_detect_calls_tool(self):
        tool = {
            "label": "t", "cmd": "echo 'a.x:1: error'", "fmt": "gnu",
            "id": "test_fixer_detect", "tier": 2, "fix_cmd": "echo --fix",
        }
        fixer = _make_generic_fixer(tool)
        mock_result = subprocess.CompletedProcess(
            args="fake", returncode=1, stdout="a.x:1: some error\n", stderr="",
        )
        with patch(
            "desloppify.languages._framework.generic.subprocess.run",
            return_value=mock_result,
        ):
            entries = fixer.detect(Path("."))
        assert len(entries) == 1
        assert entries[0]["file"] == "a.x"

    def test_fixer_fix_handles_tool_unavailable(self):
        tool = {
            "label": "t", "cmd": "echo", "fmt": "gnu",
            "id": "test_fixer_unavail", "tier": 2, "fix_cmd": "nonexistent_tool_xyz",
        }
        fixer = _make_generic_fixer(tool)
        entries = [{"file": "a.x", "line": 1}]
        with patch(
            "desloppify.languages._framework.generic.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = fixer.fix(entries, dry_run=False, path=Path("."))
        assert result.skip_reasons == {"tool_unavailable": 1}


# ── Capability report tests ──────────────────────────────


@pytest.mark.usefixtures("_cleanup_registry")
class TestCapabilityReport:
    def test_full_plugin_returns_none(self):
        from desloppify.languages._framework.base.types import LangConfig

        cfg = LangConfig(
            name="test_full", extensions=[".py"], exclusions=[],
            default_src=".", build_dep_graph=lambda p: {},
            entry_patterns=[], barrel_names=set(),
        )
        cfg.integration_depth = "full"
        assert capability_report(cfg) is None

    def test_generic_plugin_reports_present_and_missing(self):
        cfg = generic_lang(
            name="test_cap_1",
            extensions=[".x"],
            tools=[{"label": "xlint", "cmd": "echo", "fmt": "gnu", "id": "test_cap_det_1", "tier": 2}],
        )
        present, missing = capability_report(cfg)
        assert "linting (xlint)" in present
        assert "security scan" in present
        assert "import analysis" in missing
        assert "function extraction" in missing
        assert "auto-fix" in missing

    def test_generic_plugin_with_fixer_reports_auto_fix(self):
        cfg = generic_lang(
            name="test_cap_2",
            extensions=[".x"],
            tools=[{
                "label": "xlint", "cmd": "echo", "fmt": "gnu",
                "id": "test_cap_det_2", "tier": 2, "fix_cmd": "xlint --fix",
            }],
        )
        present, missing = capability_report(cfg)
        assert "auto-fix" in present
        assert "auto-fix" not in missing
