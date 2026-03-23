"""Batch execution parser option group for review command."""

from __future__ import annotations

import argparse


def _add_batch_execution_options(p_review: argparse.ArgumentParser) -> None:
    g_batch = p_review.add_argument_group("batch execution")
    g_batch.add_argument(
        "--run-batches",
        action="store_true",
        help="Run holistic investigation batches with subagents and merge/import output",
    )
    g_batch.add_argument(
        "--runner",
        choices=["codex", "opencode"],
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
            "Max concurrent subagent batches when --parallel is enabled (default: 3)"
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
            "Retries per failed batch for transient runner/network errors (default: 1)"
        ),
    )
    g_batch.add_argument(
        "--batch-retry-backoff-seconds",
        type=float,
        default=2.0,
        help=(
            "Base backoff delay for transient batch retries in seconds (default: 2.0)"
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
    g_batch.add_argument(
        "--import-run",
        dest="import_run_dir",
        type=str,
        metavar="DIR",
        default=None,
        help=(
            "Re-import results from a completed run directory "
            "(replays merge+import when the original pipeline was interrupted)"
        ),
    )


__all__ = ["_add_batch_execution_options"]
