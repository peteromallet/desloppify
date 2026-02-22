"""Reusable CLI rendering snippets for command modules."""

from __future__ import annotations

from collections.abc import Callable

from desloppify.file_discovery import rel
from desloppify.utils import colorize


def print_agent_plan(
    steps: list[str],
    *,
    next_command: str | None = None,
    header: str = "  AGENT PLAN:",
) -> None:
    """Print a consistent AGENT PLAN block with numbered steps."""
    if not steps:
        return
    print(colorize(header, "yellow"))
    for idx, step in enumerate(steps, 1):
        print(colorize(f"  {idx}. {step}", "dim"))
    if next_command:
        print(colorize(f"  Next command: `{next_command}`", "dim"))


def print_replacement_groups(
    groups: dict[str, list[tuple[str, str]]],
    *,
    title: str,
    rel_fn: Callable[[str], str] = rel,
) -> None:
    """Print grouped old→new replacement lines by file."""
    if not groups:
        return
    print(colorize(title, "cyan"))
    for filepath, replacements in sorted(groups.items()):
        print(f"    {rel_fn(filepath)}:")
        for old, new in replacements:
            print(f"      {old}  →  {new}")
    print()


def print_ranked_actions(actions: list[dict], *, limit: int = 3) -> bool:
    """Print the highest-impact narrative actions and return True when shown."""
    ranked = sorted(
        [action for action in actions if int(action.get("count", 0)) > 0],
        key=lambda action: (
            -float(action.get("impact", 0.0)),
            -int(action.get("count", 0)),
            int(action.get("priority", 999)),
        ),
    )
    if not ranked:
        return False
    print(colorize("  Biggest things impacting score:", "cyan"))
    for action in ranked[:limit]:
        detector = action.get("detector", "unknown")
        count = int(action.get("count", 0))
        command = action.get("command", "desloppify next")
        print(colorize(f"    - {detector}: {count} open — `{command}`", "dim"))
    return True


__all__ = [
    "print_agent_plan",
    "print_ranked_actions",
    "print_replacement_groups",
]
