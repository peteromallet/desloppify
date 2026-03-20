"""Canonical shared triage workflow labels and command snippets."""

from __future__ import annotations

from dataclasses import dataclass

TRIAGE_STAGE_LABELS: tuple[tuple[str, str], ...] = (
    ("strategize", "Analyse cross-cycle trends & set strategic focus"),
    ("observe", "Analyse issues & spot contradictions"),
    ("reflect", "Form strategy & present to user"),
    ("organize", "Defer contradictions, cluster, & prioritize"),
    ("enrich", "Make steps executor-ready (detail, refs)"),
    ("sense-check", "Verify accuracy, structure & value"),
    ("commit", "Write strategy & confirm"),
)

TRIAGE_RUNNERS: tuple[str, str] = ("codex", "claude")

TRIAGE_CMD_STRATEGIZE = (
    'desloppify plan triage --stage strategize --report '
    '\'"{"score_trend":"stable","debt_trend":"stable"}"\''
)
TRIAGE_CMD_OBSERVE = (
    'desloppify plan triage --stage observe --report '
    '"analysis of themes and root causes..."'
)
TRIAGE_CMD_REFLECT = (
    'desloppify plan triage --stage reflect --report '
    '"comparison against completed work..."'
)
TRIAGE_CMD_ORGANIZE = (
    'desloppify plan triage --stage organize --report '
    '"summary of organization and priorities..."'
)
TRIAGE_CMD_ENRICH = (
    'desloppify plan triage --stage enrich --report '
    '"summary of enrichment work done..."'
)
TRIAGE_CMD_SENSE_CHECK = (
    'desloppify plan triage --stage sense-check --report '
    '"summary of sense-check findings..."'
)
TRIAGE_CMD_COMPLETE = 'desloppify plan triage --complete --strategy "execution plan..."'
TRIAGE_CMD_COMPLETE_VERBOSE = (
    "desloppify plan triage --complete --strategy "
    '"execution plan with priorities and verification..."'
)
TRIAGE_CMD_CONFIRM_EXISTING = (
    'desloppify plan triage --confirm-existing --note "..." --strategy "..."'
)
TRIAGE_CMD_CLUSTER_CREATE = 'desloppify plan cluster create <name> --description "..."'
TRIAGE_CMD_CLUSTER_ADD = "desloppify plan cluster add <name> <issue-patterns>"
TRIAGE_CMD_CLUSTER_ENRICH = (
    'desloppify plan cluster update <name> --description "..." --steps '
    '"step 1" "step 2"'
)
TRIAGE_CMD_CLUSTER_ENRICH_COMPACT = (
    'desloppify plan cluster update <name> --description "..." --steps '
    '"step1" "step2"'
)
TRIAGE_CMD_CLUSTER_STEPS = (
    'desloppify plan cluster update <name> --steps "step 1" "step 2"'
)
TRIAGE_CMD_RUN_STAGES_CODEX = "desloppify plan triage --run-stages --runner codex"
TRIAGE_CMD_RUN_STAGES_CLAUDE = "desloppify plan triage --run-stages --runner claude"

_RUNNER_STAGE_NAMES = frozenset(
    stage_name for stage_name, _label in TRIAGE_STAGE_LABELS if stage_name != "commit"
)
_MANUAL_STAGE_COMMANDS: dict[str, str] = {
    "strategize": TRIAGE_CMD_STRATEGIZE,
    "observe": TRIAGE_CMD_OBSERVE,
    "reflect": TRIAGE_CMD_REFLECT,
    "organize": TRIAGE_CMD_ORGANIZE,
    "enrich": TRIAGE_CMD_ENRICH,
    "sense-check": TRIAGE_CMD_SENSE_CHECK,
    "commit": TRIAGE_CMD_COMPLETE,
}


@dataclass(frozen=True)
class StagePrerequisite:
    """One required upstream stage for a triage workflow seam."""

    stage_name: str
    require_confirmation: bool = False


@dataclass(frozen=True)
class StageReadiness:
    """Readiness state for one triage stage."""

    name: str
    recorded: bool
    confirmed: bool


@dataclass(frozen=True)
class TriageProgress:
    """Canonical stage progression snapshot for display and validation."""

    stages: tuple[StageReadiness, ...]
    current_stage: str | None
    blocked_reason: str | None
    next_command: str | None
    completed_count: int
    confirmed_count: int


TRIAGE_STAGE_PREREQUISITES: dict[str, tuple[StagePrerequisite, ...]] = {
    "strategize": (),
    "observe": (StagePrerequisite("strategize"),),
    "reflect": (StagePrerequisite("observe"),),
    "organize": (
        StagePrerequisite("observe"),
        StagePrerequisite("reflect"),
    ),
    "enrich": (
        StagePrerequisite("observe"),
        StagePrerequisite("reflect"),
        StagePrerequisite("organize", require_confirmation=True),
    ),
    "sense-check": (
        StagePrerequisite("enrich", require_confirmation=True),
    ),
    "commit": (
        StagePrerequisite("sense-check"),
    ),
}

TRIAGE_STAGE_DEPENDENCIES: dict[str, set[str]] = {
    stage: {prerequisite.stage_name for prerequisite in prerequisites}
    for stage, prerequisites in TRIAGE_STAGE_PREREQUISITES.items()
}

_STAGE_LABEL_BY_NAME = dict(TRIAGE_STAGE_LABELS)


def _confirm_stage_command(stage_name: str) -> str:
    return f"desloppify plan triage --confirm {stage_name}"


def _first_unmet_prerequisite(
    stage_name: str,
    recorded: dict[str, bool],
    confirmed: dict[str, bool],
) -> StagePrerequisite | None:
    for prerequisite in TRIAGE_STAGE_PREREQUISITES[stage_name]:
        if not recorded.get(prerequisite.stage_name, False):
            return prerequisite
        if prerequisite.require_confirmation and not confirmed.get(prerequisite.stage_name, False):
            return prerequisite
    return None


def compute_triage_progress(stages_data: dict) -> TriageProgress:
    """Return canonical triage-stage progression for display and validation."""
    stage_map = stages_data if isinstance(stages_data, dict) else {}
    if "strategize" not in stage_map and any(
        name in stage_map for name in ("observe", "reflect", "organize", "enrich", "sense-check", "commit")
    ):
        stage_map = {
            **stage_map,
            "strategize": {
                "stage": "strategize",
                "report": "(legacy: predates strategize stage)",
                "confirmed_at": "legacy",
            },
        }
    readiness: list[StageReadiness] = []
    recorded: dict[str, bool] = {}
    confirmed: dict[str, bool] = {}

    for stage_name, _label in TRIAGE_STAGE_LABELS:
        payload = stage_map.get(stage_name, {})
        is_recorded = isinstance(payload, dict) and stage_name in stage_map
        is_confirmed = bool(payload.get("confirmed_at")) if isinstance(payload, dict) else False
        readiness.append(
            StageReadiness(
                name=stage_name,
                recorded=is_recorded,
                confirmed=is_confirmed,
            )
        )
        recorded[stage_name] = is_recorded
        confirmed[stage_name] = is_confirmed

    current_stage: str | None = None
    blocked_reason: str | None = None
    next_command: str | None = None

    for stage_name, label in TRIAGE_STAGE_LABELS:
        if recorded[stage_name]:
            continue
        missing = _first_unmet_prerequisite(stage_name, recorded, confirmed)
        if missing is None:
            current_stage = stage_name
            next_command = triage_manual_stage_command(stage_name)
        else:
            prerequisite_label = _STAGE_LABEL_BY_NAME.get(missing.stage_name, missing.stage_name)
            if missing.require_confirmation and recorded.get(missing.stage_name, False):
                blocked_reason = f"{label} blocked until {prerequisite_label} is confirmed."
                next_command = _confirm_stage_command(missing.stage_name)
            else:
                blocked_reason = f"{label} blocked until {prerequisite_label} is recorded."
                next_command = triage_manual_stage_command(missing.stage_name)
        break

    return TriageProgress(
        stages=tuple(readiness),
        current_stage=current_stage,
        blocked_reason=blocked_reason,
        next_command=next_command,
        completed_count=sum(1 for stage in readiness if stage.recorded),
        confirmed_count=sum(1 for stage in readiness if stage.confirmed),
    )


def triage_run_stages_command(
    *,
    runner: str = "codex",
    only_stages: str | tuple[str, ...] | list[str] | None = None,
) -> str:
    """Return the canonical staged triage runner command."""
    resolved_runner = str(runner).strip().lower()
    if resolved_runner not in TRIAGE_RUNNERS:
        supported = ", ".join(TRIAGE_RUNNERS)
        raise ValueError(f"Unsupported triage runner: {runner!r}. Valid: {supported}")

    command = f"desloppify plan triage --run-stages --runner {resolved_runner}"
    if only_stages is None:
        return command

    if isinstance(only_stages, str):
        stages = [only_stages]
    else:
        stages = [str(stage).strip().lower() for stage in only_stages if str(stage).strip()]

    invalid = [stage for stage in stages if stage not in _RUNNER_STAGE_NAMES]
    if invalid:
        supported = ", ".join(sorted(_RUNNER_STAGE_NAMES))
        bad = ", ".join(sorted(set(invalid)))
        raise ValueError(f"Unsupported triage stage(s): {bad}. Valid: {supported}")

    return f"{command} --only-stages {','.join(stages)}"


def triage_runner_commands(
    *,
    only_stages: str | tuple[str, ...] | list[str] | None = None,
) -> tuple[tuple[str, str], tuple[str, str]]:
    """Return the preferred staged-runner commands for Codex and Claude."""
    return (
        ("Codex", triage_run_stages_command(runner="codex", only_stages=only_stages)),
        ("Claude", triage_run_stages_command(runner="claude", only_stages=only_stages)),
    )


def triage_manual_stage_command(stage: str) -> str:
    """Return the manual fallback command for a triage stage."""
    resolved_stage = str(stage).strip().lower()
    if resolved_stage not in _MANUAL_STAGE_COMMANDS:
        supported = ", ".join(sorted(_MANUAL_STAGE_COMMANDS))
        raise ValueError(f"Unsupported triage stage: {stage!r}. Valid: {supported}")
    return _MANUAL_STAGE_COMMANDS[resolved_stage]


__all__ = [
    "StagePrerequisite",
    "StageReadiness",
    "TriageProgress",
    "TRIAGE_STAGE_DEPENDENCIES",
    "TRIAGE_STAGE_LABELS",
    "TRIAGE_STAGE_PREREQUISITES",
    "TRIAGE_CMD_CLUSTER_ADD",
    "TRIAGE_CMD_CLUSTER_CREATE",
    "TRIAGE_CMD_CLUSTER_ENRICH",
    "TRIAGE_CMD_CLUSTER_ENRICH_COMPACT",
    "TRIAGE_CMD_CLUSTER_STEPS",
    "TRIAGE_CMD_COMPLETE",
    "TRIAGE_CMD_SENSE_CHECK",
    "TRIAGE_CMD_STRATEGIZE",
    "TRIAGE_CMD_COMPLETE_VERBOSE",
    "TRIAGE_CMD_CONFIRM_EXISTING",
    "TRIAGE_CMD_ENRICH",
    "TRIAGE_CMD_OBSERVE",
    "TRIAGE_CMD_ORGANIZE",
    "TRIAGE_CMD_REFLECT",
    "TRIAGE_CMD_RUN_STAGES_CLAUDE",
    "TRIAGE_CMD_RUN_STAGES_CODEX",
    "TRIAGE_RUNNERS",
    "compute_triage_progress",
    "triage_manual_stage_command",
    "triage_run_stages_command",
    "triage_runner_commands",
]
