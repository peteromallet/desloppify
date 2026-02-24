"""Tests for the subjective code review system (review.py, commands/review/cmd.py)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from desloppify import state as state_mod
from desloppify.app.commands.review import batches as review_batches_mod
from desloppify.app.commands.review.batch import (
    _do_run_batches,
)
from desloppify.app.commands.review.import_cmd import do_import as _do_import
from desloppify.app.commands.review.import_cmd import (
    do_validate_import as _do_validate_import,
)
from desloppify.app.commands.review.prepare import do_prepare as _do_prepare
from desloppify.app.commands.review.runtime import setup_lang_concrete as _setup_lang
from desloppify.engine.policy.zones import Zone, ZoneRule
from desloppify.intelligence.review import (
    import_holistic_findings,
    import_review_findings,
)
from desloppify.intelligence.review.importing.per_file import update_review_cache
from desloppify.state import empty_state as build_empty_state
from desloppify.tests.review.shared_review_fixtures import (
    _as_review_payload,
    prepare_review,
)


class TestBatchDimensionCoverageNotices:
    def test_preflight_notice_warns_when_scope_is_subset(self, capsys):
        review_batches_mod._print_preflight_dimension_scope_notice(
            selected_dims=["high_level_elegance", "mid_level_elegance"],
            scored_dims=[
                "high_level_elegance",
                "mid_level_elegance",
                "low_level_elegance",
            ],
            explicit_selection=False,
            scan_path=".",
            colorize_fn=lambda text, _tone: text,
        )

        out = capsys.readouterr().out
        assert "targets 2/3 scored subjective dimensions" in out
        assert "Missing from this run: low_level_elegance" in out
        assert "--dimensions low_level_elegance" in out

    def test_import_notice_warns_and_returns_missing_dimensions(self, capsys):
        missing = review_batches_mod._print_import_dimension_coverage_notice(
            assessed_dims=["naming_quality", "logic_clarity"],
            scored_dims=[
                "naming_quality",
                "logic_clarity",
                "type_safety",
            ],
            scan_path="src",
            colorize_fn=lambda text, _tone: text,
        )

        out = capsys.readouterr().out
        assert missing == ["type_safety"]
        assert "imported assessments for 2/3 scored subjective dimensions" in out
        assert "Still missing: type_safety" in out
        assert "--path src --dimensions type_safety" in out


class TestCmdReviewPrepare:
    def test_do_prepare_writes_query_json(
        self, mock_lang_with_zones, empty_state, tmp_path
    ):
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.ts").write_text("export function foo() {}\n" * 25)
        (src / "bar.ts").write_text("export function bar() {}\n" * 25)
        file_list = [str(src / "foo.ts"), str(src / "bar.ts")]
        mock_lang_with_zones.file_finder = MagicMock(return_value=file_list)

        query_output = {}

        def capture_query(data):
            query_output.update(data)

        args = MagicMock()
        args.path = str(tmp_path)
        args.max_files = 50
        args.max_age = 30
        args.refresh = False
        args.dimensions = None

        with (
            patch(
                "desloppify.app.commands.review.runtime.setup_lang_concrete",
                return_value=(mock_lang_with_zones, file_list),
            ),
            patch("desloppify.app.commands.review.prepare.write_query", capture_query),
        ):
            _do_prepare(
                args,
                empty_state,
                mock_lang_with_zones,
                None,
                config={},
            )

        assert query_output["command"] == "review"
        assert query_output["mode"] == "holistic"
        assert query_output["total_files"] >= 1
        assert "investigation_batches" in query_output
        assert "system_prompt" in query_output

    def test_do_import_saves_state(self, empty_state, tmp_path):
        findings = [
            {
                "dimension": "cross_module_architecture",
                "identifier": "process_data_coupling",
                "summary": "Cross-module coupling is inconsistent",
                "related_files": ["src/foo.ts", "src/bar.ts"],
                "evidence": ["Coordination logic is spread across entrypoints"],
                "confidence": "high",
                "suggestion": "consolidate coupling points",
            }
        ]
        findings_file = tmp_path / "findings.json"
        findings_file.write_text(json.dumps(findings))

        saved = {}

        def mock_save(state, sp):
            saved["state"] = state
            saved["sp"] = sp

        lang = MagicMock()
        lang.name = "typescript"

        # save_state is imported lazily: from ..state import save_state
        with patch("desloppify.state.save_state", mock_save):
            _do_import(str(findings_file), empty_state, lang, "fake_sp")

        assert saved["sp"] == "fake_sp"
        assert len(empty_state["findings"]) == 1

    def test_do_prepare_prints_narrative_reminders(self, mock_lang_with_zones, empty_state, tmp_path, capsys):
        from unittest.mock import MagicMock, patch

        from desloppify.app.commands.review.prepare import do_prepare as _do_prepare

        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.ts").write_text("export function foo() {}\n" * 25)
        file_list = [str(src / "foo.ts")]

        args = MagicMock()
        args.path = str(tmp_path)
        args.max_files = 50
        args.max_age = 30
        args.refresh = False
        args.dimensions = None
        args._config = {"review_max_age_days": 21, "review_dimensions": []}

        captured_kwargs = {}

        def _fake_narrative(_state, **kwargs):
            captured_kwargs.update(kwargs)
            return {"reminders": [{"type": "review_stale", "message": "Design review is stale."}]}

        with patch(
            "desloppify.app.commands.review.runtime.setup_lang_concrete",
            return_value=(mock_lang_with_zones, file_list),
        ), \
             patch("desloppify.app.commands.review.prepare.write_query", lambda _data: None), \
             patch("desloppify.intelligence.narrative.compute_narrative", _fake_narrative):
            _do_prepare(
                args,
                empty_state,
                mock_lang_with_zones,
                None,
                config=args._config,
            )

        out = capsys.readouterr().out
        assert "Holistic review prepared" in out
        assert captured_kwargs["context"].command == "review"

    def test_do_import_untrusted_assessment_only_payload_imports_findings_only(self, empty_state, tmp_path):
        from unittest.mock import MagicMock

        from desloppify.app.commands.review.import_cmd import do_import as _do_import

        empty_state["subjective_assessments"] = {
            "naming_quality": {"score": 90, "source": "per_file", "assessed_at": "2026-02-01T00:00:00Z"},
            "logic_clarity": {"score": 90, "source": "per_file", "assessed_at": "2026-02-01T00:00:00Z"},
        }
        payload = {
            "assessments": {"naming_quality": 40, "logic_clarity": 40},
            "findings": [],
        }
        findings_file = tmp_path / "findings_integrity_block.json"
        findings_file.write_text(json.dumps(payload))

        lang = MagicMock()
        lang.name = "typescript"

        _do_import(str(findings_file), empty_state, lang, tmp_path / "state.json")
        assert empty_state["subjective_assessments"]["naming_quality"]["score"] == 90
        audit = empty_state.get("assessment_import_audit", [])
        assert audit and audit[-1]["mode"] == "findings_only"

    def test_do_import_allows_override_with_note(self, empty_state, tmp_path):
        from unittest.mock import MagicMock, patch

        from desloppify.app.commands.review.import_cmd import do_import as _do_import

        empty_state["subjective_assessments"] = {
            "naming_quality": {"score": 90, "source": "per_file", "assessed_at": "2026-02-01T00:00:00Z"},
            "logic_clarity": {"score": 90, "source": "per_file", "assessed_at": "2026-02-01T00:00:00Z"},
        }
        payload = {
            "assessments": {"naming_quality": 40, "logic_clarity": 40},
            "findings": [],
        }
        findings_file = tmp_path / "findings_integrity_override.json"
        findings_file.write_text(json.dumps(payload))

        saved = {}

        def mock_save(state, sp):
            saved["state"] = state
            saved["sp"] = sp

        lang = MagicMock()
        lang.name = "typescript"

        with patch("desloppify.state.save_state", mock_save):
            _do_import(
                str(findings_file),
                empty_state,
                lang,
                "fake_sp",
                assessment_override=True,
                assessment_note="Manual calibration approved",
            )

        assert saved["sp"] == "fake_sp"
        assert empty_state["subjective_assessments"]["naming_quality"]["score"] == 40
        assert empty_state["subjective_assessments"]["naming_quality"]["source"] == "manual_override"
        assert (
            empty_state["subjective_assessments"]["naming_quality"]["provisional_override"]
            is True
        )
        assert (
            int(empty_state["subjective_assessments"]["naming_quality"]["provisional_until_scan"])
            == int(empty_state.get("scan_count", 0)) + 1
        )
        audit = empty_state.get("assessment_import_audit", [])
        assert audit and audit[-1]["override_used"] is True
        assert audit[-1]["provisional"] is True
        assert audit[-1]["provisional_count"] == 2

    def test_do_import_rejects_manual_override_with_allow_partial(
        self, empty_state, tmp_path
    ):
        from unittest.mock import MagicMock

        from desloppify.app.commands.review.import_cmd import do_import as _do_import

        payload = {
            "assessments": {"naming_quality": 40},
            "findings": [],
        }
        findings_file = tmp_path / "findings_invalid_combo.json"
        findings_file.write_text(json.dumps(payload))

        lang = MagicMock()
        lang.name = "typescript"

        with pytest.raises(SystemExit):
            _do_import(
                str(findings_file),
                empty_state,
                lang,
                tmp_path / "state.json",
                allow_partial=True,
                manual_override=True,
                manual_attest="operator note",
            )

    def test_trusted_internal_import_clears_provisional_flags(self, empty_state, tmp_path):
        from unittest.mock import MagicMock

        from desloppify.app.commands.review.import_cmd import do_import as _do_import

        empty_state["subjective_assessments"] = {
            "naming_quality": {
                "score": 40,
                "source": "manual_override",
                "assessed_at": "2026-02-01T00:00:00Z",
                "provisional_override": True,
                "provisional_until_scan": 7,
            }
        }
        payload = {
            "assessments": {"naming_quality": 100},
            "findings": [],
        }
        findings_file = tmp_path / "findings_trusted_internal.json"
        findings_file.write_text(json.dumps(payload))

        lang = MagicMock()
        lang.name = "typescript"

        _do_import(
            str(findings_file),
            empty_state,
            lang,
            tmp_path / "state.json",
            trusted_assessment_source=True,
            trusted_assessment_label="test trusted internal",
        )

        saved = empty_state["subjective_assessments"]["naming_quality"]
        assert saved["score"] == 100
        assert saved["source"] == "holistic"
        assert "provisional_override" not in saved
        assert "provisional_until_scan" not in saved

    def test_do_import_rebases_on_latest_saved_state(self, tmp_path):
        from unittest.mock import MagicMock

        from desloppify.app.commands.review.import_cmd import do_import as _do_import

        state_file = tmp_path / "state.json"
        latest_state = build_empty_state()
        latest_state["subjective_assessments"] = {
            "abstraction_fitness": {
                "score": 88,
                "source": "holistic",
                "assessed_at": "2026-02-24T00:00:00+00:00",
            }
        }
        latest_state["assessment_import_audit"] = [
            {
                "timestamp": "2026-02-24T00:00:00+00:00",
                "mode": "trusted_internal",
                "trusted": True,
                "reason": "seed",
                "override_used": False,
                "attested_external": False,
                "provisional": False,
                "provisional_count": 0,
                "attest": "",
                "import_file": "seed.json",
            }
        ]
        state_mod.save_state(latest_state, state_file)

        stale_state = build_empty_state()
        stale_state["subjective_assessments"] = {
            "naming_quality": {
                "score": 42,
                "source": "holistic",
                "assessed_at": "2026-02-01T00:00:00+00:00",
            }
        }

        payload = {
            "assessments": {"logic_clarity": 100},
            "findings": [],
        }
        findings_file = tmp_path / "findings_rebase.json"
        findings_file.write_text(json.dumps(payload))

        lang = MagicMock()
        lang.name = "typescript"

        _do_import(
            str(findings_file),
            stale_state,
            lang,
            state_file,
            trusted_assessment_source=True,
            trusted_assessment_label="trusted-rebase-test",
        )

        assessments = stale_state["subjective_assessments"]
        assert "abstraction_fitness" in assessments
        assert "logic_clarity" in assessments
        assert "naming_quality" not in assessments
        audit = stale_state.get("assessment_import_audit", [])
        assert len(audit) == 2
        assert audit[-1]["import_file"] == str(findings_file)

    def test_attested_external_import_applies_durable_assessment(
        self, empty_state, tmp_path
    ):
        from unittest.mock import MagicMock

        from desloppify.app.commands.review.import_cmd import do_import as _do_import

        blind_packet = tmp_path / "review_packet_blind.json"
        blind_packet.write_text(
            json.dumps({"command": "review", "dimensions": ["naming_quality"]})
        )
        packet_hash = hashlib.sha256(blind_packet.read_bytes()).hexdigest()
        payload = {
            "assessments": {"naming_quality": 100},
            "findings": [],
            "provenance": {
                "kind": "blind_review_batch_import",
                "blind": True,
                "runner": "claude",
                "packet_path": str(blind_packet),
                "packet_sha256": packet_hash,
            },
        }
        findings_file = tmp_path / "findings_attested_external.json"
        findings_file.write_text(json.dumps(payload))

        lang = MagicMock()
        lang.name = "typescript"

        _do_import(
            str(findings_file),
            empty_state,
            lang,
            tmp_path / "state.json",
            attested_external=True,
            manual_attest=(
                "I validated this review was completed without awareness of overall score "
                "and is unbiased."
            ),
        )

        saved = empty_state["subjective_assessments"]["naming_quality"]
        assert saved["score"] == 100
        assert saved["source"] == "holistic"
        assert "provisional_override" not in saved
        audit = empty_state.get("assessment_import_audit", [])
        assert audit and audit[-1]["mode"] == "attested_external"
        assert audit[-1]["attested_external"] is True

    def test_do_validate_import_reports_mode_without_state_mutation(
        self, empty_state, tmp_path, capsys
    ):
        blind_packet = tmp_path / "review_packet_blind.json"
        blind_packet.write_text(
            json.dumps({"command": "review", "dimensions": ["naming_quality"]})
        )
        packet_hash = hashlib.sha256(blind_packet.read_bytes()).hexdigest()
        payload = {
            "assessments": {"naming_quality": 100},
            "findings": [],
            "provenance": {
                "kind": "blind_review_batch_import",
                "blind": True,
                "runner": "claude",
                "packet_path": str(blind_packet),
                "packet_sha256": packet_hash,
            },
        }
        findings_file = tmp_path / "validate_findings.json"
        findings_file.write_text(json.dumps(payload))

        lang = MagicMock()
        lang.name = "typescript"

        _do_validate_import(
            str(findings_file),
            lang,
            attested_external=True,
            manual_attest=(
                "I validated this review was completed without awareness of overall score "
                "and is unbiased."
            ),
        )
        out = capsys.readouterr().out
        assert "Assessment import mode: attested external (durable scores)" in out
        assert "Import payload validation passed." in out
        assert "No state changes were made (--validate-import)." in out
        assert empty_state.get("subjective_assessments", {}) == {}

    def test_do_validate_import_rejects_manual_override_allow_partial_combo(
        self, tmp_path
    ):
        payload = {
            "assessments": {"naming_quality": 88},
            "findings": [],
        }
        findings_file = tmp_path / "validate_invalid_combo.json"
        findings_file.write_text(json.dumps(payload))
        lang = MagicMock()
        lang.name = "typescript"

        with pytest.raises(SystemExit):
            _do_validate_import(
                str(findings_file),
                lang,
                manual_override=True,
                manual_attest="operator note",
                allow_partial=True,
            )

    def test_do_import_rejects_nonexistent_file(self, empty_state):
        lang = MagicMock()
        lang.name = "typescript"

        with pytest.raises(SystemExit):
            _do_import("/nonexistent/findings.json", empty_state, lang, "sp")

    def test_do_import_rejects_non_array(self, empty_state, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"not": "an array"}')

        lang = MagicMock()
        lang.name = "typescript"

        with pytest.raises(SystemExit):
            _do_import(str(bad_file), empty_state, lang, "sp")

    def test_do_import_rejects_invalid_json(self, empty_state, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all")

        lang = MagicMock()
        lang.name = "typescript"

        with pytest.raises(SystemExit):
            _do_import(str(bad_file), empty_state, lang, "sp")

    def test_do_import_fails_closed_on_skipped_findings(self, empty_state, tmp_path):
        payload = {
            "assessments": {"cross_module_architecture": 95},
            "findings": [
                {
                    "dimension": "cross_module_architecture",
                    "identifier": "positive_observation",
                    "summary": "Good module boundaries across the codebase",
                    "related_files": ["src/a.ts"],
                    "evidence": ["Boundary modules align with feature folders"],
                    "suggestion": "No change needed",
                    "confidence": "high",
                }
            ],
        }
        findings_file = tmp_path / "partial.json"
        findings_file.write_text(json.dumps(payload))

        lang = MagicMock()
        lang.name = "typescript"

        with patch("desloppify.state.save_state") as mock_save:
            with pytest.raises(SystemExit):
                _do_import(str(findings_file), empty_state, lang, "sp")
        assert mock_save.called is False
        assert empty_state.get("subjective_assessments", {}) == {}
        assert empty_state.get("findings", {}) == {}

    def test_do_import_allow_partial_persists_when_overridden(
        self, empty_state, tmp_path
    ):
        payload = {
            "assessments": {"cross_module_architecture": 95},
            "findings": [
                {
                    "dimension": "cross_module_architecture",
                    "identifier": "positive_observation",
                    "summary": "Good module boundaries across the codebase",
                    "related_files": ["src/a.ts"],
                    "evidence": ["Boundary modules align with feature folders"],
                    "suggestion": "No change needed",
                    "confidence": "high",
                }
            ],
        }
        findings_file = tmp_path / "partial_allowed.json"
        findings_file.write_text(json.dumps(payload))

        lang = MagicMock()
        lang.name = "typescript"

        with patch("desloppify.state.save_state") as mock_save:
            _do_import(
                str(findings_file),
                empty_state,
                lang,
                "sp",
                allow_partial=True,
            )
        assert mock_save.called is True
        assert empty_state.get("subjective_assessments", {}) == {}
        audit = empty_state.get("assessment_import_audit", [])
        assert audit and audit[-1]["mode"] == "findings_only"

    def test_do_run_batches_dry_run_generates_packet_and_prompts(
        self,
        mock_lang_with_zones,
        empty_state,
        tmp_path,
    ):
        src = tmp_path / "src"
        src.mkdir()
        f1 = src / "foo.ts"
        f2 = src / "bar.ts"
        f1.write_text("export const foo = 1;\n")
        f2.write_text("export const bar = 2;\n")
        file_list = [str(f1), str(f2)]
        mock_lang_with_zones.file_finder = MagicMock(return_value=file_list)

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = True
        args.packet = None
        args.only_batches = None
        args.scan_after_import = False
        args.save_run_log = True
        args.run_log_file = None

        prepared = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": [
                "high_level_elegance",
                "mid_level_elegance",
                "low_level_elegance",
            ],
            "system_prompt": "prompt",
            "investigation_batches": [
                {
                    "name": "Architecture & Coupling",
                    "dimensions": ["high_level_elegance"],
                    "files_to_read": ["src/foo.ts"],
                    "why": "test",
                    "historical_issue_focus": {
                        "dimensions": ["high_level_elegance"],
                        "max_items": 20,
                        "selected_count": 1,
                        "issues": [
                            {
                                "dimension": "high_level_elegance",
                                "status": "open",
                                "summary": "Legacy surface remains primary",
                                "suggestion": "consolidate interfaces",
                                "related_files": ["src/a.ts"],
                                "note": "",
                                "confidence": "high",
                                "first_seen": "2026-02-20T10:00:00+00:00",
                                "last_seen": "2026-02-24T10:00:00+00:00",
                            }
                        ],
                    },
                },
                {
                    "name": "Conventions & Errors",
                    "dimensions": ["mid_level_elegance"],
                    "files_to_read": ["src/bar.ts"],
                    "why": "test",
                },
            ],
            "total_files": 2,
            "workflow": [],
        }

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        with (
            patch(
                "desloppify.app.commands.review.runtime.setup_lang_concrete",
                return_value=(mock_lang_with_zones, file_list),
            ),
            patch(
                "desloppify.app.commands.review.batch.review_mod.prepare_holistic_review",
                return_value=prepared,
            ),
            patch(
                "desloppify.app.commands.review.prepare.write_query",
            ),
            patch(
                "desloppify.app.commands.review.batch.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.batch.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch._do_import",
            ) as mock_import,
        ):
            _do_run_batches(
                args, empty_state, mock_lang_with_zones, "fake_sp", config={}
            )

        assert not mock_import.called
        packet_files = sorted(review_packet_dir.glob("holistic_packet_*.json"))
        assert len(packet_files) == 1
        blind_packet = tmp_path / ".desloppify" / "review_packet_blind.json"
        assert blind_packet.exists()
        prompt_files = list(runs_dir.glob("*/prompts/batch-*.md"))
        assert len(prompt_files) == 2
        prompt_text = prompt_files[0].read_text()
        assert "Blind packet:" in prompt_text
        assert str(blind_packet) in prompt_text
        assert "Previously flagged issues" in prompt_text
        assert "Legacy surface remains primary" in prompt_text
        run_logs = sorted(runs_dir.glob("*/run.log"))
        assert len(run_logs) == 1
        run_log_text = run_logs[0].read_text()
        assert "run-start" in run_log_text
        assert "run-finished dry-run" in run_log_text

    def test_do_run_batches_merges_outputs_and_imports(self, empty_state, tmp_path):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": [
                "high_level_elegance",
                "mid_level_elegance",
                "low_level_elegance",
            ],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["high_level_elegance", "mid_level_elegance"],
                    "files_to_read": ["src/a.ts", "src/b.ts"],
                    "why": "A",
                },
                {
                    "name": "Batch B",
                    "dimensions": ["high_level_elegance", "low_level_elegance"],
                    "files_to_read": ["src/c.ts", "src/d.ts"],
                    "why": "B",
                },
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = False
        args.allow_partial = False

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        def fake_subprocess_run(
            cmd,
            capture_output=False,
            text=False,
            timeout=None,
            cwd=None,
        ):
            _ = timeout, cwd
            out_path = Path(cmd[cmd.index("-o") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.name == "batch-1.raw.txt":
                payload = {
                    "assessments": {
                        "high_level_elegance": 70,
                        "mid_level_elegance": 65,
                    },
                    "dimension_notes": {
                        "high_level_elegance": {
                            "evidence": ["shared orchestration crosses module seams"],
                            "impact_scope": "subsystem",
                            "fix_scope": "multi_file_refactor",
                            "confidence": "high",
                            "issues_preventing_higher_score": "Cross-cutting regression risk remains.",
                        },
                        "mid_level_elegance": {
                            "evidence": ["handoff adapters are inconsistent"],
                            "impact_scope": "module",
                            "fix_scope": "single_edit",
                            "confidence": "medium",
                            "issues_preventing_higher_score": "",
                        },
                    },
                    "findings": [
                        {
                            "dimension": "high_level_elegance",
                            "identifier": "dup",
                            "summary": "shared",
                            "related_files": ["src/a.ts", "src/b.ts"],
                            "evidence": ["shared orchestration crosses module seams"],
                            "suggestion": "extract orchestration boundary policy into one module",
                            "confidence": "high",
                            "impact_scope": "subsystem",
                            "fix_scope": "multi_file_refactor",
                        },
                        {
                            "dimension": "mid_level_elegance",
                            "identifier": "handoff_adapter_drift",
                            "summary": "Handoff adapters drift between sibling modules",
                            "related_files": ["src/a.ts", "src/b.ts"],
                            "evidence": ["handoff adapters are inconsistent"],
                            "suggestion": "standardize one adapter protocol for handoff boundaries",
                            "confidence": "medium",
                            "impact_scope": "module",
                            "fix_scope": "single_edit",
                        },
                    ],
                }
            else:
                payload = {
                    "assessments": {
                        "high_level_elegance": 90,
                        "low_level_elegance": 80,
                    },
                    "dimension_notes": {
                        "high_level_elegance": {
                            "evidence": ["orchestration seams mostly consistent"],
                            "impact_scope": "module",
                            "fix_scope": "single_edit",
                            "confidence": "medium",
                            "issues_preventing_higher_score": "Some edge seams are still brittle.",
                        },
                        "low_level_elegance": {
                            "evidence": ["local internals remain concise"],
                            "impact_scope": "local",
                            "fix_scope": "single_edit",
                            "confidence": "medium",
                            "issues_preventing_higher_score": "",
                        },
                    },
                    "findings": [
                        {
                            "dimension": "high_level_elegance",
                            "identifier": "dup",
                            "summary": "shared",
                            "related_files": ["src/c.ts", "src/d.ts"],
                            "evidence": ["seam handling differs between sibling modules"],
                            "suggestion": "standardize orchestration seams through shared adapter",
                            "confidence": "high",
                            "impact_scope": "module",
                            "fix_scope": "single_edit",
                        },
                        {
                            "dimension": "low_level_elegance",
                            "identifier": "new",
                            "summary": "unique",
                            "related_files": ["src/c.ts", "src/d.ts"],
                            "evidence": ["local flow uses repetitive branching boilerplate"],
                            "suggestion": "extract one local helper to remove repeated branches",
                            "confidence": "medium",
                            "impact_scope": "local",
                            "fix_scope": "single_edit",
                        },
                    ],
                }
            out_path.write_text(json.dumps(payload))
            return MagicMock(returncode=0, stdout="ok", stderr="")

        captured: dict[str, object] = {}

        def fake_import(import_file, _state, _lang, _sp, holistic=True, config=None, **kwargs):
            captured["holistic"] = holistic
            captured["config"] = config
            captured["kwargs"] = kwargs
            captured["payload"] = json.loads(Path(import_file).read_text())

        lang = MagicMock()
        lang.name = "typescript"

        with (
            patch(
                "desloppify.app.commands.review.batch.subprocess.run",
                side_effect=fake_subprocess_run,
            ),
            patch(
                "desloppify.app.commands.review.batch.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.batch.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch._do_import",
                side_effect=fake_import,
            ),
        ):
            _do_run_batches(args, empty_state, lang, "fake_sp", config={})

        payload = captured["payload"]
        assert isinstance(payload, dict)
        assert payload["assessments"]["high_level_elegance"] == 71.5
        assert payload["assessments"]["mid_level_elegance"] == 62.1
        assert payload["assessments"]["low_level_elegance"] == 77.8
        assert payload["reviewed_files"] == ["src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts"]
        assert "dimension_notes" in payload
        assert "review_quality" in payload
        assert payload["review_quality"]["dimension_coverage"] == 0.667
        assert len(payload["findings"]) == 3
        provenance = payload.get("provenance", {})
        assert provenance.get("kind") == "blind_review_batch_import"
        assert provenance.get("blind") is True
        assert provenance.get("runner") == "codex"
        assert isinstance(provenance.get("packet_sha256"), str)
        assert captured["kwargs"]["trusted_assessment_source"] is True
        assert (
            captured["kwargs"]["trusted_assessment_label"]
            == "trusted internal run-batches import"
        )
        assert captured["kwargs"]["allow_partial"] is False
        summary_files = sorted(runs_dir.glob("*/run_summary.json"))
        assert len(summary_files) == 1
        summary_payload = json.loads(summary_files[0].read_text())
        assert summary_payload["failed_batches"] == []
        assert summary_payload["successful_batches"] == [1, 2]

    def test_do_run_batches_forwards_allow_partial_when_enabled(
        self, empty_state, tmp_path
    ):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": ["mid_level_elegance"],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["mid_level_elegance"],
                    "files_to_read": ["src/a.ts"],
                    "why": "A",
                }
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = False
        args.allow_partial = True

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        def fake_subprocess_run(
            cmd,
            capture_output=False,
            text=False,
            timeout=None,
            cwd=None,
        ):
            _ = capture_output, text, timeout, cwd
            out_path = Path(cmd[cmd.index("-o") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "assessments": {"mid_level_elegance": 77},
                "dimension_notes": {
                    "mid_level_elegance": {
                        "evidence": ["seams are mostly explicit"],
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                        "confidence": "medium",
                        "issues_preventing_higher_score": "",
                    }
                },
                "findings": [
                    {
                        "dimension": "mid_level_elegance",
                        "identifier": "seam_style_drift",
                        "summary": "Seam style drifts across adjacent modules",
                        "related_files": ["src/a.ts"],
                        "evidence": ["adjacent modules use incompatible seam conventions"],
                        "suggestion": "standardize one seam pattern for sibling modules",
                        "confidence": "medium",
                        "impact_scope": "module",
                        "fix_scope": "single_edit",
                    }
                ],
            }
            out_path.write_text(json.dumps(payload))
            return MagicMock(returncode=0, stdout="ok", stderr="")

        captured: dict[str, object] = {}

        def fake_import(import_file, _state, _lang, _sp, holistic=True, config=None, **kwargs):
            captured["holistic"] = holistic
            captured["config"] = config
            captured["kwargs"] = kwargs
            captured["payload"] = json.loads(Path(import_file).read_text())

        lang = MagicMock()
        lang.name = "typescript"

        with (
            patch(
                "desloppify.app.commands.review.batch.subprocess.run",
                side_effect=fake_subprocess_run,
            ),
            patch(
                "desloppify.app.commands.review.batch.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.batch.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch._do_import",
                side_effect=fake_import,
            ),
        ):
            _do_run_batches(args, empty_state, lang, "fake_sp", config={})

        assert captured["kwargs"]["allow_partial"] is True

    def test_do_run_batches_allow_partial_imports_successful_batches_when_one_fails(
        self, empty_state, tmp_path
    ):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": ["mid_level_elegance"],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["mid_level_elegance"],
                    "files_to_read": ["src/a.ts"],
                    "why": "A",
                },
                {
                    "name": "Batch B",
                    "dimensions": ["mid_level_elegance"],
                    "files_to_read": ["src/b.ts"],
                    "why": "B",
                },
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = False
        args.allow_partial = True

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        def fake_subprocess_run(
            cmd,
            capture_output=False,
            text=False,
            timeout=None,
            cwd=None,
        ):
            _ = capture_output, text, timeout, cwd
            out_path = Path(cmd[cmd.index("-o") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.name == "batch-1.raw.txt":
                out_path.write_text(
                    json.dumps(
                        {
                            "assessments": {"mid_level_elegance": 77},
                            "dimension_notes": {
                                "mid_level_elegance": {
                                    "evidence": ["explicit seams"],
                                    "impact_scope": "module",
                                    "fix_scope": "single_edit",
                                    "confidence": "medium",
                                    "issues_preventing_higher_score": "",
                                }
                            },
                            "findings": [
                                {
                                    "dimension": "mid_level_elegance",
                                    "identifier": "seam_style",
                                    "summary": "Seams drift slightly",
                                    "related_files": ["src/a.ts"],
                                    "evidence": ["interface seam style differs across nearby modules"],
                                    "suggestion": "normalize seam style to one interface pattern",
                                    "confidence": "medium",
                                    "impact_scope": "module",
                                    "fix_scope": "single_edit",
                                }
                            ],
                        }
                    )
                )
                return MagicMock(returncode=0, stdout="ok", stderr="")
            return MagicMock(returncode=124, stdout="", stderr="timed out")

        captured: dict[str, object] = {}

        def fake_import(import_file, _state, _lang, _sp, holistic=True, config=None, **kwargs):
            captured["holistic"] = holistic
            captured["config"] = config
            captured["kwargs"] = kwargs
            captured["payload"] = json.loads(Path(import_file).read_text())

        lang = MagicMock()
        lang.name = "typescript"

        with (
            patch(
                "desloppify.app.commands.review.batch.subprocess.run",
                side_effect=fake_subprocess_run,
            ),
            patch(
                "desloppify.app.commands.review.batch.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.batch.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch._do_import",
                side_effect=fake_import,
            ),
        ):
            _do_run_batches(args, empty_state, lang, "fake_sp", config={})

        payload = captured["payload"]
        assert payload["assessments"]["mid_level_elegance"] == pytest.approx(74.1, abs=0.1)
        assert payload["reviewed_files"] == ["src/a.ts"]
        assert captured["kwargs"]["allow_partial"] is True
        summary_files = sorted(runs_dir.glob("*/run_summary.json"))
        assert len(summary_files) == 1
        summary_payload = json.loads(summary_files[0].read_text())
        assert summary_payload["failed_batches"] == [2]
        assert summary_payload["successful_batches"] == [1]

    def test_do_run_batches_allow_partial_exits_when_no_batch_succeeds(
        self, empty_state, tmp_path
    ):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": ["mid_level_elegance"],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["mid_level_elegance"],
                    "files_to_read": ["src/a.ts"],
                    "why": "A",
                }
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = False
        args.allow_partial = True

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        def fake_subprocess_run(
            _cmd,
            capture_output=False,
            text=False,
            timeout=None,
            cwd=None,
        ):
            _ = capture_output, text, timeout, cwd
            return MagicMock(returncode=124, stdout="", stderr="timed out")

        lang = MagicMock()
        lang.name = "typescript"

        with (
            patch(
                "desloppify.app.commands.review.batch.subprocess.run",
                side_effect=fake_subprocess_run,
            ),
            patch(
                "desloppify.app.commands.review.batch.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.batch.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _do_run_batches(args, empty_state, lang, "fake_sp", config={})
        assert exc_info.value.code == 1

    def test_do_run_batches_keeps_abstraction_component_breakdown(
        self, empty_state, tmp_path
    ):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "python",
            "dimensions": ["abstraction_fitness"],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["abstraction_fitness"],
                    "files_to_read": ["src/a.py", "src/b.py"],
                    "why": "A",
                }
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = False

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        def fake_subprocess_run(
            cmd,
            capture_output=False,
            text=False,
            timeout=None,
            cwd=None,
        ):
            _ = capture_output, text, timeout, cwd
            out_path = Path(cmd[cmd.index("-o") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "assessments": {"abstraction_fitness": 72},
                "dimension_notes": {
                    "abstraction_fitness": {
                        "evidence": ["3 wrapper layers before domain call"],
                        "impact_scope": "subsystem",
                        "fix_scope": "multi_file_refactor",
                        "confidence": "high",
                        "issues_preventing_higher_score": "",
                        "sub_axes": {
                            "abstraction_leverage": 68,
                            "indirection_cost": 62,
                            "interface_honesty": 81,
                        },
                    },
                },
                "findings": [
                    {
                        "dimension": "abstraction_fitness",
                        "identifier": "wrapper_chain",
                        "summary": "Wrapper stack adds indirection cost",
                        "related_files": ["src/a.py", "src/b.py"],
                        "evidence": ["3 wrapper layers before reaching domain behavior"],
                        "suggestion": "collapse wrapper chain and expose one direct boundary",
                        "confidence": "high",
                        "impact_scope": "subsystem",
                        "fix_scope": "multi_file_refactor",
                    }
                ],
            }
            out_path.write_text(json.dumps(payload))
            return MagicMock(returncode=0, stdout="ok", stderr="")

        captured: dict[str, object] = {}

        def fake_import(import_file, _state, _lang, _sp, holistic=True, config=None, **kwargs):
            captured["holistic"] = holistic
            captured["config"] = config
            captured["kwargs"] = kwargs
            captured["payload"] = json.loads(Path(import_file).read_text())

        lang = MagicMock()
        lang.name = "python"

        with (
            patch(
                "desloppify.app.commands.review.batch.subprocess.run",
                side_effect=fake_subprocess_run,
            ),
            patch(
                "desloppify.app.commands.review.batch.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.batch.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch._do_import",
                side_effect=fake_import,
            ),
        ):
            _do_run_batches(args, empty_state, lang, "fake_sp", config={})

        payload = captured["payload"]
        assert isinstance(payload, dict)
        abstraction = payload["assessments"]["abstraction_fitness"]
        assert abstraction["score"] == 66.5
        assert abstraction["components"] == [
            "Abstraction Leverage",
            "Indirection Cost",
            "Interface Honesty",
        ]
        assert abstraction["component_scores"]["Abstraction Leverage"] == 68.0
        assert abstraction["component_scores"]["Indirection Cost"] == 62.0
        assert abstraction["component_scores"]["Interface Honesty"] == 81.0
        assert captured["kwargs"]["trusted_assessment_source"] is True

    def test_run_codex_batch_returns_127_when_runner_missing(self, tmp_path):
        from desloppify.app.commands.review import runner_helpers as runner_helpers_mod

        log_file = tmp_path / "batch.log"
        mock_run = MagicMock(side_effect=FileNotFoundError("codex not found"))
        code = runner_helpers_mod.run_codex_batch(
            prompt="test prompt",
            repo_root=tmp_path,
            output_file=tmp_path / "out.txt",
            log_file=log_file,
            deps=runner_helpers_mod.CodexBatchRunnerDeps(
                timeout_seconds=60,
                subprocess_run=mock_run,
                timeout_error=TimeoutError,
                safe_write_text_fn=lambda p, t: p.write_text(t),
            ),
        )
        assert code == 127
        assert "RUNNER ERROR" in log_file.read_text()

    def test_run_codex_batch_retries_stream_disconnect(self, tmp_path):
        from desloppify.app.commands.review import runner_helpers as runner_helpers_mod

        log_file = tmp_path / "batch.log"
        attempts = [
            MagicMock(
                returncode=1,
                stdout="",
                stderr=(
                    "ERROR: stream disconnected before completion: "
                    "error sending request for url (https://chatgpt.com/backend-api/codex/responses)"
                ),
            ),
            MagicMock(returncode=0, stdout="ok", stderr=""),
        ]
        mock_run = MagicMock(side_effect=attempts)
        code = runner_helpers_mod.run_codex_batch(
            prompt="test prompt",
            repo_root=tmp_path,
            output_file=tmp_path / "out.txt",
            log_file=log_file,
            deps=runner_helpers_mod.CodexBatchRunnerDeps(
                timeout_seconds=60,
                subprocess_run=mock_run,
                timeout_error=TimeoutError,
                safe_write_text_fn=lambda p, t: p.write_text(t),
                max_retries=1,
                retry_backoff_seconds=0.0,
                sleep_fn=lambda _seconds: None,
            ),
        )
        assert code == 0
        assert mock_run.call_count == 2
        raw_log = log_file.read_text()
        assert "ATTEMPT 1/2" in raw_log
        assert "ATTEMPT 2/2" in raw_log
        assert "Transient runner failure detected" in raw_log

    def test_run_codex_batch_writes_live_status_before_completion(self, tmp_path):
        from desloppify.app.commands.review import runner_helpers as runner_helpers_mod

        log_file = tmp_path / "batch.log"
        live_snapshot = {"text": ""}

        def fake_run(_cmd, *, capture_output, text, timeout):  # noqa: ARG001
            if log_file.exists():
                live_snapshot["text"] = log_file.read_text()
            return MagicMock(returncode=0, stdout="ok", stderr="")

        code = runner_helpers_mod.run_codex_batch(
            prompt="test prompt",
            repo_root=tmp_path,
            output_file=tmp_path / "out.txt",
            log_file=log_file,
            deps=runner_helpers_mod.CodexBatchRunnerDeps(
                timeout_seconds=60,
                subprocess_run=fake_run,
                timeout_error=TimeoutError,
                safe_write_text_fn=lambda p, t: p.write_text(t),
            ),
        )
        assert code == 0
        assert "STATUS: running" in live_snapshot["text"]
        assert "ATTEMPT 1/1" in live_snapshot["text"]
        assert "STDOUT:" in log_file.read_text()

    def test_print_failures_and_exit_shows_codex_missing_hint(self, tmp_path, capsys):
        from desloppify.app.commands.review import runner_helpers as runner_helpers_mod

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            "$ codex exec --ephemeral ...\n\nRUNNER ERROR:\n[Errno 2] No such file or directory: 'codex'\n"
        )
        with pytest.raises(SystemExit) as exc_info:
            runner_helpers_mod.print_failures_and_exit(
                failures=[0],
                packet_path=tmp_path / "packet.json",
                logs_dir=logs_dir,
                colorize_fn=lambda text, _style: text,
            )
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Environment hints:" in err
        assert "codex CLI not found on PATH" in err

    def test_print_failures_and_exit_shows_codex_auth_hint(self, tmp_path, capsys):
        from desloppify.app.commands.review import runner_helpers as runner_helpers_mod

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            "$ codex exec --ephemeral ...\n\nSTDERR:\nAuthentication failed: please login first.\n"
        )
        with pytest.raises(SystemExit) as exc_info:
            runner_helpers_mod.print_failures_and_exit(
                failures=[0],
                packet_path=tmp_path / "packet.json",
                logs_dir=logs_dir,
                colorize_fn=lambda text, _style: text,
            )
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Environment hints:" in err
        assert "codex login" in err

    def test_print_failures_reports_categories_without_exit(self, tmp_path, capsys):
        from desloppify.app.commands.review import runner_helpers as runner_helpers_mod

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text("$ codex ...\nTIMEOUT after 60s\n")
        (logs_dir / "batch-2.log").write_text(
            "$ codex ...\nSTDERR:\nAuthentication failed: please login first.\n"
        )

        runner_helpers_mod.print_failures(
            failures=[0, 1, 2],
            packet_path=tmp_path / "packet.json",
            logs_dir=logs_dir,
            colorize_fn=lambda text, _style: text,
        )
        err = capsys.readouterr().err
        assert "Failure categories:" in err
        assert "timeout=1" in err
        assert "runner auth=1" in err
        assert "missing log=1" in err

    def test_print_failures_reports_stream_disconnect_category(self, tmp_path, capsys):
        from desloppify.app.commands.review import runner_helpers as runner_helpers_mod

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch-1.log").write_text(
            "$ codex ...\nSTDERR:\nERROR: stream disconnected before completion\n"
        )

        runner_helpers_mod.print_failures(
            failures=[0],
            packet_path=tmp_path / "packet.json",
            logs_dir=logs_dir,
            colorize_fn=lambda text, _style: text,
        )
        err = capsys.readouterr().err
        assert "Failure categories:" in err
        assert "stream disconnect=1" in err
        assert "Connectivity tuning:" in err

    def test_run_followup_scan_returns_nonzero_code(self, tmp_path):
        from desloppify.app.commands.review import runner_helpers as runner_helpers_mod

        mock_run = MagicMock(return_value=MagicMock(returncode=9))
        code = runner_helpers_mod.run_followup_scan(
            lang_name="typescript",
            scan_path=str(tmp_path),
            deps=runner_helpers_mod.FollowupScanDeps(
                project_root=tmp_path,
                timeout_seconds=60,
                python_executable="python",
                subprocess_run=mock_run,
                timeout_error=TimeoutError,
                colorize_fn=lambda text, _: text,
            ),
        )
        assert code == 9

    def test_do_run_batches_scan_after_import_exits_on_failed_followup(
        self, empty_state, tmp_path
    ):
        packet = {
            "command": "review",
            "mode": "holistic",
            "language": "typescript",
            "dimensions": ["high_level_elegance"],
            "investigation_batches": [
                {
                    "name": "Batch A",
                    "dimensions": ["high_level_elegance"],
                    "files_to_read": ["src/a.ts"],
                    "why": "A",
                }
            ],
        }
        packet_path = tmp_path / "packet.json"
        packet_path.write_text(json.dumps(packet))

        args = MagicMock()
        args.path = str(tmp_path)
        args.dimensions = None
        args.runner = "codex"
        args.parallel = False
        args.dry_run = False
        args.packet = str(packet_path)
        args.only_batches = None
        args.scan_after_import = True

        review_packet_dir = tmp_path / ".desloppify" / "review_packets"
        runs_dir = tmp_path / ".desloppify" / "subagents" / "runs"

        lang = MagicMock()
        lang.name = "typescript"

        with (
            patch(
                "desloppify.app.commands.review.batch.PROJECT_ROOT",
                tmp_path,
            ),
            patch(
                "desloppify.app.commands.review.batch.REVIEW_PACKET_DIR",
                review_packet_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch.SUBAGENT_RUNS_DIR",
                runs_dir,
            ),
            patch(
                "desloppify.app.commands.review.batch._do_import",
            ),
            patch(
                "desloppify.app.commands.review.batch.runner_helpers_mod.execute_batches",
                return_value=[],
            ),
            patch(
                "desloppify.app.commands.review.batch.runner_helpers_mod.collect_batch_results",
                return_value=([{"assessments": {}, "dimension_notes": {}, "findings": []}], []),
            ),
            patch(
                "desloppify.app.commands.review.batch._merge_batch_results",
                return_value={"assessments": {}, "dimension_notes": {}, "findings": []},
            ),
            patch(
                "desloppify.app.commands.review.runner_helpers.run_followup_scan",
                return_value=7,
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _do_run_batches(args, empty_state, lang, "fake_sp", config={})

        assert exc_info.value.code == 7


class TestSetupLang:
    def test_setup_builds_zone_map(self, tmp_path):
        lang = MagicMock()
        lang.name = "typescript"
        lang.zone_map = None
        lang.dep_graph = None
        lang.build_dep_graph = None
        lang.zone_rules = [ZoneRule(Zone.TEST, ["/tests/"])]
        f1 = str(tmp_path / "src" / "foo.ts")
        f2 = str(tmp_path / "tests" / "foo.test.ts")
        lang.file_finder = MagicMock(return_value=[f1, f2])

        lang_run, files = _setup_lang(lang, tmp_path, {})
        assert files == [f1, f2]
        assert lang_run.zone_map is not None

    def test_setup_returns_files(self, tmp_path):
        lang = MagicMock()
        lang.name = "typescript"
        lang.zone_map = None
        lang.dep_graph = None
        lang.build_dep_graph = None
        lang.zone_rules = []
        lang.file_finder = None

        _lang_run, files = _setup_lang(lang, tmp_path, {})
        assert files == []

    def test_setup_builds_dep_graph(self, tmp_path):
        fake_graph = {"a.ts": {"imports": set(), "importers": set()}}
        lang = MagicMock()
        lang.name = "typescript"
        lang.zone_map = None
        lang.dep_graph = None
        lang.zone_rules = []
        lang.file_finder = None
        lang.build_dep_graph = MagicMock(return_value=fake_graph)

        lang_run, _files = _setup_lang(lang, tmp_path, {})
        assert lang_run.dep_graph == fake_graph

    def test_setup_dep_graph_error_nonfatal(self, tmp_path):
        lang = MagicMock()
        lang.name = "typescript"
        lang.zone_map = None
        lang.dep_graph = None
        lang.zone_rules = []
        lang.file_finder = None
        lang.build_dep_graph = MagicMock(side_effect=RuntimeError("boom"))

        lang_run, files = _setup_lang(lang, tmp_path, {})
        assert files == []
        assert lang_run.dep_graph is None  # Not set due to error


# ── update_review_cache robustness test ─────────────────────────


class TestUpdateReviewCache:
    def test_cache_created_from_scratch(
        self, empty_state, sample_findings_data, tmp_path
    ):
        with patch("desloppify.intelligence.review.importing.per_file.PROJECT_ROOT", tmp_path):
            (tmp_path / "src").mkdir(exist_ok=True)
            (tmp_path / "src" / "foo.ts").write_text("content")
            (tmp_path / "src" / "bar.ts").write_text("content")
            update_review_cache(empty_state, sample_findings_data)
        assert "review_cache" in empty_state
        assert "files" in empty_state["review_cache"]

    def test_cache_survives_partial_review_cache(self, sample_findings_data, tmp_path):
        """If review_cache exists without files key, shouldn't crash."""
        state = {"review_cache": {}}  # No "files" key
        with patch("desloppify.intelligence.review.importing.per_file.PROJECT_ROOT", tmp_path):
            (tmp_path / "src").mkdir(exist_ok=True)
            (tmp_path / "src" / "foo.ts").write_text("content")
            (tmp_path / "src" / "bar.ts").write_text("content")
            update_review_cache(state, sample_findings_data)
        assert "files" in state["review_cache"]

    def test_file_finder_called_once_in_prepare(self, mock_lang, empty_state, tmp_path):
        """prepare_review should call file_finder exactly once."""
        f = tmp_path / "foo.ts"
        f.write_text("export function getData() { return 42; }\n" * 25)
        mock_lang.file_finder = MagicMock(return_value=[str(f)])

        prepare_review(tmp_path, mock_lang, empty_state)
        # file_finder should be called exactly once (by prepare_review itself)
        assert mock_lang.file_finder.call_count == 1


# ── Skipped findings tests ────────────────────────────────────────


class TestSkippedFindings:
    """Findings missing required fields are tracked and reported."""

    def test_per_file_skipped_missing_fields(self):
        state = build_empty_state()
        data = {
            "findings": [
                # Valid finding
                {
                    "file": "src/a.ts",
                    "dimension": "naming_quality",
                    "identifier": "x",
                    "summary": "bad",
                    "confidence": "high",
                },
                # Missing 'identifier'
                {
                    "file": "src/b.ts",
                    "dimension": "naming_quality",
                    "summary": "bad",
                    "confidence": "high",
                },
                # Missing 'confidence'
                {
                    "file": "src/c.ts",
                    "dimension": "naming_quality",
                    "identifier": "y",
                    "summary": "bad",
                },
            ],
        }
        diff = import_review_findings(_as_review_payload(data), state, "typescript")
        assert diff["new"] == 1
        assert diff["skipped"] == 2
        assert len(diff["skipped_details"]) == 2
        assert "identifier" in diff["skipped_details"][0]["missing"]
        assert "confidence" in diff["skipped_details"][1]["missing"]

    def test_per_file_invalid_dimension_skipped(self):
        state = build_empty_state()
        data = {
            "findings": [
                {
                    "file": "src/a.ts",
                    "dimension": "bogus_dimension",
                    "identifier": "x",
                    "summary": "bad",
                    "confidence": "high",
                },
            ],
        }
        diff = import_review_findings(_as_review_payload(data), state, "typescript")
        assert diff["new"] == 0
        assert diff["skipped"] == 1
        assert "invalid dimension" in diff["skipped_details"][0]["missing"][0]

    def test_holistic_skipped_missing_fields(self):
        state = build_empty_state()
        data = {
            "findings": [
                # Valid
                {
                    "dimension": "cross_module_architecture",
                    "identifier": "god_mod",
                    "summary": "too central",
                    "confidence": "high",
                    "suggestion": "split it",
                },
                # Missing 'summary' and 'suggestion'
                {
                    "dimension": "cross_module_architecture",
                    "identifier": "god_mod2",
                    "confidence": "high",
                },
            ],
        }
        diff = import_holistic_findings(_as_review_payload(data), state, "typescript")
        assert diff["new"] == 1
        assert diff["skipped"] == 1
        assert any(
            f in diff["skipped_details"][0]["missing"]
            for f in ("summary", "suggestion")
        )

    def test_no_skipped_when_all_valid(self):
        state = build_empty_state()
        data = {
            "findings": [
                {
                    "file": "src/a.ts",
                    "dimension": "naming_quality",
                    "identifier": "x",
                    "summary": "bad",
                    "confidence": "high",
                },
            ],
        }
        diff = import_review_findings(_as_review_payload(data), state, "typescript")
        assert diff["new"] == 1
        assert "skipped" not in diff


# ── Auto-resolve on re-import tests ──────────────────────────────


class TestAutoResolveOnReImport:
    """Old findings should auto-resolve when re-imported without them."""

    def test_holistic_import_preserves_existing_mechanical_potentials(self):
        state = build_empty_state()
        state["potentials"] = {"typescript": {"unused": 12, "smells": 40}}
        data = {
            "findings": [
                {
                    "dimension": "cross_module_architecture",
                    "identifier": "god_mod",
                    "summary": "too central",
                    "confidence": "high",
                    "suggestion": "split it",
                },
            ],
        }
        import_holistic_findings(_as_review_payload(data), state, "typescript")

        pots = state["potentials"]["typescript"]
        assert pots["unused"] == 12
        assert pots["smells"] == 40
        assert pots.get("review", 0) > 0

    def test_holistic_auto_resolve_on_reimport(self):
        state = build_empty_state()

        # First import: 2 holistic findings
        data1 = {
            "findings": [
                {
                    "dimension": "cross_module_architecture",
                    "identifier": "god_mod",
                    "summary": "too central",
                    "confidence": "high",
                    "suggestion": "split it",
                },
                {
                    "dimension": "abstraction_fitness",
                    "identifier": "util_dump",
                    "summary": "dumping ground",
                    "confidence": "medium",
                    "suggestion": "extract domains",
                },
            ],
        }
        diff1 = import_holistic_findings(_as_review_payload(data1), state, "typescript")
        assert diff1["new"] == 2
        open_ids = [
            fid for fid, f in state["findings"].items() if f["status"] == "open"
        ]
        assert len(open_ids) == 2

        # Second import: only 1 finding (different from first)
        data2 = {
            "findings": [
                {
                    "dimension": "error_consistency",
                    "identifier": "mixed_errors",
                    "summary": "mixed strategies",
                    "confidence": "high",
                    "suggestion": "consolidate error handling",
                },
            ],
        }
        diff2 = import_holistic_findings(_as_review_payload(data2), state, "typescript")
        assert diff2["new"] == 1
        # The 2 old findings should be auto-resolved
        assert diff2["auto_resolved"] >= 2
        still_open = [
            fid for fid, f in state["findings"].items() if f["status"] == "open"
        ]
        assert len(still_open) == 1

    def test_per_file_auto_resolve_on_reimport(self):
        state = build_empty_state()

        # First import: findings for src/a.ts
        data1 = {
            "findings": [
                {
                    "file": "src/a.ts",
                    "dimension": "naming_quality",
                    "identifier": "x",
                    "summary": "bad name",
                    "confidence": "high",
                },
                {
                    "file": "src/a.ts",
                    "dimension": "comment_quality",
                    "identifier": "y",
                    "summary": "stale comment",
                    "confidence": "medium",
                },
            ],
        }
        diff1 = import_review_findings(_as_review_payload(data1), state, "typescript")
        assert diff1["new"] == 2

        # Second import: re-review src/a.ts but only 1 finding remains
        data2 = {
            "findings": [
                {
                    "file": "src/a.ts",
                    "dimension": "naming_quality",
                    "identifier": "x",
                    "summary": "bad name",
                    "confidence": "high",
                },
            ],
        }
        import_review_findings(_as_review_payload(data2), state, "typescript")
        # The comment_quality finding should be auto-resolved
        resolved = [
            f
            for f in state["findings"].values()
            if f["status"] == "auto_resolved"
            and "not reported in latest per-file" in (f.get("note") or "")
        ]
        assert len(resolved) >= 1

    def test_holistic_does_not_resolve_per_file(self):
        """Holistic re-import should not touch per-file review findings."""
        state = build_empty_state()

        # Import per-file findings
        per_file = {
            "findings": [
                {
                    "file": "src/a.ts",
                    "dimension": "naming_quality",
                    "identifier": "x",
                    "summary": "bad name",
                    "confidence": "high",
                },
            ],
        }
        import_review_findings(_as_review_payload(per_file), state, "typescript")
        per_file_ids = [
            fid for fid, f in state["findings"].items() if f["status"] == "open"
        ]
        assert len(per_file_ids) == 1

        # Import holistic findings (empty) — should NOT resolve per-file
        holistic = {"findings": []}
        import_holistic_findings(_as_review_payload(holistic), state, "typescript")
        # Per-file finding should still be open
        assert state["findings"][per_file_ids[0]]["status"] == "open"
