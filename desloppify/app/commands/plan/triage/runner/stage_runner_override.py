"""Per-stage subprocess runner override registry.

Lives in its own module to avoid circular imports between
:mod:`orchestrator_codex_pipeline` and the parallel sub-runners
(:mod:`orchestrator_codex_observe`, :mod:`orchestrator_codex_sense`)
that need to consult the override.

The override is set transiently by alternative pipeline wrappers (for
example :mod:`rovodev_pipeline`) so that all per-stage subprocesses for
the lifetime of one pipeline call route through the chosen backend.
"""

from __future__ import annotations

from .codex_runner import run_triage_stage

_STAGE_RUNNER_OVERRIDE = None
_RUNNER_NAME_OVERRIDE: str | None = None


def set_stage_runner_override(stage_runner_fn, runner_name: str | None) -> None:
    """Install a transient per-stage runner override and label."""
    global _STAGE_RUNNER_OVERRIDE, _RUNNER_NAME_OVERRIDE
    _STAGE_RUNNER_OVERRIDE = stage_runner_fn
    _RUNNER_NAME_OVERRIDE = runner_name


def clear_stage_runner_override() -> None:
    """Remove any installed override."""
    global _STAGE_RUNNER_OVERRIDE, _RUNNER_NAME_OVERRIDE
    _STAGE_RUNNER_OVERRIDE = None
    _RUNNER_NAME_OVERRIDE = None


def active_stage_runner():
    """Return the active per-stage subprocess runner.

    Falls back to the codex stage runner when no override is set.
    """
    return _STAGE_RUNNER_OVERRIDE or run_triage_stage


def active_runner_name(default: str = "codex") -> str:
    """Return the active runner label (used in run logs/summaries)."""
    return _RUNNER_NAME_OVERRIDE or default


def stage_runner_override():
    """Return the raw override or None (used by pipeline dependency wiring)."""
    return _STAGE_RUNNER_OVERRIDE


__all__ = [
    "active_runner_name",
    "active_stage_runner",
    "clear_stage_runner_override",
    "set_stage_runner_override",
    "stage_runner_override",
]
