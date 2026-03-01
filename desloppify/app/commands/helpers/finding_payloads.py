"""Typed finding/detail accessors for command-layer renderers."""

from __future__ import annotations

from typing import Any, Mapping, TypedDict, cast

from desloppify import state as state_mod


class FindingDetail(TypedDict, total=False):
    """Known finding detail keys used by command rendering paths."""

    category: str
    count: int
    dimension: str
    dimension_name: str
    importers: int
    investigation: bool
    line: int
    lines: list[int]
    strict_score: float
    suggestion: str


def state_findings(
    state: state_mod.StateModel | dict[str, Any],
    *,
    strict: bool = False,
) -> dict[str, state_mod.Finding]:
    """Return typed state findings map or raise on contract violations."""
    if strict:
        return state_mod.require_findings(state)
    findings = state.get("findings")
    if isinstance(findings, dict):
        return cast(dict[str, state_mod.Finding], findings)
    return {}


def finding_detail(finding: Mapping[str, Any]) -> FindingDetail:
    """Return typed detail mapping for a finding-like payload."""
    detail = finding.get("detail")
    if isinstance(detail, dict):
        return cast(FindingDetail, detail)
    return FindingDetail()


def detail_dimension(finding: Mapping[str, Any]) -> str:
    """Return normalized detail.dimension value."""
    return str(finding_detail(finding).get("dimension", "")).strip()


def detail_lines(finding: Mapping[str, Any]) -> list[int]:
    """Return normalized integer line list from finding detail."""
    raw_lines = finding_detail(finding).get("lines", [])
    if not isinstance(raw_lines, list):
        return []
    return [int(line) for line in raw_lines if isinstance(line, int | float)]


def detail_target_line(finding: Mapping[str, Any]) -> int | None:
    """Return primary target line from detail.line or detail.lines[0]."""
    detail = finding_detail(finding)
    line = detail.get("line")
    if isinstance(line, int):
        return line
    lines = detail_lines(finding)
    return lines[0] if lines else None


__all__ = [
    "FindingDetail",
    "detail_dimension",
    "detail_lines",
    "detail_target_line",
    "finding_detail",
    "state_findings",
]
