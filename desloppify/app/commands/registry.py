"""Central command registry for CLI command handler resolution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

CommandHandler = Callable[[Any], None]

_COMMAND_HANDLERS: dict[str, CommandHandler] | None = None


def _build_handlers() -> dict[str, CommandHandler]:
    """Import all command modules and build the handler dict on first access."""
    from desloppify.app.commands.config_cmd import cmd_config
    from desloppify.app.commands.detect import cmd_detect
    from desloppify.app.commands.dev_cmd import cmd_dev
    from desloppify.app.commands.exclude_cmd import cmd_exclude
    from desloppify.app.commands.fix.cmd import cmd_fix
    from desloppify.app.commands.langs import cmd_langs
    from desloppify.app.commands.move.move import cmd_move
    from desloppify.app.commands.next import cmd_next
    from desloppify.app.commands.plan.cmd import cmd_plan
    from desloppify.app.commands.resolve.cmd import cmd_ignore_pattern
    from desloppify.app.commands.review import cmd_review
    from desloppify.app.commands.scan import cmd_scan
    from desloppify.app.commands.show.cmd import cmd_show
    from desloppify.app.commands.status_cmd import cmd_status
    from desloppify.app.commands.update_skill import cmd_update_skill
    from desloppify.app.commands.viz_cmd import cmd_tree, cmd_viz
    from desloppify.app.commands.zone_cmd import cmd_zone

    return {
        "scan": cmd_scan,
        "status": cmd_status,
        "show": cmd_show,
        "next": cmd_next,
        "ignore": cmd_ignore_pattern,
        "exclude": cmd_exclude,
        "fix": cmd_fix,
        "plan": cmd_plan,
        "detect": cmd_detect,
        "tree": cmd_tree,
        "viz": cmd_viz,
        "move": cmd_move,
        "zone": cmd_zone,
        "review": cmd_review,
        "config": cmd_config,
        "dev": cmd_dev,
        "langs": cmd_langs,
        "update-skill": cmd_update_skill,
    }


def get_command_handlers() -> dict[str, CommandHandler]:
    """Return cached command handler dict, building on first access."""
    global _COMMAND_HANDLERS
    if _COMMAND_HANDLERS is None:
        _COMMAND_HANDLERS = _build_handlers()
    return _COMMAND_HANDLERS


__all__ = ["CommandHandler", "get_command_handlers"]
