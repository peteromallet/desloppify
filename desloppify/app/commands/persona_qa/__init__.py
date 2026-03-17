"""Persona-based browser QA command package."""

from __future__ import annotations

import argparse


def cmd_persona_qa(args: argparse.Namespace) -> None:
    """Dispatch to the persona QA command implementation."""
    from .cmd import cmd_persona_qa as _cmd_persona_qa

    _cmd_persona_qa(args)


__all__ = ["cmd_persona_qa"]
