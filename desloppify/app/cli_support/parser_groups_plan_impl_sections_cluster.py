"""Cluster-focused parser section builder for plan command."""

from __future__ import annotations

import argparse


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
    p_cc.add_argument("--priority", type=int, default=None, help="Priority (lower = higher priority)")
    p_cc.add_argument("--steps-file", "-f", type=str, default=None,
                      help="Load steps from numbered-steps text file")

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
    p_cl.add_argument("--missing-steps", action="store_true", default=False,
                      help="Show only clusters that need action steps")

    # plan cluster merge <source> <target>
    p_cmerge = cluster_sub.add_parser("merge", help="Merge source cluster into target (moves issues, deletes source)")
    p_cmerge.add_argument("source", type=str, help="Source cluster name (will be deleted)")
    p_cmerge.add_argument("target", type=str, help="Target cluster name (receives issues)")

    # plan cluster update <name> [--description "..."] [structured step flags]
    p_cu = cluster_sub.add_parser("update", help="Update cluster description and/or action steps")
    p_cu.add_argument("cluster_name", type=str, help="Cluster name")
    p_cu.add_argument("--description", type=str, default=None, help="Cluster description")
    p_cu.add_argument(
        "--steps",
        nargs="+",
        metavar="STEP",
        default=None,
        help=argparse.SUPPRESS,  # legacy compatibility only; prefer structured step flags
    )
    p_cu.add_argument("--steps-file", "-f", type=str, default=None,
                      help="Load steps from numbered-steps text file")
    p_cu.add_argument("--add-step", type=str, default=None, metavar="TITLE",
                      help="Append a single step")
    p_cu.add_argument("--detail", type=str, default=None,
                      help="Body text for --add-step or --update-step")
    p_cu.add_argument("--update-title", type=str, default=None, metavar="TITLE",
                      help="Replacement title for --update-step")
    p_cu.add_argument("--update-step", type=int, default=None, metavar="N",
                      help="Update step N (1-based); use --update-title, --detail, --effort, --issue-refs")
    p_cu.add_argument("--remove-step", type=int, default=None, metavar="N",
                      help="Remove step N (1-based)")
    p_cu.add_argument("--done-step", type=int, default=None, metavar="N",
                      help="Mark step N (1-based) as done")
    p_cu.add_argument("--undone-step", type=int, default=None, metavar="N",
                      help="Mark step N (1-based) as not done")
    p_cu.add_argument("--priority", type=int, default=None,
                      help="Set cluster priority (lower = higher priority)")
    p_cu.add_argument("--effort", type=str, default=None,
                      choices=["trivial", "small", "medium", "large"],
                      help="Effort tag for --add-step or --update-step")
    dependency_options = p_cu.add_mutually_exclusive_group()
    dependency_options.add_argument(
        "--depends-on",
        nargs="+",
        default=None,
        metavar="CLUSTER",
        help="Cluster(s) this cluster depends on",
    )
    dependency_options.add_argument(
        "--clear-depends-on",
        action="store_true",
        default=False,
        help="Clear all cluster dependencies",
    )
    p_cu.add_argument("--issue-refs", nargs="+", default=None, metavar="REF",
                      help="Issue refs for --add-step or --update-step")

    # plan cluster export <name> [--format text|yaml]
    p_cexport = cluster_sub.add_parser("export", help="Export cluster steps to editable format")
    p_cexport.add_argument("cluster_name", type=str, help="Cluster name")
    p_cexport.add_argument("--format", dest="export_format", choices=["text", "yaml"],
                           default="text", help="Output format (default: text)")

    # plan cluster import <file> [--dry-run]
    p_cimport = cluster_sub.add_parser("import", help="Bulk create/update clusters from YAML")
    p_cimport.add_argument("file", type=str, help="YAML file path")
    p_cimport.add_argument("--dry-run", action="store_true", default=False,
                           help="Preview changes without saving")


__all__ = ["_add_cluster_subparser"]
