"""Central command registry for CLI command handler resolution."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from functools import lru_cache

CommandHandler = Callable[[argparse.Namespace], None]


def _build_handlers() -> dict[str, CommandHandler]:
    """Import all command modules and build the handler dict on first access."""
    from desloppify.app.commands.autofix import cmd_autofix
    from desloppify.app.commands.backlog import cmd_backlog
    from desloppify.app.commands.config import cmd_config
    from desloppify.app.commands.detect import cmd_detect
    from desloppify.app.commands.directives import cmd_directives
    from desloppify.app.commands.dev import cmd_dev
    from desloppify.app.commands.exclude import cmd_exclude
    from desloppify.app.commands.langs import cmd_langs
    from desloppify.app.commands.move import cmd_move
    from desloppify.app.commands.next import cmd_next
    from desloppify.app.commands.plan import cmd_plan
    from desloppify.app.commands.suppress import cmd_suppress
    from desloppify.app.commands.review import cmd_review
    from desloppify.app.commands.scan import cmd_scan
    from desloppify.app.commands.show import cmd_show
    from desloppify.app.commands.status import cmd_status
    from desloppify.app.commands.persona_qa import cmd_persona_qa
    from desloppify.app.commands.update_skill import cmd_update_skill
    from desloppify.app.commands.viz import cmd_tree, cmd_viz
    from desloppify.app.commands.zone import cmd_zone

    return {
        "scan": cmd_scan,
        "status": cmd_status,
        "show": cmd_show,
        "next": cmd_next,
        "backlog": cmd_backlog,
        "suppress": cmd_suppress,
        "exclude": cmd_exclude,
        "autofix": cmd_autofix,
        "plan": cmd_plan,
        "detect": cmd_detect,
        "tree": cmd_tree,
        "viz": cmd_viz,
        "move": cmd_move,
        "zone": cmd_zone,
        "review": cmd_review,
        "config": cmd_config,
        "directives": cmd_directives,
        "dev": cmd_dev,
        "langs": cmd_langs,
        "update-skill": cmd_update_skill,
        "persona-qa": cmd_persona_qa,
    }


@lru_cache(maxsize=1)
def get_command_handlers() -> dict[str, CommandHandler]:
    """Return cached command handler dict, building on first access."""
    return _build_handlers()


__all__ = ["CommandHandler", "get_command_handlers"]
