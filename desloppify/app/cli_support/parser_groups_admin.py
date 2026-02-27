"""CLI parser group builders for admin/workflow command families."""

from __future__ import annotations

import argparse
import sys

from desloppify.languages import get_lang


class _DeprecatedAction(argparse.Action):
    """Argparse action that prints a deprecation warning and stores the value."""

    def __call__(self, parser, namespace, values, option_string=None):
        print(
            f"Warning: {option_string} is deprecated and will be removed in a future version.",
            file=sys.stderr,
        )
        setattr(namespace, self.dest, values)


class _DeprecatedBoolAction(argparse.Action):
    """Argparse action for deprecated boolean flags (store_true equivalent)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("nargs", 0)
        kwargs.setdefault("const", True)
        kwargs.setdefault("default", False)
        super().__init__(*args, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print(
            f"Warning: {option_string} is deprecated and will be removed in a future version.",
            file=sys.stderr,
        )
        setattr(namespace, self.dest, True)


def _add_detect_parser(sub, detector_names: list[str]) -> None:
    p_detect = sub.add_parser(
        "detect",
        help="Run a single detector directly (bypass state)",
        epilog=f"detectors: {', '.join(detector_names)}",
    )
    p_detect.add_argument("detector", type=str, help="Detector to run")
    p_detect.add_argument("--top", type=int, default=20, help="Max items to show (default: 20)")
    p_detect.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_detect.add_argument("--json", action="store_true", help="Output as JSON")
    p_detect.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix detected issues (logs detector only)",
    )
    p_detect.add_argument(
        "--category",
        choices=["imports", "vars", "params", "all"],
        default="all",
        help="Filter unused by category",
    )
    p_detect.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="LOC threshold (large) or similarity (dupes)",
    )
    p_detect.add_argument(
        "--file", type=str, default=None, help="Show deps for specific file"
    )
    p_detect.add_argument(
        "--lang-opt",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Language runtime option override (repeatable)",
    )


def _add_move_parser(sub) -> None:
    p_move = sub.add_parser(
        "move", help="Move a file or directory and update all import references"
    )
    p_move.add_argument(
        "source", type=str, help="File or directory to move (relative to project root)"
    )
    p_move.add_argument("dest", type=str, help="Destination path (file or directory)")
    p_move.add_argument(
        "--dry-run", action="store_true", help="Show changes without modifying files"
    )


def _add_review_parser(sub) -> None:
    p_review = sub.add_parser(
        "review",
        help="Prepare or import holistic subjective review",
        description="Run holistic subjective reviews using LLM-based analysis.",
        epilog="""\
examples:
  desloppify review --prepare
  desloppify review --run-batches --runner codex --parallel --scan-after-import
  desloppify review --external-start --external-runner claude
  desloppify review --external-submit --session-id <id> --import findings.json
  desloppify review --merge --similarity 0.8""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # -- core options --
    g_core = p_review.add_argument_group("core options")
    g_core.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    g_core.add_argument("--state", type=str, default=None, help="Path to state file")
    g_core.add_argument(
        "--prepare",
        action="store_true",
        help="Prepare review data (output to query.json)",
    )
    g_core.add_argument(
        "--import",
        dest="import_file",
        type=str,
        metavar="FILE",
        help="Import review findings from JSON file",
    )
    g_core.add_argument(
        "--validate-import",
        dest="validate_import_file",
        type=str,
        metavar="FILE",
        help="Validate review import payload and selected trust mode without mutating state",
    )
    g_core.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Allow partial review import when invalid findings are skipped "
            "(default: fail on any skipped finding)"
        ),
    )
    g_core.add_argument(
        "--dimensions",
        type=str,
        default=None,
        help="Comma-separated dimensions to evaluate",
    )
    g_core.add_argument(
        "--retrospective",
        action="store_true",
        help=(
            "Include historical review issue status/note context in the packet "
            "to support root-cause vs symptom analysis during review"
        ),
    )
    g_core.add_argument(
        "--retrospective-max-issues",
        type=int,
        default=30,
        help="Max recent historical issues to include in review context (default: 30)",
    )
    g_core.add_argument(
        "--retrospective-max-batch-items",
        type=int,
        default=20,
        help="Max history items included per batch focus slice (default: 20)",
    )
    g_core.add_argument(
        "--force-review-rerun",
        action="store_true",
        help="Bypass the objective-plan-drained gate for review reruns",
    )

    # -- external review --
    g_external = p_review.add_argument_group("external review")
    g_external.add_argument(
        "--external-start",
        action="store_true",
        help=(
            "Start a cloud external review session (generates blind packet, "
            "session id/token, and reviewer template)"
        ),
    )
    g_external.add_argument(
        "--external-submit",
        action="store_true",
        help=(
            "Submit external reviewer JSON via a started session; "
            "CLI injects canonical provenance before import"
        ),
    )
    g_external.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="External review session id for --external-submit",
    )
    g_external.add_argument(
        "--external-runner",
        choices=["claude"],
        default="claude",
        help="External reviewer runner for --external-start (default: claude)",
    )
    g_external.add_argument(
        "--session-ttl-hours",
        type=int,
        default=24,
        help="External review session expiration in hours (default: 24)",
    )

    # -- batch execution --
    g_batch = p_review.add_argument_group("batch execution")
    g_batch.add_argument(
        "--run-batches",
        action="store_true",
        help="Run holistic investigation batches with subagents and merge/import output",
    )
    g_batch.add_argument(
        "--runner",
        choices=["codex"],
        default="codex",
        help="Subagent runner backend (default: codex)",
    )
    g_batch.add_argument(
        "--parallel", action="store_true", help="Run selected batches in parallel"
    )
    g_batch.add_argument(
        "--max-parallel-batches",
        type=int,
        default=3,
        help=(
            "Max concurrent subagent batches when --parallel is enabled "
            "(default: 3)"
        ),
    )
    g_batch.add_argument(
        "--batch-timeout-seconds",
        type=int,
        default=20 * 60,
        help="Per-batch runner timeout in seconds (default: 1200)",
    )
    g_batch.add_argument(
        "--batch-max-retries",
        type=int,
        default=1,
        help=(
            "Retries per failed batch for transient runner/network errors "
            "(default: 1)"
        ),
    )
    g_batch.add_argument(
        "--batch-retry-backoff-seconds",
        type=float,
        default=2.0,
        help=(
            "Base backoff delay for transient batch retries in seconds "
            "(default: 2.0)"
        ),
    )
    g_batch.add_argument(
        "--batch-heartbeat-seconds",
        type=float,
        default=15.0,
        help=(
            "Progress heartbeat interval during parallel batch runs in seconds "
            "(default: 15.0)"
        ),
    )
    g_batch.add_argument(
        "--batch-stall-warning-seconds",
        type=int,
        default=0,
        help=(
            "Emit warning when a running batch exceeds this elapsed time "
            "(0 disables warnings; does not terminate the batch)"
        ),
    )
    g_batch.add_argument(
        "--batch-stall-kill-seconds",
        type=int,
        default=120,
        help=(
            "Terminate a batch when output state is unchanged and runner streams are idle "
            "for this many seconds (default: 120; 0 disables kill recovery)"
        ),
    )
    g_batch.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate packet/prompts only (skip runner/import)",
    )
    g_batch.add_argument(
        "--run-log-file",
        type=str,
        default=None,
        help=(
            "Optional explicit path for live run log output "
            "(overrides default run artifacts path)"
        ),
    )
    g_batch.add_argument(
        "--packet",
        type=str,
        default=None,
        help="Use an existing immutable packet JSON instead of preparing a new one",
    )
    g_batch.add_argument(
        "--only-batches",
        type=str,
        default=None,
        help="Comma-separated 1-based batch indexes to run (e.g. 1,3,5)",
    )
    g_batch.add_argument(
        "--scan-after-import",
        action="store_true",
        help="Run `scan` after successful merged import",
    )

    # -- trust & attestation --
    g_trust = p_review.add_argument_group("trust & attestation")
    g_trust.add_argument(
        "--manual-override",
        action="store_true",
        help=(
            "Allow untrusted assessment score imports. Findings always import; "
            "scores require trusted blind provenance unless this override is set."
        ),
    )
    g_trust.add_argument(
        "--attested-external",
        action="store_true",
        help=(
            "Accept external blind-run assessments as durable scores when "
            "paired with --attest and valid blind packet provenance "
            "(intended for cloud Claude subagent workflows)."
        ),
    )
    g_trust.add_argument(
        "--attest",
        type=str,
        default=None,
        help=(
            "Required with --manual-override or --attested-external. "
            "For attested external imports include both phrases "
            "'without awareness' and 'unbiased'."
        ),
    )

    # -- post-processing --
    g_post = p_review.add_argument_group("post-processing")
    g_post.add_argument(
        "--merge",
        action="store_true",
        help="Merge conceptually duplicate open review findings",
    )
    g_post.add_argument(
        "--similarity",
        type=float,
        default=0.8,
        help="Summary similarity threshold for merge (0-1, default: 0.8)",
    )

    # -- deprecated --
    g_deprecated = p_review.add_argument_group("deprecated")
    g_deprecated.add_argument(
        "--max-age",
        type=int,
        default=None,
        action=_DeprecatedAction,
        help="Deprecated in holistic-only mode (ignored)",
    )
    g_deprecated.add_argument(
        "--max-files",
        type=int,
        default=None,
        action=_DeprecatedAction,
        help="Deprecated in holistic-only mode (ignored)",
    )
    g_deprecated.add_argument(
        "--refresh",
        action=_DeprecatedBoolAction,
        help="Deprecated in holistic-only mode (ignored)",
    )
    g_deprecated.add_argument(
        "--holistic",
        action=_DeprecatedBoolAction,
        help="Deprecated: holistic is now the only review mode",
    )
    g_deprecated.add_argument(
        "--save-run-log",
        action="store_true",
        help=(
            "Deprecated no-op: run logs are now always saved while running "
            "(default location: run artifacts dir)"
        ),
    )


def _add_zone_parser(sub) -> None:
    p_zone = sub.add_parser("zone", help="Show/set/clear zone classifications")
    p_zone.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_zone.add_argument("--state", type=str, default=None, help="Path to state file")
    zone_sub = p_zone.add_subparsers(dest="zone_action")
    zone_sub.add_parser("show", help="Show zone classifications for all files")
    z_set = zone_sub.add_parser("set", help="Override zone for a file")
    z_set.add_argument("zone_path", type=str, help="Relative file path")
    z_set.add_argument(
        "zone_value",
        type=str,
        help="Zone (production, test, config, generated, script, vendor)",
    )
    z_clear = zone_sub.add_parser("clear", help="Remove zone override for a file")
    z_clear.add_argument("zone_path", type=str, help="Relative file path")


def _add_config_parser(sub) -> None:
    p_config = sub.add_parser("config", help="Show/set/unset project configuration")
    config_sub = p_config.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="Show all config values")
    c_set = config_sub.add_parser("set", help="Set a config value")
    c_set.add_argument("config_key", type=str, help="Config key name")
    c_set.add_argument("config_value", type=str, help="Value to set")
    c_unset = config_sub.add_parser("unset", help="Reset a config key to default")
    c_unset.add_argument("config_key", type=str, help="Config key name")


def _fixer_help_lines(langs: list[str]) -> list[str]:
    fixer_help_lines: list[str] = []
    for lang_name in langs:
        try:
            fixer_names = sorted(get_lang(lang_name).fixers.keys())
        except (ImportError, ValueError, TypeError, AttributeError):
            fixer_names = []
        fixer_list = ", ".join(fixer_names) if fixer_names else "none yet"
        fixer_help_lines.append(f"fixers ({lang_name}): {fixer_list}")
    fixer_help_lines.append("special: review — prepare structured review data")
    return fixer_help_lines


def _add_fix_parser(sub, langs: list[str]) -> None:
    p_fix = sub.add_parser(
        "fix",
        help="Auto-fix mechanical issues",
        epilog="\n".join(_fixer_help_lines(langs)),
    )
    p_fix.add_argument("fixer", type=str, help="What to fix")
    p_fix.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_fix.add_argument("--state", type=str, default=None, help="Path to state file")
    p_fix.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files",
    )


def _add_plan_parser(sub) -> None:
    p_plan = sub.add_parser(
        "plan",
        help="Living plan: generate, reorder, cluster, skip, note",
        description="""\
Manage the living plan — a persistent layer on top of the work queue.
Track custom ordering, clusters, skips, and per-finding annotations.
Run with no subcommand to generate a full prioritized markdown plan.""",
        epilog="""\
typical workflow:
  desloppify scan                       # detect findings
  desloppify plan                       # full prioritized markdown
  desloppify plan queue                 # compact table of all items
  desloppify plan cluster create ...    # group related findings
  desloppify plan focus <cluster>       # narrow scope
  desloppify next                       # work on the next item
  desloppify plan done <id> --attest .. # mark as fixed

subcommands:
  show       Show plan metadata summary
  queue      Compact table of upcoming queue items
  reset      Reset plan to empty
  move       Move findings in the queue
  done       Mark findings as fixed (score movement + next-step)
  describe   Set augmented description
  note       Set note on findings
  skip       Skip findings (temporary/permanent/false_positive)
  unskip     Bring skipped findings back to queue
  reopen     Reopen resolved findings
  focus      Set or clear active cluster focus
  cluster    Manage finding clusters""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_plan.add_argument("--state", type=str, default=None, help="Path to state file")
    p_plan.add_argument(
        "--output", type=str, metavar="FILE", help="Write to file instead of stdout"
    )

    plan_sub = p_plan.add_subparsers(dest="plan_action")

    # plan show
    plan_sub.add_parser("show", help="Show plan metadata summary")

    # plan queue
    p_queue = plan_sub.add_parser("queue", help="Compact table of upcoming queue items")
    p_queue.add_argument("--top", type=int, default=30, help="Max items (default: 30, 0=all)")
    p_queue.add_argument("--tier", type=int, choices=[1, 2, 3, 4], default=None,
                         help="Show only items in this tier (T1=critical .. T4=cosmetic)")
    p_queue.add_argument("--cluster", type=str, default=None, metavar="NAME",
                         help="Filter to a specific cluster")
    p_queue.add_argument("--include-skipped", action="store_true",
                         help="Include skipped items at end")

    # plan reset
    plan_sub.add_parser("reset", help="Reset plan to empty")

    # plan move <patterns> <position> [target|N]
    p_move = plan_sub.add_parser(
        "move",
        help="Move findings in the queue",
        epilog="""\
examples:
  desloppify plan move security top                    # prioritize a detector
  desloppify plan move "unused::src/foo.ts::*" top     # prioritize by pattern
  desloppify plan move smells bottom                   # deprioritize smells
  desloppify plan move unused before security          # move before another""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_move.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Finding ID(s), prefix, detector name, file path, or glob",
    )
    p_move.add_argument(
        "position", choices=["top", "bottom", "before", "after", "up", "down"],
        help="Where to move (top, bottom, before, after, up N, down N)",
    )
    p_move.add_argument(
        "target", nargs="?", default=None,
        help="Target finding ID (for before/after) or offset (for up/down)",
    )

    # plan describe <patterns> "<text>"
    p_describe = plan_sub.add_parser("describe", help="Set augmented description")
    p_describe.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Finding ID(s), prefix, detector name, file path, or glob",
    )
    p_describe.add_argument("text", type=str, help="Description text")

    # plan note <patterns> "<text>"
    p_note = plan_sub.add_parser("note", help="Set note on findings")
    p_note.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Finding ID(s), prefix, detector name, file path, or glob",
    )
    p_note.add_argument("text", type=str, help="Note text")

    # plan skip <patterns> [--reason] [--review-after N] [--permanent] [--false-positive] [--note] [--attest]
    p_skip = plan_sub.add_parser(
        "skip",
        help="Skip findings: temporary (default), --permanent (wontfix), or --false-positive",
    )
    p_skip.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Finding ID(s), prefix, detector name, file path, or glob",
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
        "unskip", help="Bring skipped findings back to queue (reopens permanent/fp in state)"
    )
    p_unskip.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Finding ID(s), prefix, detector name, file path, or glob",
    )

    # plan reopen <patterns>
    p_reopen = plan_sub.add_parser(
        "reopen", help="Reopen resolved findings and move back to queue"
    )
    p_reopen.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Finding ID(s), prefix, detector name, file path, or glob",
    )

    # plan done <patterns> --attest [--note]
    p_done = plan_sub.add_parser(
        "done",
        help="Mark findings as fixed (shows score movement + next step)",
        epilog="""\
examples:
  desloppify plan done "unused::src/foo.tsx::React" \\
    --attest "I have actually removed the import and I am not gaming the score."
  desloppify plan done security --note "patched XSS" \\
    --attest "I have actually ..."  """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_done.add_argument(
        "patterns", nargs="+", metavar="PATTERN",
        help="Finding ID(s), prefix, detector name, file path, or glob",
    )
    p_done.add_argument(
        "--note", type=str, default=None, help="Explanation of the fix"
    )
    p_done.add_argument(
        "--attest",
        type=str,
        default=None,
        help=(
            "Required anti-gaming attestation. Must include BOTH keywords "
            "'I have actually' and 'not gaming'."
        ),
    )

    # plan focus <cluster> | --clear
    p_focus = plan_sub.add_parser("focus", help="Set or clear active cluster focus")
    p_focus.add_argument("cluster_name", nargs="?", default=None, help="Cluster name")
    p_focus.add_argument("--clear", action="store_true", help="Clear focus")

    # plan cluster ...
    p_cluster = plan_sub.add_parser(
        "cluster",
        help="Manage finding clusters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cluster_sub = p_cluster.add_subparsers(dest="cluster_action")

    # plan cluster create <name> [--description "..."] [--action "..."]
    p_cc = cluster_sub.add_parser("create", help="Create a cluster")
    p_cc.add_argument("cluster_name", type=str, help="Cluster name (slug)")
    p_cc.add_argument("--description", type=str, default=None, help="Cluster description")
    p_cc.add_argument("--action", type=str, default=None, help="Primary action/command for this cluster")

    # plan cluster add <cluster> <patterns...>
    p_ca = cluster_sub.add_parser("add", help="Add findings to a cluster")
    p_ca.add_argument("cluster_name", type=str, help="Cluster name")
    p_ca.add_argument("patterns", nargs="+", metavar="PATTERN", help="Finding patterns")

    # plan cluster remove <cluster> <patterns...>
    p_cr = cluster_sub.add_parser("remove", help="Remove findings from a cluster")
    p_cr.add_argument("cluster_name", type=str, help="Cluster name")
    p_cr.add_argument("patterns", nargs="+", metavar="PATTERN", help="Finding patterns")

    # plan cluster delete <name>
    p_cd = cluster_sub.add_parser("delete", help="Delete a cluster")
    p_cd.add_argument("cluster_name", type=str, help="Cluster name")

    # plan cluster move <cluster> <position> [target]
    p_cm = cluster_sub.add_parser("move", help="Move cluster as a block")
    p_cm.add_argument("cluster_name", type=str, help="Cluster name")
    p_cm.add_argument(
        "position", choices=["top", "bottom", "before", "after", "up", "down"],
        help="Where to move",
    )
    p_cm.add_argument("target", nargs="?", default=None, help="Target or offset")

    # plan cluster show <name>
    p_cs = cluster_sub.add_parser("show", help="Show cluster details and members")
    p_cs.add_argument("cluster_name", type=str, help="Cluster name")

    # plan cluster list
    cluster_sub.add_parser("list", help="List all clusters")


def _add_viz_parser(sub) -> None:
    p_viz = sub.add_parser("viz", help="Generate interactive HTML treemap")
    p_viz.add_argument("--path", type=str, default=None, help="Project root directory (default: auto-detected)")
    p_viz.add_argument("--output", type=str, default=None, help="Output file path")
    p_viz.add_argument("--state", type=str, default=None, help="Path to state file")


def _add_dev_parser(sub) -> None:
    p_dev = sub.add_parser("dev", help="Developer utilities")
    dev_sub = p_dev.add_subparsers(dest="dev_action", required=True)
    d_scaffold = dev_sub.add_parser(
        "scaffold-lang", help="Generate a standardized language plugin scaffold"
    )
    d_scaffold.add_argument("name", type=str, help="Language name (snake_case)")
    d_scaffold.add_argument(
        "--extension",
        action="append",
        default=None,
        metavar="EXT",
        help="Source file extension (repeatable, e.g. --extension .go --extension .gomod)",
    )
    d_scaffold.add_argument(
        "--marker",
        action="append",
        default=None,
        metavar="FILE",
        help="Project-root detection marker file (repeatable)",
    )
    d_scaffold.add_argument(
        "--default-src",
        type=str,
        default="src",
        metavar="DIR",
        help="Default source directory for scans (default: src)",
    )
    d_scaffold.add_argument(
        "--force", action="store_true", help="Overwrite existing scaffold files"
    )
    d_scaffold.add_argument(
        "--no-wire-pyproject",
        dest="wire_pyproject",
        action="store_false",
        help="Do not edit pyproject.toml testpaths array",
    )
    d_scaffold.set_defaults(wire_pyproject=True)


def _add_langs_parser(sub) -> None:
    sub.add_parser("langs", help="List all available language plugins with depth and tools")


def _add_update_skill_parser(sub) -> None:
    p = sub.add_parser(
        "update-skill",
        help="Install or update the desloppify skill/agent document",
    )
    p.add_argument(
        "interface",
        nargs="?",
        default=None,
        help="Agent interface (claude, codex, cursor, copilot, windsurf, gemini, opencode). "
        "Auto-detected on updates if omitted.",
    )
