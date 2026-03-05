"""CLI parser group builder for plan command family."""

from __future__ import annotations

import argparse


def _add_queue_subparser(plan_sub) -> None:
    p_queue = plan_sub.add_parser("queue", help="Compact table of upcoming queue items")
    p_queue.add_argument("--top", type=int, default=30, help="Max items (default: 30, 0=all)")
    p_queue.add_argument("--cluster", type=str, default=None, metavar="NAME",
                         help="Filter to a specific cluster")
    p_queue.add_argument("--include-skipped", action="store_true",
                         help="Include skipped items at end")
    p_queue.add_argument("--sort", choices=["priority", "recent"], default="priority",
                         help="Sort order (default: priority)")


def _add_reorder_subparser(plan_sub) -> None:
    p_move = plan_sub.add_parser(
        "reorder",
        help="Reposition issues in the queue",
        epilog="""\
patterns accept issue IDs, detector names, file paths, globs, or cluster names.
cluster names expand to all member IDs automatically.

examples:
  desloppify plan reorder security top                         # all issues from detector
  desloppify plan reorder "unused::src/foo.ts::*" top          # glob pattern
  desloppify plan reorder smells bottom                        # deprioritize
  desloppify plan reorder my-cluster top                       # cluster members
  desloppify plan reorder my-cluster unused top                # mix clusters + issues
  desloppify plan reorder unused before -t security            # before a issue/cluster
  desloppify plan reorder smells after -t my-cluster           # after a cluster
  desloppify plan reorder security up -t 3                     # shift up 3 positions""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_move.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Issue ID(s), detector, file path, glob, or cluster name",
    )
    p_move.add_argument(
        "position", choices=["top", "bottom", "before", "after", "up", "down"],
        help="Where to move",
    )
    p_move.add_argument(
        "-t", "--target", default=None,
        help="Required for before/after (issue ID or cluster name) and up/down (integer offset)",
    )


def _add_annotation_subparsers(plan_sub) -> None:
    # plan describe <patterns> "<text>"
    p_describe = plan_sub.add_parser("describe", help="Set augmented description")
    p_describe.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Issue ID(s), detector, file path, glob, or cluster name",
    )
    p_describe.add_argument("text", type=str, help="Description text")

    # plan note <patterns> "<text>"
    p_note = plan_sub.add_parser("note", help="Set note on issues")
    p_note.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Issue ID(s), detector, file path, glob, or cluster name",
    )
    p_note.add_argument("text", type=str, help="Note text")


def _add_skip_subparsers(plan_sub) -> None:
    # plan skip <patterns> [--reason] [--review-after N] [--permanent] [--false-positive] [--note] [--attest]
    p_skip = plan_sub.add_parser(
        "skip",
        help="Skip issues: temporary (default), --permanent (wontfix), or --false-positive",
    )
    p_skip.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Issue ID(s), detector, file path, glob, or cluster name",
    )
    p_skip.add_argument("--reason", type=str, default=None, help="Why this is being skipped")
    p_skip.add_argument(
        "--review-after", type=int, default=None, metavar="N",
        help="Re-surface after N scans (temporary only)",
    )
    p_skip.add_argument(
        "--permanent", action="store_true",
        help="Mark as wontfix (score-affecting, requires --note and --attest)",
    )
    p_skip.add_argument(
        "--false-positive", action="store_true",
        help="Mark as false positive (requires --attest)",
    )
    p_skip.add_argument("--note", type=str, default=None, help="Explanation (required for --permanent)")
    p_skip.add_argument(
        "--attest", type=str, default=None,
        help="Attestation (required for --permanent and --false-positive)",
    )

    # plan unskip <patterns>
    p_unskip = plan_sub.add_parser(
        "unskip", help="Bring skipped issues back to queue (reopens permanent/fp in state)"
    )
    p_unskip.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Issue ID(s), detector, file path, glob, or cluster name",
    )


def _add_resolve_subparser(plan_sub) -> None:
    # plan reopen <patterns>
    p_reopen = plan_sub.add_parser(
        "reopen", help="Reopen resolved issues and move back to queue"
    )
    p_reopen.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Issue ID(s), detector, file path, glob, or cluster name",
    )

    # plan resolve <patterns> --attest [--note]
    p_resolve = plan_sub.add_parser(
        "resolve",
        help="Mark issues as fixed (shows score movement + next step)",
        epilog="""\
examples:
  desloppify plan resolve "unused::src/foo.tsx::React" \\
    --attest "I have actually removed the import and I am not gaming the score."
  desloppify plan resolve security --note "patched XSS" \\
    --attest "I have actually ..."  """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_resolve.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Issue ID(s), detector, file path, glob, or cluster name",
    )
    p_resolve.add_argument(
        "--note", type=str, default=None, help="Explanation of the fix"
    )
    p_resolve.add_argument(
        "--attest",
        type=str,
        default=None,
        help=(
            "Required anti-gaming attestation. Must include BOTH keywords "
            "'I have actually' and 'not gaming'."
        ),
    )
    p_resolve.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Auto-generate attestation from --note (requires --note)",
    )
    p_resolve.add_argument(
        "--force-resolve",
        action="store_true",
        default=False,
        dest="force_resolve",
        help="Bypass triage guardrail when new issues are pending triage",
    )


def _add_cluster_subparser(plan_sub) -> None:
    # plan focus <cluster> | --clear
    p_focus = plan_sub.add_parser("focus", help="Set or clear active cluster focus")
    p_focus.add_argument("cluster_name", nargs="?", default=None, help="Cluster name")
    p_focus.add_argument("--clear", action="store_true", help="Clear focus")

    # plan cluster ...
    p_cluster = plan_sub.add_parser(
        "cluster",
        help="Manage issue clusters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cluster_sub = p_cluster.add_subparsers(dest="cluster_action")

    # plan cluster create <name> [--description "..."] [--action "..."]
    p_cc = cluster_sub.add_parser("create", help="Create a cluster")
    p_cc.add_argument("cluster_name", type=str, help="Cluster name (slug)")
    p_cc.add_argument("--description", type=str, default=None, help="Cluster description")
    p_cc.add_argument("--action", type=str, default=None, help="Primary action/command for this cluster")

    # plan cluster add <cluster> <patterns...>
    p_ca = cluster_sub.add_parser("add", help="Add issues to a cluster")
    p_ca.add_argument("cluster_name", type=str, help="Cluster name")
    p_ca.add_argument("patterns", nargs="+", metavar="PATTERN", help="Issue ID(s), detector, file path, glob, or cluster name")
    p_ca.add_argument("--dry-run", action="store_true", default=False, help="Preview without saving")

    # plan cluster remove <cluster> <patterns...>
    p_cr = cluster_sub.add_parser("remove", help="Remove issues from a cluster")
    p_cr.add_argument("cluster_name", type=str, help="Cluster name")
    p_cr.add_argument("patterns", nargs="+", metavar="PATTERN", help="Issue ID(s), detector, file path, glob, or cluster name")
    p_cr.add_argument("--dry-run", action="store_true", default=False, help="Preview without saving")

    # plan cluster delete <name>
    p_cd = cluster_sub.add_parser("delete", help="Delete a cluster")
    p_cd.add_argument("cluster_name", type=str, help="Cluster name")

    # plan cluster reorder <cluster[,cluster...]> <position> [target]
    p_cm = cluster_sub.add_parser("reorder", help="Reorder cluster(s) as a block")
    p_cm.add_argument("cluster_names", type=str, help="Cluster name(s), comma-separated for multiple")
    p_cm.add_argument(
        "position", choices=["top", "bottom", "before", "after", "up", "down"],
        help="Where to move",
    )
    p_cm.add_argument("target", nargs="?", default=None, help="Target issue/cluster (before/after) or integer offset (up/down)")
    p_cm.add_argument(
        "--item", dest="item_pattern", default=None, metavar="PATTERN",
        help="Move a specific item within the cluster (omit to move whole cluster as a block)",
    )

    # plan cluster show <name>
    p_cs = cluster_sub.add_parser("show", help="Show cluster details and members")
    p_cs.add_argument("cluster_name", type=str, help="Cluster name")

    # plan cluster list
    p_cl = cluster_sub.add_parser("list", help="List all clusters")
    p_cl.add_argument("--verbose", "-v", action="store_true", default=False,
                      help="Show queue position, steps count, and description as a table")

    # plan cluster merge <source> <target>
    p_cmerge = cluster_sub.add_parser("merge", help="Merge source cluster into target (moves issues, deletes source)")
    p_cmerge.add_argument("source", type=str, help="Source cluster name (will be deleted)")
    p_cmerge.add_argument("target", type=str, help="Target cluster name (receives issues)")

    # plan cluster update <name> [--description "..."] [--steps "..." ...]
    p_cu = cluster_sub.add_parser("update", help="Update cluster description and/or action steps")
    p_cu.add_argument("cluster_name", type=str, help="Cluster name")
    p_cu.add_argument("--description", type=str, default=None, help="Cluster description")
    p_cu.add_argument("--steps", nargs="+", metavar="STEP", default=None, help="Action steps list")


def _add_triage_subparser(plan_sub) -> None:
    p_triage = plan_sub.add_parser(
        "triage",
        help="Staged triage workflow for review issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_triage.add_argument(
        "--stage",
        type=str,
        choices=["observe", "reflect", "organize"],
        default=None,
        help="Stage to record",
    )
    p_triage.add_argument(
        "--report", type=str, default=None,
        help="Stage report text",
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
        help="Manually start triage (inject triage::pending, clear prior stages)",
    )
    p_triage.add_argument(
        "--confirm",
        type=str,
        choices=["observe", "reflect", "organize"],
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


def add_plan_parser(sub) -> None:
    p_plan = sub.add_parser(
        "plan",
        help="Living plan: generate, show, resolve, skip, cluster, triage",
        description="""\
Manage the living plan — a persistent layer on top of the work queue.
Track custom ordering, clusters, skips, and per-issue annotations.
Run with no subcommand to generate a full prioritized markdown plan.""",
        epilog="""\
typical workflow:
  desloppify scan                       # detect issues
  desloppify plan                       # full prioritized markdown
  desloppify plan queue                 # compact table of all items
  desloppify plan cluster create ...    # group related issues
  desloppify plan focus <cluster>       # narrow scope
  desloppify next                       # work on the next item
  desloppify plan resolve <id> --attest .. # mark as fixed

patterns (used by reorder, skip, resolve, describe, note, etc.):
  Patterns match issues by detector, file, ID prefix, glob, or name.
  Cluster names also work as patterns — they expand to all member IDs.
  Examples: "security", "src/foo.py", "unused::*React*", "my-cluster"

subcommands:
  show       Show plan metadata summary
  queue      Compact table of upcoming queue items
  reset      Reset plan to empty
  reorder    Reposition issues or clusters in the queue
  resolve    Mark issues as fixed (score movement + next-step)
  describe   Set augmented description
  note       Set note on issues
  skip       Skip issues (temporary/permanent/false_positive)
  unskip     Bring skipped issues back to queue
  reopen     Reopen resolved issues
  focus      Set or clear active cluster focus
  cluster    Manage issue clusters
  triage     Staged triage workflow (after review)
  scan-gate  Check or skip scan requirement for workflow items""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_plan.add_argument("--state", type=str, default=None, help="Path to state file")
    p_plan.add_argument(
        "--output", type=str, metavar="FILE",
        help="Write to file instead of stdout (refuses to overwrite existing files)",
    )

    plan_sub = p_plan.add_subparsers(dest="plan_action")

    # plan show
    plan_sub.add_parser("show", help="Show plan metadata summary")

    _add_queue_subparser(plan_sub)

    # plan reset
    plan_sub.add_parser("reset", help="Reset plan to empty")

    _add_reorder_subparser(plan_sub)
    _add_annotation_subparsers(plan_sub)
    _add_skip_subparsers(plan_sub)
    _add_resolve_subparser(plan_sub)
    _add_cluster_subparser(plan_sub)
    _add_triage_subparser(plan_sub)
    _add_scan_gate_subparser(plan_sub)
    _add_commit_log_subparser(plan_sub)


__all__ = ["add_plan_parser"]
