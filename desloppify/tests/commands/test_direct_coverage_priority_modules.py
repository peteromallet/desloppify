"""Direct coverage smoke tests for high-priority untested modules."""

from __future__ import annotations

import inspect
from pathlib import Path

import desloppify.app.commands.helpers.display as display_mod
import desloppify.app.commands.next.render_support as next_render_support_mod
import desloppify.app.commands.helpers.persist as helpers_persist_mod
import desloppify.app.commands.resolve.queue_guard as resolve_queue_guard_mod
import desloppify.app.commands.resolve.render_support as resolve_render_support_mod
import desloppify.app.commands.suppress as suppress_cmd_mod
import desloppify.app.commands.review.importing.output as review_import_output_mod
import desloppify.app.commands.review.importing.parse as review_import_parse_mod
import desloppify.app.commands.review.importing.policy as review_import_policy_mod
import desloppify.app.commands.scan.reporting.agent_context as scan_agent_context_mod
import desloppify.app.commands.scan.reporting.integrity_report as scan_integrity_report_mod
import desloppify.app.commands.show.concerns_view as show_concerns_view_mod
import desloppify.app.commands.show.dimension_views as show_dimension_views_mod
import desloppify.app.commands.status.render_dimensions as status_render_dimensions_mod
import desloppify.app.commands.status.render_io as status_render_io_mod
import desloppify.app.commands.status.render_structural as status_render_structural_mod
import desloppify.base.compatibility as compatibility_mod
import desloppify.base.search.grep as grep_mod
import desloppify.base.output.terminal as output_mod
import desloppify.app.skill_docs as skill_docs_mod
import desloppify.base.subjective_dimensions as subjective_dimensions_mod
import desloppify.base.discovery.paths as paths_mod
import desloppify.engine._plan.schema_migrations as schema_migrations_mod
import desloppify.engine._scoring.results.health as scoring_health_mod
import desloppify.engine._scoring.results.impact as scoring_impact_mod
import desloppify.engine._state.schema_scores as schema_scores_mod
import desloppify.engine._work_queue.plan_order as work_queue_plan_order_mod
import desloppify.engine._work_queue.synthetic as work_queue_synthetic_mod
import desloppify.engine.planning as planning_pkg
import desloppify.engine.planning.dimension_rows as planning_dimension_rows_mod
import desloppify.engine.planning.render_sections as planning_render_sections_mod
import desloppify.engine.planning.scorecard_policy as dimension_policy_mod
import desloppify.engine.hook_registry as hook_registry_mod
import desloppify.intelligence.narrative.signals as narrative_signals_mod
import desloppify.intelligence.review.context_holistic.selection_contexts as selection_contexts_mod
import desloppify.intelligence.review.selection_cache as review_selection_cache_mod
import desloppify.languages._framework.scoped_store as scoped_store_mod
import desloppify.languages.csharp.detectors.deps_support as csharp_deps_support_mod
import desloppify.languages.python.detectors.deps_dynamic as py_deps_dynamic_mod
import desloppify.languages.python.detectors.deps_resolution as py_deps_resolution_mod
import desloppify.languages.python.detectors.smells_runtime as py_smells_runtime_mod
import desloppify.languages.python.phases_runtime as py_phases_runtime_mod
import desloppify.languages.typescript.detectors.deps_resolve as ts_deps_resolve_mod
import desloppify.languages.typescript.fixers.fixer_io as ts_fixer_io_mod
import desloppify.languages.typescript.fixers.import_rewrite as ts_import_rewrite_mod
import desloppify.languages.typescript.fixers.syntax_scan as ts_syntax_scan_mod
import desloppify.languages.typescript.syntax.scanner as ts_scanner_mod


def test_direct_coverage_priority_modules_smoke():
    assert callable(review_import_output_mod.print_import_load_errors)
    assert callable(review_import_parse_mod.load_import_issues_data)
    assert callable(review_import_policy_mod.apply_assessment_import_policy)

    assert callable(scan_agent_context_mod.print_llm_summary)
    assert callable(scan_integrity_report_mod.show_score_integrity)
    assert callable(next_render_support_mod.render_queue_header)
    assert callable(suppress_cmd_mod.cmd_suppress)
    assert callable(helpers_persist_mod.save_state_or_exit)
    assert callable(resolve_queue_guard_mod._check_queue_order_guard)
    assert callable(resolve_render_support_mod.print_post_resolve_guidance)
    assert callable(show_concerns_view_mod._show_concerns)
    assert callable(show_dimension_views_mod._render_subjective_views_guide)
    assert callable(status_render_dimensions_mod.render_subjective_dimensions)
    assert callable(status_render_io_mod.write_status_query)
    assert callable(status_render_structural_mod.render_area_workflow)
    assert callable(display_mod.short_issue_id)
    assert callable(dimension_policy_mod._compose_scorecard_dimensions)

    assert callable(compatibility_mod.is_private_module)
    assert callable(grep_mod.grep_files_containing)
    assert callable(output_mod.display_entries)
    assert callable(skill_docs_mod.check_skill_version)
    assert callable(subjective_dimensions_mod.default_dimension_keys)
    assert callable(paths_mod.read_code_snippet)

    assert callable(hook_registry_mod.register_lang_hooks)
    assert callable(schema_migrations_mod.migrate_v5_to_v6)
    assert callable(scoring_health_mod.compute_health_breakdown)
    assert callable(scoring_impact_mod.compute_score_impact)
    assert callable(schema_scores_mod.get_verified_strict_score)
    assert callable(work_queue_plan_order_mod.collapse_clusters)
    assert callable(planning_pkg.get_next_item)
    assert callable(planning_dimension_rows_mod.scorecard_dimension_rows)
    assert callable(planning_render_sections_mod.render_plan_item)
    assert callable(narrative_signals_mod.compute_risk_flags)
    assert callable(selection_contexts_mod.architecture_context)
    assert callable(review_selection_cache_mod.get_file_issues)
    assert callable(scoped_store_mod.resolve_effective_scope)
    assert callable(csharp_deps_support_mod.map_file_to_project)
    assert callable(py_deps_dynamic_mod.find_python_dynamic_imports)
    assert callable(py_deps_resolution_mod.resolve_python_import)
    assert callable(py_smells_runtime_mod._detect_empty_except)
    assert callable(py_phases_runtime_mod.run_phase_structural)
    assert callable(ts_deps_resolve_mod.resolve_module)

    assert callable(ts_scanner_mod.scan_code)
    assert callable(ts_fixer_io_mod.apply_fixer)
    assert callable(ts_import_rewrite_mod.process_unused_import_lines)
    assert callable(ts_syntax_scan_mod.find_balanced_end)


def test_direct_coverage_priority_modules_behavior():
    assert display_mod.short_issue_id("foo::bar::baz").startswith("foo")
    assert ts_syntax_scan_mod.collapse_blank_lines(["a", "", "", "b"]) == ["a", "", "b"]
    rewritten, removed = ts_import_rewrite_mod.remove_symbols_from_import_stmt(
        "import { A, B } from 'pkg';\n",
        {"A"},
    )
    assert rewritten is not None
    assert "B" in rewritten
    assert removed == {"A"}


def test_review_import_parse_normalizes_legacy_findings_alias():
    payload, errors = review_import_parse_mod._normalize_import_root_payload(
        {"findings": []}
    )
    assert errors == []
    assert payload == {"issues": []}


def test_engine_modules_avoid_app_layer_import_paths():
    synthetic_src = inspect.getsource(work_queue_synthetic_mod.build_triage_stage_items)
    assert "desloppify.app.commands.plan.triage_playbook" not in synthetic_src

    dimension_rows_src = inspect.getsource(planning_dimension_rows_mod)
    assert "desloppify.app.output.scorecard_parts.dimensions" not in dimension_rows_src


def test_app_plan_modules_avoid_private_engine_plan_imports():
    package_root = Path(__file__).resolve().parents[2]
    rel_paths = [
        "app/commands/plan/cmd.py",
        "app/commands/plan/cluster_handlers.py",
        "app/commands/plan/override_handlers.py",
        "app/commands/plan/triage/helpers.py",
        "app/commands/plan/triage/runner/stage_validation.py",
        "app/commands/plan/triage/runner/stage_prompts.py",
        "app/commands/plan/triage_playbook.py",
        "app/commands/resolve/cmd.py",
        "app/commands/review/importing/cmd.py",
    ]
    for rel_path in rel_paths:
        text = (package_root / rel_path).read_text(encoding="utf-8")
        assert "desloppify.engine._plan" not in text
