"""Runtime context helpers for command handlers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.helpers.state import state_path
from desloppify.core.config import load_config


@dataclass(frozen=True)
class CommandRuntime:
    """Explicit runtime dependencies shared by command handlers."""

    config: dict
    state: dict
    state_path: Path | None


def command_runtime(args) -> CommandRuntime:
    """Return runtime context from explicit args.runtime or construct one."""
    runtime = getattr(args, "runtime", None)
    if isinstance(runtime, CommandRuntime):
        return runtime

    config = load_config()
    sp = state_path(args)
    if isinstance(sp, str):
        sp = Path(sp)

    state = state_mod.load_state(sp)

    return CommandRuntime(config=config, state=state, state_path=sp)


__all__ = ["CommandRuntime", "command_runtime"]
