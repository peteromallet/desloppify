"""Generic plugin scoring/narrative/shared-phase/fixer/capability integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from desloppify.languages._framework.generic_support.core import capability_report, generic_lang
from desloppify.languages._framework.generic_parts.tool_factories import (
    make_generic_fixer,
)


@pytest.fixture
def _cleanup_registry():
    """Auto-cleanup generic plugins registered during a test."""
    from desloppify.languages._framework.registry import state as registry_state
    from desloppify.languages._framework.registry.discovery import load_all

    load_all()
    before = set(registry_state.all_keys())
    yield
    for name in set(registry_state.all_keys()) - before:
        registry_state.remove(name)


class TestScoringIntegration:
    def test_generic_issues_contribute_to_code_quality_dimension(self):
        from desloppify.engine._scoring.policy.core import DIMENSIONS

        generic_lang(
            name="test_scoring_1",
            extensions=[".x"],
            tools=[{"label": "t", "cmd": "echo", "fmt": "gnu", "id": "test_score_det_1", "tier": 2}],
        )
        cq = next(d for d in DIMENSIONS if d.name == "Code quality")
        assert "test_score_det_1" in cq.detectors

    def test_generic_issues_score_with_correct_tier(self):
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
        fixer = make_generic_fixer(tool)
        entries = [{"file": "a.x", "line": 1}, {"file": "b.x", "line": 2}]
        result = fixer.fix(entries, dry_run=True, path=Path("."))
        assert len(result.entries) == 2
        assert result.entries[0]["file"] == "a.x"

    def test_fixer_detect_calls_tool(self):
        tool = {
            "label": "t", "cmd": "echo 'a.x:1: error'", "fmt": "gnu",
            "id": "test_fixer_detect", "tier": 2, "fix_cmd": "echo --fix",
        }
        fixer = make_generic_fixer(tool)
        mock_result = subprocess.CompletedProcess(
            args="fake", returncode=1, stdout="a.x:1: some error\n", stderr="",
        )
        with patch(
            "desloppify.languages._framework.generic_parts.tool_runner.subprocess.run",
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
        fixer = make_generic_fixer(tool)
        entries = [{"file": "a.x", "line": 1}]
        with patch(
            "desloppify.languages._framework.generic_parts.tool_factories.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = fixer.fix(entries, dry_run=False, path=Path("."))
        assert result.skip_reasons == {"tool_unavailable": 1}

    def test_fixer_takes_scan_path(self):
        tool = {
            "label": "t", "cmd": "echo", "fmt": "gnu",
            "id": "test_fixer_path_flag", "tier": 2, "fix_cmd": "echo --fix",
        }
        assert make_generic_fixer(tool).takes_scan_path is True

    def test_fixer_dry_run_groups_issues_by_file(self):
        tool = {
            "label": "t", "cmd": "echo", "fmt": "gnu",
            "id": "test_fixer_dry_group", "tier": 2, "fix_cmd": "echo --fix",
        }
        fixer = make_generic_fixer(tool)
        entries = [
            {"file": "a.x", "line": 1},
            {"file": "a.x", "line": 2},
            {"file": "b.x", "line": 3},
        ]
        result = fixer.fix(entries, dry_run=True)
        assert result.entries == [
            {"file": "a.x", "fixed_count": 2, "summary": "2 issues"},
            {"file": "b.x", "fixed_count": 1, "summary": "1 issue"},
        ]

    def test_fixer_requires_path_to_apply(self):
        tool = {
            "label": "t", "cmd": "echo", "fmt": "gnu",
            "id": "test_fixer_no_path", "tier": 2, "fix_cmd": "echo --fix",
        }
        fixer = make_generic_fixer(tool)
        with pytest.raises(ValueError):
            fixer.fix([{"file": "a.x", "line": 1}], dry_run=False)

    def test_fixer_counts_fixed_issues_per_file(self):
        tool = {
            "label": "t", "cmd": "lint", "fmt": "gnu",
            "id": "test_fixer_per_file", "tier": 2, "fix_cmd": "lint --fix",
        }
        outputs = [
            subprocess.CompletedProcess(args="fix", returncode=1, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args="lint", returncode=1, stdout="a.x:9: still wrong\n", stderr="",
            ),
        ]
        fixer = make_generic_fixer(tool, run_subprocess=lambda *a, **k: outputs.pop(0))
        entries = [
            {"file": "a.x", "line": 1},
            {"file": "a.x", "line": 2},
            {"file": "b.x", "line": 3},
        ]
        result = fixer.fix(entries, dry_run=False, path=Path("."))
        assert result.entries == [
            {"file": "a.x", "fixed": True, "fixed_count": 1, "summary": "1 fixed"},
            {"file": "b.x", "fixed": True, "fixed_count": 1, "summary": "1 fixed"},
        ]
        assert result.skip_reasons == {}

    def test_fixer_claims_nothing_when_recheck_fails(self):
        tool = {
            "label": "t", "cmd": "lint", "fmt": "json",
            "id": "test_fixer_recheck_fail", "tier": 2, "fix_cmd": "lint --fix",
        }
        outputs = [
            subprocess.CompletedProcess(args="fix", returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(args="lint", returncode=1, stdout="not json", stderr=""),
        ]
        fixer = make_generic_fixer(tool, run_subprocess=lambda *a, **k: outputs.pop(0))
        result = fixer.fix([{"file": "a.x", "line": 1}], dry_run=False, path=Path("."))
        assert result.entries == []
        assert result.skip_reasons == {"recheck_failed": 1}


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
