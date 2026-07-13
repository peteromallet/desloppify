"""Direct tests for parser section helper modules."""

from __future__ import annotations

import argparse

import pytest

from desloppify.app.cli_support.parser_groups_admin_review_options_batch import (
    _add_batch_execution_options,
)
from desloppify.app.cli_support.parser_groups_admin_review_options_core import (
    _add_core_options,
)
from desloppify.app.cli_support.parser_groups_admin_review_options_external import (
    _add_external_review_options,
)
from desloppify.app.cli_support.parser_groups_admin_review_options_trust_post import (
    _add_trust_options,
)
from desloppify.app.cli_support.parser_groups_plan_impl_sections_annotations import (
    _add_annotation_subparsers,
    _add_resolve_subparser,
    _add_skip_subparsers,
)
from desloppify.app.cli_support.parser_groups_plan_impl_sections_cluster import (
    _add_cluster_subparser,
)
from desloppify.app.cli_support.parser_groups_plan_impl_sections_queue_reorder import (
    _add_queue_subparser,
    _add_reorder_subparser,
)
from desloppify.app.cli_support.parser_groups_plan_impl_sections_triage_commit_scan import (
    _add_commit_log_subparser,
    _add_scan_gate_subparser,
    _add_triage_subparser,
)


def _build_plan_parser() -> tuple[argparse.ArgumentParser, argparse._SubParsersAction]:
    parser = argparse.ArgumentParser(prog="desloppify")
    root_sub = parser.add_subparsers(dest="command")
    p_plan = root_sub.add_parser("plan")
    plan_sub = p_plan.add_subparsers(dest="plan_action")
    return parser, plan_sub


def test_review_option_groups_register_expected_flags() -> None:
    parser = argparse.ArgumentParser(prog="desloppify review")
    _add_core_options(parser)
    _add_external_review_options(parser)
    _add_batch_execution_options(parser)
    _add_trust_options(parser)

    defaults = parser.parse_args([])
    assert defaults.retrospective_max_issues == 30
    assert defaults.retrospective_max_batch_items == 20
    assert defaults.external_runner == "claude"
    assert defaults.session_ttl_hours == 24
    assert defaults.max_parallel_batches == 3
    assert defaults.batch_timeout_seconds == 1200
    assert defaults.batch_retry_backoff_seconds == 2.0

    args = parser.parse_args(
        [
            "--prepare",
            "--import",
            "review.json",
            "--dimensions",
            "naming_quality,error_consistency",
            "--retrospective",
            "--retrospective-max-issues",
            "5",
            "--retrospective-max-batch-items",
            "7",
            "--external-start",
            "--external-submit",
            "--session-id",
            "session-1",
            "--session-ttl-hours",
            "48",
            "--run-batches",
            "--parallel",
            "--max-parallel-batches",
            "4",
            "--batch-timeout-seconds",
            "30",
            "--batch-max-retries",
            "2",
            "--batch-retry-backoff-seconds",
            "3.5",
            "--batch-heartbeat-seconds",
            "2.5",
            "--batch-stall-warning-seconds",
            "120",
            "--batch-stall-kill-seconds",
            "180",
            "--only-batches",
            "1,3",
            "--packet",
            "packet.json",
            "--import-run",
            "run-dir",
            "--scan-after-import",
            "--manual-override",
            "--attested-external",
            "--attest",
            "without awareness and unbiased reviewer.",
        ]
    )
    assert args.prepare is True
    assert args.import_file == "review.json"
    assert args.dimensions == "naming_quality,error_consistency"
    assert args.retrospective is True
    assert args.retrospective_max_issues == 5
    assert args.retrospective_max_batch_items == 7
    assert args.external_start is True
    assert args.external_submit is True
    assert args.session_id == "session-1"
    assert args.session_ttl_hours == 48
    assert args.run_batches is True
    assert args.parallel is True
    assert args.max_parallel_batches == 4
    assert args.batch_timeout_seconds == 30
    assert args.batch_max_retries == 2
    assert args.batch_retry_backoff_seconds == 3.5
    assert args.batch_heartbeat_seconds == 2.5
    assert args.batch_stall_warning_seconds == 120
    assert args.batch_stall_kill_seconds == 180
    assert args.only_batches == "1,3"
    assert args.packet == "packet.json"
    assert args.import_run_dir == "run-dir"
    assert args.scan_after_import is True
    assert args.manual_override is True
    assert args.attested_external is True
    assert args.attest == "without awareness and unbiased reviewer."


def test_plan_queue_and_reorder_subparsers_parse_expected_shapes() -> None:
    parser, plan_sub = _build_plan_parser()
    _add_queue_subparser(plan_sub)
    _add_reorder_subparser(plan_sub)

    queue_args = parser.parse_args(
        [
            "plan",
            "queue",
            "--top",
            "0",
            "--cluster",
            "auto/test_coverage",
            "--include-skipped",
            "--sort",
            "recent",
        ]
    )
    assert queue_args.plan_action == "queue"
    assert queue_args.top == 0
    assert queue_args.cluster == "auto/test_coverage"
    assert queue_args.include_skipped is True
    assert queue_args.sort == "recent"

    reorder_args = parser.parse_args(
        [
            "plan",
            "reorder",
            "smells",
            "unused::*",
            "before",
            "--target",
            "security",
        ]
    )
    assert reorder_args.plan_action == "reorder"
    assert reorder_args.patterns == ["smells", "unused::*"]
    assert reorder_args.position == "before"
    assert reorder_args.target == "security"


def test_plan_annotation_skip_and_resolve_parsers() -> None:
    parser, plan_sub = _build_plan_parser()
    _add_annotation_subparsers(plan_sub)
    _add_skip_subparsers(plan_sub)
    _add_resolve_subparser(plan_sub)

    describe_args = parser.parse_args(
        ["plan", "describe", "unused::*", "security", "prioritize now"]
    )
    assert describe_args.plan_action == "describe"
    assert describe_args.patterns == ["unused::*", "security"]
    assert describe_args.text == "prioritize now"

    note_args = parser.parse_args(["plan", "note", "unused::*", "temporary defer"])
    assert note_args.plan_action == "note"
    assert note_args.patterns == ["unused::*"]
    assert note_args.text == "temporary defer"

    skip_args = parser.parse_args(
        [
            "plan",
            "skip",
            "review::*",
            "--reason",
            "batch later",
            "--review-after",
            "2",
            "--confirm",
        ]
    )
    assert skip_args.plan_action == "skip"
    assert skip_args.reason == "batch later"
    assert skip_args.review_after == 2
    assert skip_args.confirm is True

    unskip_args = parser.parse_args(["plan", "unskip", "review::*", "--force"])
    assert unskip_args.plan_action == "unskip"
    assert unskip_args.force is True

    resolve_args = parser.parse_args(
        [
            "plan",
            "resolve",
            "unused::*",
            "--note",
            "added direct tests",
            "--attest",
            "I have actually validated this and I am not gaming the score.",
            "--force-resolve",
        ]
    )
    assert resolve_args.plan_action == "resolve"
    assert resolve_args.patterns == ["unused::*"]
    assert resolve_args.force_resolve is True

    reopen_args = parser.parse_args(["plan", "reopen", "unused::*"])
    assert reopen_args.plan_action == "reopen"
    assert reopen_args.patterns == ["unused::*"]


def test_plan_cluster_triage_commit_and_scan_gate_subparsers() -> None:
    parser, plan_sub = _build_plan_parser()
    _add_cluster_subparser(plan_sub)
    _add_triage_subparser(plan_sub)
    _add_commit_log_subparser(plan_sub)
    _add_scan_gate_subparser(plan_sub)

    cluster_update = parser.parse_args(
        [
            "plan",
            "cluster",
            "update",
            "auto/test_coverage",
            "--description",
            "coverage cluster",
            "--add-step",
            "Add direct tests",
            "--detail",
            "focus transitive_only modules first",
            "--effort",
            "small",
            "--depends-on",
            "base",
            "parser",
            "--issue-refs",
            "test_coverage::a",
            "test_coverage::b",
        ]
    )
    assert cluster_update.plan_action == "cluster"
    assert cluster_update.cluster_action == "update"
    assert cluster_update.cluster_name == "auto/test_coverage"
    assert cluster_update.add_step == "Add direct tests"
    assert cluster_update.effort == "small"
    assert cluster_update.depends_on == ["base", "parser"]
    assert cluster_update.issue_refs == ["test_coverage::a", "test_coverage::b"]

    clear_dependencies = parser.parse_args(
        [
            "plan",
            "cluster",
            "update",
            "auto/test_coverage",
            "--clear-depends-on",
        ]
    )
    assert clear_dependencies.clear_depends_on is True
    assert clear_dependencies.depends_on is None

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "plan",
                "cluster",
                "update",
                "auto/test_coverage",
                "--depends-on",
                "base",
                "--clear-depends-on",
            ]
        )

    triage_args = parser.parse_args(
        [
            "plan",
            "triage",
            "--confirm",
            "reflect",
            "--attestation",
            "I verified this stage summary with direct queue evidence and no shortcuts.",
            "--run-stages",
            "--runner",
            "claude",
            "--only-stages",
            "observe,reflect",
            "--stage-timeout-seconds",
            "90",
        ]
    )
    assert triage_args.plan_action == "triage"
    assert triage_args.confirm == "reflect"
    assert triage_args.attestation.startswith("I verified")
    assert triage_args.run_stages is True
    assert triage_args.runner == "claude"
    assert triage_args.only_stages == "observe,reflect"
    assert triage_args.stage_timeout_seconds == 90

    commit_record = parser.parse_args(
        [
            "plan",
            "commit-log",
            "record",
            "--sha",
            "abc123",
            "--branch",
            "wip/triage-runner",
            "--note",
            "batch 1",
            "--only",
            "test_coverage::a",
            "test_coverage::b",
        ]
    )
    assert commit_record.plan_action == "commit-log"
    assert commit_record.commit_log_action == "record"
    assert commit_record.sha == "abc123"
    assert commit_record.branch == "wip/triage-runner"
    assert commit_record.only == ["test_coverage::a", "test_coverage::b"]

    commit_history = parser.parse_args(["plan", "commit-log", "history", "--top", "3"])
    assert commit_history.commit_log_action == "history"
    assert commit_history.top == 3

    commit_pr = parser.parse_args(["plan", "commit-log", "pr"])
    assert commit_pr.commit_log_action == "pr"

    scan_gate = parser.parse_args(
        [
            "plan",
            "scan-gate",
            "--skip",
            "--note",
            "Skipping scan gate for this cycle because objective queue execution is in progress.",
        ]
    )
    assert scan_gate.plan_action == "scan-gate"
    assert scan_gate.skip is True
    assert scan_gate.note.startswith("Skipping scan gate")
