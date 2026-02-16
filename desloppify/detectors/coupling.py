"""Coupling analysis: boundary violations and boundary candidates.

These detect architectural violations in codebases with shared/tools structure.
The algorithms work on any dep graph — the boundary definitions (what prefixes
constitute "shared" vs "tools") are provided by the caller.
"""

from pathlib import Path

from ..utils import rel


def detect_coupling_violations(path: Path, graph: dict,
                                shared_prefix: str = "",
                                tools_prefix: str = "") -> tuple[list[dict], int]:
    """Find files in shared/ that import from tools/ (backwards coupling).

    Args:
        shared_prefix: absolute path prefix for shared code. Required.
        tools_prefix: absolute path prefix for tool code. Required.

    Returns:
        (entries, total_cross_boundary_edges_checked)
    """
    total_edges = 0
    entries = []
    for filepath, entry in graph.items():
        if not filepath.startswith(shared_prefix):
            continue
        for target in entry["imports"]:
            if target.startswith(tools_prefix):
                total_edges += 1
                remainder = target[len(tools_prefix):]
                tool = remainder.split("/")[0] if "/" in remainder else remainder
                entries.append({
                    "file": filepath,
                    "target": rel(target),
                    "tool": tool,
                    "direction": "shared→tools",
                })
            elif target.startswith(shared_prefix):
                total_edges += 1  # Count shared→shared edges too for the universe
    return sorted(entries, key=lambda e: (e["file"], e["target"])), total_edges


def detect_boundary_candidates(path: Path, graph: dict,
                                shared_prefix: str = "",
                                tools_prefix: str = "",
                                skip_basenames: set[str] | None = None) -> tuple[list[dict], int]:
    """Find shared/ files whose importers ALL come from a single tool.

    Args:
        shared_prefix: absolute path prefix for shared code. Required.
        tools_prefix: absolute path prefix for tool code. Required.

    Returns:
        (entries, total_shared_files_checked)
    """
    total_shared = 0
    entries = []
    skip_basenames = skip_basenames or set()
    for filepath, entry in graph.items():
        if not filepath.startswith(shared_prefix):
            continue
        total_shared += 1
        basename = Path(filepath).name
        if basename in skip_basenames:
            continue
        if f"{shared_prefix}components/ui/" in filepath:
            continue
        if entry["importer_count"] == 0:
            continue

        tool_areas = set()
        has_non_tool_importer = False
        for imp in entry["importers"]:
            if imp.startswith(tools_prefix):
                remainder = imp[len(tools_prefix):]
                tool = remainder.split("/")[0]
                tool_areas.add(tool)
            else:
                has_non_tool_importer = True

        if len(tool_areas) == 1 and not has_non_tool_importer:
            try:
                loc = len(Path(filepath).read_text().splitlines())
            except (OSError, UnicodeDecodeError):
                loc = 0
            entries.append({
                "file": filepath,
                "sole_tool": f"src/tools/{list(tool_areas)[0]}",
                "importer_count": entry["importer_count"],
                "loc": loc,
            })

    return sorted(entries, key=lambda e: -e["loc"]), total_shared


def detect_cross_tool_imports(path: Path, graph: dict,
                               tools_prefix: str = "") -> tuple[list[dict], int]:
    """Find tools/A files that import from tools/B (cross-tool coupling).

    Args:
        tools_prefix: absolute path prefix for tool code. Required.

    Returns:
        (entries, total_cross_tool_edges)
    """
    total_edges = 0
    entries = []
    for filepath, entry in graph.items():
        if not filepath.startswith(tools_prefix):
            continue
        remainder = filepath[len(tools_prefix):]
        if "/" not in remainder:
            continue
        source_tool = remainder.split("/")[0]
        for target in entry["imports"]:
            if not target.startswith(tools_prefix):
                continue
            target_tool = target[len(tools_prefix):].split("/")[0]
            if source_tool != target_tool:
                total_edges += 1
                entries.append({
                    "file": filepath,
                    "target": rel(target),
                    "source_tool": source_tool,
                    "target_tool": target_tool,
                    "direction": "tools→tools",
                })
            else:
                total_edges += 1  # Same-tool edge (passes check)
    return sorted(entries, key=lambda e: (e["source_tool"], e["file"])), total_edges
