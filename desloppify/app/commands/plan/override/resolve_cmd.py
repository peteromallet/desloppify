"""Resolve command handler for plan overrides."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.attestation import (
    show_attestation_requirement,
    show_note_length_requirement,
    validate_attestation,
    validate_note_length,
)
from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.app.commands.plan.shared.patterns import resolve_ids_from_patterns
from desloppify.app.commands.resolve.cmd import cmd_resolve
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.triage.protection import protected_review_issue_ids
from desloppify.engine._work_queue.core import ATTEST_EXAMPLE
from desloppify.engine.plan_state import (
    load_plan,
)

from .resolve_helpers import (
    check_cluster_guard,
    split_synthetic_patterns,
)
from .resolve_workflow import resolve_workflow_patterns


def cmd_plan_resolve(args: argparse.Namespace) -> None:
    """Mark issues as fixed and delegate to resolve command UX."""
    patterns: list[str] = getattr(args, "patterns", [])
    attestation: str | None = getattr(args, "attest", None)
    note: str | None = getattr(args, "note", None)

    if getattr(args, "confirm", False):
        if not note:
            print(colorize("  --confirm requires --note to describe what you did.", "red"))
            return
        attestation = f"I have actually {note} and I am not gaming the score."
        args.attest = attestation

    synthetic_ids, real_patterns = split_synthetic_patterns(patterns)
    if synthetic_ids:
        workflow_outcome = resolve_workflow_patterns(
            args,
            synthetic_ids=synthetic_ids,
            real_patterns=real_patterns,
            note=note,
        )
        if workflow_outcome.status == "blocked":
            return
        if workflow_outcome.status == "handled":
            return
        patterns = workflow_outcome.remaining_patterns
        args.patterns = patterns

    if not validate_note_length(note):
        show_note_length_requirement(note)
        return

    if not validate_attestation(attestation):
        show_attestation_requirement("Plan resolve", attestation, ATTEST_EXAMPLE)
        return

    plan: dict | None = None
    try:
        runtime = command_runtime(args)
        state = runtime.state
        plan = load_plan()
        if check_cluster_guard(patterns, plan, state):
            return
        protected_ids = sorted(
            set(resolve_ids_from_patterns(state, patterns, plan=plan, status_filter="all"))
            & protected_review_issue_ids(plan)
        )
        if protected_ids:
            print(
                colorize(
                    "  Cannot resolve protected review item(s): "
                    + ", ".join(protected_ids),
                    "red",
                )
            )
            return
    except PLAN_LOAD_EXCEPTIONS:
        plan = None

    resolve_args = argparse.Namespace(
        status="fixed",
        patterns=patterns,
        note=note,
        attest=attestation,
        confirm_batch_wontfix=False,
        force_resolve=bool(getattr(args, "force_resolve", False)),
        state=getattr(args, "state", None),
        lang=getattr(args, "lang", None),
        path=getattr(args, "path", None),
        exclude=getattr(args, "exclude", None),
    )

    cmd_resolve(resolve_args)


__all__ = ["cmd_plan_resolve"]
