"""Triage/commit-log/scan-gate parser section builders for plan command."""

from __future__ import annotations

import argparse


def _add_triage_subparser(plan_sub) -> None:
    p_triage = plan_sub.add_parser(
        "triage",
        help="Staged triage workflow for review issues",
        epilog="""\
examples:
  desloppify plan triage
  desloppify plan triage --run-stages --runner codex
  desloppify plan triage --run-stages --runner claude
  desloppify plan triage --run-stages --runner codex --only-stages organize
  desloppify plan triage --stage strategize --report '{"score_trend":"stable","debt_trend":"stable"}'   # manual fallback
  desloppify plan triage --confirm-existing --note "..." --strategy "same" --confirmed "I reviewed the new issues and the existing plan still holds."\
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_triage.add_argument(
        "--stage",
        type=str,
        choices=["strategize", "observe", "reflect", "organize", "enrich", "sense-check"],
        default=None,
        help="Stage to record",
    )
    p_triage.add_argument(
        "--report", type=str, default=None,
        help="Stage report text",
    )
    p_triage.add_argument(
        "--report-file", type=str, default=None,
        dest="report_file",
        help="Read stage report text from a file (--report takes precedence)",
    )
    p_triage.add_argument(
        "--complete", action="store_true", default=False,
        help="Mark triage complete",
    )
    p_triage.add_argument(
        "--strategy", type=str, default=None,
        help="Strategy summary (for --complete)",
    )
    p_triage.add_argument(
        "--confirm-existing", action="store_true", default=False,
        help="Fast-track confirmation of existing plan",
    )
    p_triage.add_argument(
        "--note", type=str, default=None,
        help="Note for --confirm-existing",
    )
    p_triage.add_argument(
        "--start", action="store_true", default=False,
        help="Manually start triage (inject triage stages, clear prior stages)",
    )
    p_triage.add_argument(
        "--confirm",
        type=str,
        choices=["strategize", "observe", "reflect", "organize", "enrich", "sense-check"],
        default=None,
        help="Confirm a completed stage (shows summary, requires --attestation)",
    )
    p_triage.add_argument(
        "--attestation",
        type=str,
        default=None,
        help="Attestation text confirming stage review (min 30 chars, used with --confirm)",
    )
    p_triage.add_argument(
        "--confirmed",
        type=str,
        default=None,
        help="Plan validation text for --confirm-existing (confirms plan review)",
    )
    p_triage.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Preview mode",
    )

    # Subagent runner
    p_triage.add_argument(
        "--run-stages", action="store_true", default=False,
        help="Preferred: run triage stages via the codex/claude staged runner",
    )
    p_triage.add_argument(
        "--runner", choices=["codex", "claude"], default="codex",
        help="Runner for --run-stages (default: codex)",
    )
    p_triage.add_argument(
        "--stage-timeout-seconds", type=int, default=1800,
        help="Per-stage timeout in seconds (default: 1800, codex only)",
    )
    p_triage.add_argument(
        "--only-stages", type=str, default=None,
        help="Comma-separated list of stages to run (default: all)",
    )

    # Stage prompt (on-demand, for orchestrator flow)
    p_triage.add_argument(
        "--stage-prompt",
        type=str,
        choices=["strategize", "observe", "reflect", "organize", "enrich", "sense-check"],
        default=None,
        help="Print the current prompt for a stage (built from live plan data)",
    )


def _add_commit_log_subparser(plan_sub) -> None:
    p_commit_log = plan_sub.add_parser(
        "commit-log",
        help="Track commits and resolved issues for PR updates",
        epilog="""\
examples:
  desloppify plan commit-log                     # show status
  desloppify plan commit-log record              # record HEAD commit
  desloppify plan commit-log record --note "..."  # with rationale
  desloppify plan commit-log record --only "smells::*"
  desloppify plan commit-log history             # show commit records
  desloppify plan commit-log pr                  # print PR body markdown""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commit_log_sub = p_commit_log.add_subparsers(dest="commit_log_action")

    p_cl_record = commit_log_sub.add_parser("record", help="Record a commit with resolved issues")
    p_cl_record.add_argument("--sha", type=str, default=None, help="Commit SHA (default: auto-detect HEAD)")
    p_cl_record.add_argument("--branch", type=str, default=None, help="Branch name (default: auto-detect)")
    p_cl_record.add_argument("--note", type=str, default=None, help="Commit rationale/description")
    p_cl_record.add_argument("--only", nargs="+", metavar="PATTERN", default=None, help="Record only matching issues (glob patterns)")

    p_cl_history = commit_log_sub.add_parser("history", help="Show commit records")
    p_cl_history.add_argument("--top", type=int, default=10, help="Number of records to show (default: 10)")

    commit_log_sub.add_parser("pr", help="Print PR body markdown (dry run)")


def _add_scan_gate_subparser(plan_sub) -> None:
    p_sg = plan_sub.add_parser(
        "scan-gate",
        help="Check or skip the scan requirement for workflow items",
        epilog="""\
examples:
  desloppify plan scan-gate                        # check scan gate status
  desloppify plan scan-gate --skip --note "..."    # mark scan requirement as satisfied""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_sg.add_argument(
        "--skip", action="store_true", default=False,
        help="Mark the scan requirement as satisfied without running a scan",
    )
    p_sg.add_argument(
        "--note", type=str, default=None,
        help="Explanation for skipping (required with --skip, min 50 chars)",
    )


def _add_policy_subparser(plan_sub) -> None:
    p_policy = plan_sub.add_parser(
        "policy",
        help="Manage project policy rules (enforced during triage and review)",
        epilog="""\
examples:
  desloppify plan policy                            # list rules
  desloppify plan policy add "No re-export facades" # add a rule
  desloppify plan policy remove 2                   # remove rule #2""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    policy_sub = p_policy.add_subparsers(dest="policy_action")
    p_add = policy_sub.add_parser("add", help="Add a policy rule")
    p_add.add_argument("rule_text", type=str, help="Rule text")
    p_remove = policy_sub.add_parser("remove", help="Remove a policy rule by number")
    p_remove.add_argument("rule_index", type=int, help="Rule number to remove")


def _add_repair_state_subparser(plan_sub) -> None:
    plan_sub.add_parser(
        "repair-state",
        help="Rebuild state.json from surviving plan metadata",
        epilog="""\
examples:
  desloppify plan repair-state
  desloppify plan repair-state --state .desloppify/state-typescript.json""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


__all__ = [
    "_add_commit_log_subparser",
    "_add_policy_subparser",
    "_add_repair_state_subparser",
    "_add_scan_gate_subparser",
    "_add_triage_subparser",
]
