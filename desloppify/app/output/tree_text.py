"""Text-tree rendering helpers for LLM-readable codebase views."""

from __future__ import annotations


def _aggregate(node: dict) -> dict:
    """Compute aggregate stats for a tree node."""
    if "children" not in node:
        return {
            "files": 1,
            "loc": node.get("loc", 0),
            "findings": node.get("findings_open", 0),
            "max_coupling": node.get("fan_in", 0) + node.get("fan_out", 0),
        }
    agg = {"files": 0, "loc": 0, "findings": 0, "max_coupling": 0}
    for child in node["children"]:
        child_agg = _aggregate(child)
        agg["files"] += child_agg["files"]
        agg["loc"] += child_agg["loc"]
        agg["findings"] += child_agg["findings"]
        agg["max_coupling"] = max(agg["max_coupling"], child_agg["max_coupling"])
    return agg


def _render_leaf_node(
    node: dict,
    *,
    prefix: str,
    min_loc: int,
    detail: bool,
    lines: list[str],
) -> bool:
    loc = node.get("loc", 0)
    if loc < min_loc:
        return False
    findings = node.get("findings_open", 0)
    coupling = node.get("fan_in", 0) + node.get("fan_out", 0)
    parts = [f"{loc:,} LOC"]
    if findings > 0:
        parts.append(f"⚠{findings}")
    if coupling > 10:
        parts.append(f"c:{coupling}")
    lines.append(f"{prefix}{node['name']}  ({', '.join(parts)})")
    if detail and node.get("finding_summaries"):
        for summary in node["finding_summaries"]:
            lines.append(f"{prefix}  → {summary}")
    return True


def _sorted_children(children: list[dict], *, sort_by: str) -> list[dict]:
    if sort_by == "findings":
        return sorted(children, key=lambda child: -_aggregate(child)["findings"])
    if sort_by == "coupling":
        return sorted(children, key=lambda child: -_aggregate(child)["max_coupling"])
    return sorted(children, key=lambda child: -_aggregate(child)["loc"])


def _render_branch_node(
    node: dict,
    *,
    indent: int,
    max_depth: int,
    min_loc: int,
    sort_by: str,
    detail: bool,
    lines: list[str],
) -> bool:
    prefix = "  " * indent
    agg = _aggregate(node)
    if agg["loc"] < min_loc:
        return False

    lines.append(
        f"{prefix}{node['name']}/  "
        f"({agg['files']} files, {agg['loc']:,} LOC, {agg['findings']} findings)"
    )
    if indent >= max_depth:
        return True

    for child in _sorted_children(node["children"], sort_by=sort_by):
        _print_tree(child, indent + 1, max_depth, min_loc, sort_by, detail, lines)
    return True


def _print_tree(
    node: dict,
    indent: int,
    max_depth: int,
    min_loc: int,
    sort_by: str,
    detail: bool,
    lines: list[str],
) -> None:
    """Recursively print annotated tree."""
    prefix = "  " * indent

    if "children" not in node:
        _render_leaf_node(
            node,
            prefix=prefix,
            min_loc=min_loc,
            detail=detail,
            lines=lines,
        )
        return

    _render_branch_node(
        node,
        indent=indent,
        max_depth=max_depth,
        min_loc=min_loc,
        sort_by=sort_by,
        detail=detail,
        lines=lines,
    )


def render_tree_lines(
    root: dict,
    *,
    max_depth: int,
    min_loc: int,
    sort_by: str,
    detail: bool,
) -> list[str]:
    lines: list[str] = []
    _print_tree(root, 0, max_depth, min_loc, sort_by, detail, lines)
    return lines


__all__ = ["render_tree_lines"]
