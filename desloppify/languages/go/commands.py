"""Detect command registry for language plugin scaffolding."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ...utils import c

if TYPE_CHECKING:
    import argparse


def cmd_placeholder(_args: argparse.Namespace) -> None:
    print(c("go: placeholder detector command (not implemented)", "yellow"))


def get_detect_commands() -> dict[str, Callable[..., None]]:
    return {"placeholder": cmd_placeholder}
