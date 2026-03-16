"""directives command: view and manage agent directives."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.base.config import save_config
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize
from desloppify.engine._plan.refresh_lifecycle import VALID_LIFECYCLE_PHASES

# The four phases that actually matter as agent directive hooks.
# Each has: short description, when it fires, example use case.
_PHASES: list[tuple[str, str, str, str]] = [
    (
        "execute",
        "Working the fix queue — code changes, refactors, and fixes.",
        "Fires when the queue fills with work items after triage,\n"
        "    or when you unskip/reopen issues that push back into work mode.",
        "Commit after every 3 fixes. Don't refactor beyond what the issue asks.",
    ),
    (
        "postflight",
        "Execution done — transitioning into planning/review phases.",
        "Fires when the execution queue drains and the system moves into\n"
        "    review, workflow, or triage. Catch-all for leaving work mode.",
        "Stop and summarise what you fixed before continuing.",
    ),
    (
        "triage",
        "Reading issues, deciding what's real, clustering into a plan.",
        "Fires when workflow items complete and triage stages are injected,\n"
        "    or when review surfaces issues that need strategic decisions.",
        "Open every flagged file before deciding. Skip nothing without reading the code.",
    ),
    (
        "review",
        "Scoring subjective dimensions — reading code and assessing quality.",
        "Fires when the system needs subjective scores (first review, stale\n"
        "    dimensions, or post-triage re-review). Covers all review sub-phases.",
        "Use review_packet_blind.json only. Do not read previous scores or targets.",
    ),
    (
        "scan",
        "Running detectors and analyzing the codebase.",
        "Fires when the lifecycle resets to the scan phase after a cycle\n"
        "    completes or when no other phase applies.",
        "Include --skip-slow if this is a mid-cycle rescan.",
    ),
]

_PHASE_NAMES = {name for name, _, _, _ in _PHASES}

_EXAMPLE_DIRECTIVES = {
    "execute": "Commit after every 3 fixes. Don't refactor beyond what the issue asks.",
    "triage": "Open every flagged file before deciding. Skip nothing without reading the code.",
    "review": "Use review_packet_blind.json only. Do not read previous scores or targets.",
}


def cmd_directives(args: argparse.Namespace) -> None:
    """Handle directives subcommands: show, set, unset."""
    action = getattr(args, "directives_action", None)
    if action == "set":
        _directives_set(args)
    elif action == "unset":
        _directives_unset(args)
    else:
        _directives_show(args)


def _directives_show(args: argparse.Namespace) -> None:
    """Show all phases with their directives (if configured)."""
    config = command_runtime(args).config
    messages = config.get("transition_messages", {})
    if not isinstance(messages, dict):
        messages = {}

    active = {
        phase: text
        for phase, text in messages.items()
        if isinstance(text, str) and text.strip()
    }

    print(colorize("\n  Agent Directives\n", "bold"))
    print(
        "  Messages shown to AI agents at lifecycle phase transitions.\n"
        "  Use them to switch models, set constraints, or give context-\n"
        "  specific instructions at key moments in the workflow.\n"
    )

    for name, description, when, example_use in _PHASES:
        directive = active.get(name)
        if directive:
            marker = colorize("*", "green")
            print(f"  {marker} {colorize(name, 'cyan')}  {description}")
            print(colorize(f"    When: {when}", "dim"))
            print(f"    Directive: {directive}")
        else:
            print(f"    {colorize(name, 'cyan')}  {description}")
            print(colorize(f"    When: {when}", "dim"))
            print(colorize(f"    e.g.: {example_use}", "dim"))
        print()

    count = len(active)
    if count:
        print(colorize(f"  {count} directive{'s' if count != 1 else ''} configured.\n", "green"))
    else:
        print(colorize("  No directives configured.\n", "dim"))

    print(colorize("  Examples:", "dim"))
    for phase, text in _EXAMPLE_DIRECTIVES.items():
        print(colorize(f'    desloppify directives set {phase} "{text}"', "dim"))
    print()
    print(colorize("  Commands:", "dim"))
    print(colorize('    desloppify directives set <phase> "<message>"', "dim"))
    print(colorize("    desloppify directives unset <phase>", "dim"))
    print()


def _directives_set(args: argparse.Namespace) -> None:
    """Set a directive for a lifecycle phase."""
    phase = args.phase
    text = args.message

    # Accept the main phases (including postflight) plus any valid lifecycle phase.
    if phase != "postflight" and phase not in VALID_LIFECYCLE_PHASES:
        valid = ", ".join(sorted(_PHASE_NAMES))
        raise CommandError(f"unknown phase {phase!r}; valid phases: {valid}")

    config = command_runtime(args).config
    messages = config.get("transition_messages", {})
    if not isinstance(messages, dict):
        messages = {}
    messages[phase] = text
    config["transition_messages"] = messages

    try:
        save_config(config)
    except OSError as e:
        raise CommandError(f"could not save config: {e}") from e
    print(colorize(f"  Set directive for {phase}:", "green"))
    print(f"    {text}")


def _directives_unset(args: argparse.Namespace) -> None:
    """Remove a directive for a lifecycle phase."""
    phase = args.phase

    config = command_runtime(args).config
    messages = config.get("transition_messages", {})
    if not isinstance(messages, dict):
        messages = {}

    if phase not in messages:
        raise CommandError(f"no directive set for phase {phase!r}")

    del messages[phase]
    config["transition_messages"] = messages

    try:
        save_config(config)
    except OSError as e:
        raise CommandError(f"could not save config: {e}") from e
    print(colorize(f"  Removed directive for {phase}", "green"))
