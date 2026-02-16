"""Tree aggregation and text rendering helpers for visualize.py."""

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
        loc = node.get("loc", 0)
        if loc < min_loc:
            return
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
        return

    agg = _aggregate(node)
    if agg["loc"] < min_loc:
        return

    lines.append(f"{prefix}{node['name']}/  ({agg['files']} files, {agg['loc']:,} LOC, {agg['findings']} findings)")
    if indent >= max_depth:
        return

    children = node["children"]
    if sort_by == "findings":
        children = sorted(children, key=lambda c: -_aggregate(c)["findings"])
    elif sort_by == "coupling":
        children = sorted(children, key=lambda c: -_aggregate(c)["max_coupling"])
    else:
        children = sorted(children, key=lambda c: -_aggregate(c)["loc"])

    for child in children:
        _print_tree(child, indent + 1, max_depth, min_loc, sort_by, detail, lines)
