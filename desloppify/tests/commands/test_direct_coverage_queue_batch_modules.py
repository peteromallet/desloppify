"""Direct coverage smoke tests for split plan/review helper modules."""

from __future__ import annotations

import desloppify.app.commands.helpers.guardrails as guardrails_mod
import desloppify.app.commands.backlog.cmd as backlog_mod
import desloppify.app.commands.plan.triage.display.progress as plan_progress_render_mod
import desloppify.app.commands.plan.triage.stages.commands as triage_flow_mod
import desloppify.app.commands.plan.triage.command as triage_handlers_mod
import desloppify.app.commands.review.batch.merge as batch_merge_mod
import desloppify.app.commands.review.batch.scope as batches_scope_mod
import desloppify.app.commands.review.batches_runtime as batches_runtime_mod
import desloppify.app.commands.review.coordinator as coordinator_mod
import desloppify.app.commands.review.packet.build as packet_build_mod
import desloppify.app.commands.review.runner_failures as runner_failures_mod
import desloppify.app.commands.review.runner_opencode as runner_opencode_mod
import desloppify.app.commands.review.runner_packets as runner_packets_mod
import desloppify.app.commands.review.runner_parallel as runner_parallel_mod
import desloppify.app.commands.runner.codex_batch as runner_process_mod
import desloppify.app.commands.review.runtime_paths as runtime_paths_mod
import desloppify.app.commands.review.state_payloads as state_payloads_mod
import desloppify.app.commands.scan.plan_nudge as plan_nudge_mod
import desloppify.engine._plan.persistence as plan_persistence_mod
import desloppify.engine.planning.queue_policy as queue_policy_mod
import desloppify.intelligence.review.issue_merge as issue_merge_mod


def test_direct_coverage_split_queue_batch_modules_smoke():
    assert callable(triage_flow_mod.cmd_stage_organize)
    assert callable(triage_flow_mod.cmd_stage_reflect)
    assert callable(triage_flow_mod.cmd_stage_observe)
    assert callable(triage_handlers_mod.cmd_plan_triage)
    assert callable(backlog_mod.cmd_backlog)
    assert callable(queue_policy_mod.build_open_plan_queue)
    assert callable(queue_policy_mod.build_backlog_queue)
    assert callable(queue_policy_mod.build_execution_queue)
    assert callable(guardrails_mod.print_triage_guardrail_info)
    assert callable(plan_progress_render_mod._print_progress)
    assert callable(batch_merge_mod.merge_batch_results)
    assert callable(batches_runtime_mod.build_batch_tasks)
    assert callable(batches_scope_mod.validate_runner)
    assert callable(coordinator_mod.build_review_session_baseline)
    assert callable(coordinator_mod.evaluate_session_baseline_drift)
    assert callable(packet_build_mod.build_holistic_packet)
    assert callable(packet_build_mod.build_review_packet_payload)
    assert callable(packet_build_mod.write_review_packet_snapshot)
    assert callable(runner_failures_mod.print_failures)
    assert callable(runner_opencode_mod.run_opencode_batch)
    assert callable(runner_opencode_mod.opencode_batch_command)
    assert callable(runner_packets_mod.prepare_run_artifacts)
    assert callable(runner_parallel_mod.execute_batches)
    assert callable(runner_process_mod.run_codex_batch)
    assert callable(runtime_paths_mod.runtime_project_root)
    assert callable(state_payloads_mod.subjective_assessment_store)
    assert callable(plan_nudge_mod.print_plan_workflow_nudge)
    assert callable(plan_persistence_mod.load_plan)
    assert callable(issue_merge_mod.merge_list_fields)
