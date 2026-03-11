"""Plan rendering/query helpers (read-only ownership).

This package owns human-readable planning views (markdown/selection helpers)
and does not own plan persistence or queue mutation.

Ownership contract:
- ``engine.plan_state``: persisted plan state/schema/policy surface.
- ``engine.plan_ops``: queue/cluster/skip/annotation mutations.
- ``engine.plan_queue``: reconcile/sync lifecycle orchestration.
- ``engine.plan_triage``: triage prompts/commands/contracts.
- ``engine.planning`` (this package): read-only rendering/query helpers only.

``engine._plan`` remains internal implementation detail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from desloppify.engine.planning.helpers import CONFIDENCE_ORDER

if TYPE_CHECKING:
    from pathlib import Path

    from desloppify.engine.planning.scan import PlanScanOptions
    from desloppify.engine.planning.types import PlanItem, PlanState
    from desloppify.languages.framework import LangConfig, LangRun
    from desloppify.state_io import Issue


def generate_plan_md(state: PlanState, plan: dict | None = None) -> str:
    from desloppify.engine.planning.render import generate_plan_md as _generate_plan_md

    if plan is None:
        return _generate_plan_md(state)
    return _generate_plan_md(state, plan)


def get_next_item(
    state: PlanState,
    scan_path: str | None = None,
) -> PlanItem | None:
    from desloppify.engine.planning.select import get_next_item as _get_next_item

    if scan_path is None:
        return _get_next_item(state)
    return _get_next_item(state, scan_path=scan_path)


def get_next_items(
    state: PlanState,
    count: int = 1,
    scan_path: str | None = None,
) -> list[PlanItem]:
    from desloppify.engine.planning.select import get_next_items as _get_next_items

    if count == 1 and scan_path is None:
        return _get_next_items(state)
    if scan_path is None:
        return _get_next_items(state, count=count)
    if count == 1:
        return _get_next_items(state, scan_path=scan_path)
    return _get_next_items(state, count=count, scan_path=scan_path)


__all__ = [
    "CONFIDENCE_ORDER",
    "generate_plan_md",
    "get_next_item",
    "get_next_items",
]
