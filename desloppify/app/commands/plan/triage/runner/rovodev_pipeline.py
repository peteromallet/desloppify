"""Rovo Dev pipeline wrapper for triage stage execution.

The pipeline body lives in :mod:`orchestrator_codex_pipeline`; this module
swaps the per-stage subprocess runner (and the ``runner`` label that
appears in run logs / summaries) to Rovo Dev for the lifetime of one
``run_rovodev_pipeline`` invocation.
"""

from __future__ import annotations

import argparse

from . import orchestrator_codex_pipeline as _pipeline
from . import stage_runner_override as _override
from .rovodev_runner import run_triage_stage_rovodev

if False:  # pragma: no cover — import guard for type checkers
    from ..services import TriageServices


def run_rovodev_pipeline(
    args: argparse.Namespace,
    *,
    stages_to_run: list[str],
    services: "TriageServices | None" = None,
) -> None:
    """Run triage stages via ``acli rovodev`` subprocesses.

    Behaves exactly like :func:`run_codex_pipeline` but uses the Rovo Dev
    stage runner instead of the codex runner. The ``runner`` field in
    ``run_summary.json`` and the run log header is set to ``"rovodev"``.
    The override also flows through parallel sub-runners (observe,
    sense-check) via :mod:`stage_runner_override`.
    """
    previous_runner = _override._STAGE_RUNNER_OVERRIDE
    previous_label = _override._RUNNER_NAME_OVERRIDE
    _override.set_stage_runner_override(run_triage_stage_rovodev, "rovodev")
    try:
        _pipeline.run_codex_pipeline(
            args,
            stages_to_run=stages_to_run,
            services=services,
        )
    finally:
        _override.set_stage_runner_override(previous_runner, previous_label)


__all__ = ["run_rovodev_pipeline"]
