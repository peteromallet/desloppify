"""Additional direct-coverage smoke tests for transitively covered modules."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import desloppify.app.commands.plan.cmd as plan_cmd_mod
import desloppify.app.commands.helpers.lazy_exports as lazy_exports_mod
import desloppify.app.commands.plan.move_handlers as plan_move_handlers_mod
import desloppify.app.commands.plan.override_handlers as plan_override_handlers_mod
import desloppify.app.commands.review.quality.assessment_integrity as review_assessment_integrity
import desloppify.app.commands.review.batch_prompt_template as review_batch_prompt_template
import desloppify.app.commands.review.runtime as review_runtime_pkg
import desloppify.app.commands.scan.scan_coverage as scan_coverage_mod
import desloppify.app.commands.scan.scan_orchestrator as scan_orchestrator_mod
import desloppify.app.commands.scan.scan_reporting_text as scan_reporting_text_mod
import desloppify.app.commands.scan.scan_wontfix as scan_wontfix_mod
import desloppify.app.output.scorecard_parts.dimension_policy as dimension_policy_mod
import desloppify.core as core_pkg
import desloppify.core._internal.coercions as coercions_mod
import desloppify.core.enums as enums_mod
import desloppify.core.grep as grep_mod
import desloppify.core.output as output_mod
import desloppify.core.query_paths as query_paths_mod
import desloppify.core.skill_docs as skill_docs_mod
import desloppify.engine._plan.persistence as plan_persistence_mod
import desloppify.engine.planning as planning_pkg
import desloppify.engine.planning.dimension_rows as planning_dimension_rows_mod
import desloppify.engine.planning.queue_policy as queue_policy_mod
import desloppify.languages.go.commands as go_commands_mod
import desloppify.languages.go.detectors.deps as go_deps_mod
import desloppify.languages.go.move as go_move_mod
import desloppify.languages.go.phases as go_phases_mod
import desloppify.languages.go.review as go_review_mod
import desloppify.languages.typescript.fixers.import_rewrite as ts_import_rewrite_mod
import desloppify.languages.typescript.syntax.scanner as ts_scanner_mod


def _assert_all_callables(*targets) -> None:
    for target in targets:
        assert callable(target), f"Expected callable target, got {target!r}"  # nosec B101


def test_plan_review_helpers_smoke() -> None:
    _assert_all_callables(
        plan_cmd_mod.cmd_plan,
        plan_move_handlers_mod.cmd_plan_move,
        plan_override_handlers_mod.cmd_plan_done,
        plan_override_handlers_mod.cmd_plan_skip,
        review_assessment_integrity.subjective_at_target_dimensions,
        review_assessment_integrity.bind_scorecard_subjective_at_target,
        review_batch_prompt_template.render_batch_prompt,
    )


def test_lazy_exports_runtime_core_queue_policy_smoke() -> None:
    _assert_all_callables(
        lazy_exports_mod.lazy_module_getattr,
        lazy_exports_mod.lazy_module_dir,
        review_runtime_pkg.setup_lang,
        review_runtime_pkg.setup_lang_concrete,
        queue_policy_mod.build_open_plan_queue,
    )
    assert isinstance(core_pkg.__all__, list)  # nosec B101
    assert callable(core_pkg.__getattr__)  # nosec B101
    assert isinstance(review_runtime_pkg.__all__, list)  # nosec B101
    assert "runner_helpers" in review_runtime_pkg.__all__  # nosec B101
    assert callable(ts_scanner_mod.scan_code)  # nosec B101


def test_scan_core_engine_go_smoke() -> None:
    _assert_all_callables(
        scan_coverage_mod.persist_scan_coverage,
        scan_coverage_mod.seed_runtime_coverage_warnings,
        scan_orchestrator_mod.ScanOrchestrator,
        scan_reporting_text_mod.build_workflow_guide,
        scan_wontfix_mod.augment_with_stale_wontfix_findings,
        coercions_mod.coerce_positive_int,
        coercions_mod.coerce_non_negative_float,
        enums_mod.canonical_finding_status,
        enums_mod.finding_status_tokens,
        grep_mod.grep_files,
        grep_mod.grep_count_files,
        output_mod.colorize,
        output_mod.print_table,
        query_paths_mod.query_file_path,
        skill_docs_mod.find_installed_skill,
        plan_persistence_mod.load_plan,
        plan_persistence_mod.save_plan,
        planning_dimension_rows_mod.scorecard_dimension_rows,
        go_commands_mod.get_detect_commands,
        go_deps_mod.build_dep_graph,
        go_move_mod.find_replacements,
        go_move_mod.find_self_replacements,
        go_review_mod.module_patterns,
        go_review_mod.api_surface,
    )
    assert isinstance(go_phases_mod.GO_COMPLEXITY_SIGNALS, list)  # nosec B101
    assert callable(go_phases_mod._phase_structural)  # nosec B101
    assert isinstance(planning_pkg.__all__, list)  # nosec B101
    assert isinstance(dimension_policy_mod._SCORECARD_DIMENSIONS_BY_LANG, dict)  # nosec B101


def test_fixer_import_rewrite_smoke() -> None:
    _assert_all_callables(
        ts_import_rewrite_mod.process_unused_import_lines,
        ts_import_rewrite_mod.remove_symbols_from_import_stmt,
        ts_import_rewrite_mod._collect_import_statement,
    )


def test_roslyn_stub_module_loads() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / ".github" / "scripts" / "roslyn_stub.py"
    spec = importlib.util.spec_from_file_location("roslyn_stub_for_test", script_path)
    assert spec is not None  # nosec B101
    assert spec.loader is not None  # nosec B101
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)  # nosec B101
