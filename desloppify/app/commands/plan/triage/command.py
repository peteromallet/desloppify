"""Handler for `plan triage` command entrypoint."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.state import require_issue_inventory

from .services import default_triage_services
from .workflow import run_triage_workflow

def cmd_plan_triage(args: argparse.Namespace) -> None:
    """Run staged triage workflow: strategize -> observe -> reflect -> organize -> enrich -> sense-check -> commit."""
    triage_services = default_triage_services()
    run_triage_workflow(
        args,
        services=triage_services,
        require_issue_inventory_fn=require_issue_inventory,
    )


__all__ = [
    "cmd_plan_triage",
]
