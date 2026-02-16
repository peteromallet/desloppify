"""Coupling analysis: boundary violations and boundary candidates.

These detect architectural violations in codebases with shared/tools structure.
The algorithms work on any dep graph — the boundary definitions (what prefixes
constitute "shared" vs "tools") are provided by the caller.
"""

from pathlib import Path

from ..utils import rel


def _norm_path(path: str) -> str:
    """Normalize path separators for cross-platform prefix matching."""
    return path.replace("\\", "/")


def _norm_prefix(prefix: str) -> str:
    """Normalize a directory prefix and ensure trailing slash."""
    p = _norm_path(prefix)
    return p if p.endswith("/") else p + "/"


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
    shared_prefix_norm = _norm_prefix(shared_prefix)
    tools_prefix_norm = _norm_prefix(tools_prefix)

    total_edges = 0
    entries = []
    for filepath, entry in graph.items():
        filepath_norm = _norm_path(filepath)
        if not filepath_norm.startswith(shared_prefix_norm):
            continue
        for target in entry["imports"]:
            target_norm = _norm_path(target)
            if target_norm.startswith(tools_prefix_norm):
                total_edges += 1
                remainder = target_norm[len(tools_prefix_norm):]
                tool = remainder.split("/")[0] if "/" in remainder else remainder
                entries.append({
                    "file": filepath,
                    "target": rel(target),
                    "tool": tool,
                    "direction": "shared→tools",
                })
            elif target_norm.startswith(shared_prefix_norm):
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
    shared_prefix_norm = _norm_prefix(shared_prefix)
    tools_prefix_norm = _norm_prefix(tools_prefix)
    ui_prefix_norm = shared_prefix_norm + "components/ui/"

    total_shared = 0
    entries = []
    skip_basenames = skip_basenames or set()
    for filepath, entry in graph.items():
        filepath_norm = _norm_path(filepath)
        if not filepath_norm.startswith(shared_prefix_norm):
            continue
        total_shared += 1
        basename = Path(filepath).name
        if basename in skip_basenames:
            continue
        if ui_prefix_norm in filepath_norm:
            continue
        if entry["importer_count"] == 0:
            continue

        tool_areas = set()
        has_non_tool_importer = False
        for imp in entry["importers"]:
            imp_norm = _norm_path(imp)
            if imp_norm.startswith(tools_prefix_norm):
                remainder = imp_norm[len(tools_prefix_norm):]
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
    tools_prefix_norm = _norm_prefix(tools_prefix)

    total_edges = 0
    entries = []
    for filepath, entry in graph.items():
        filepath_norm = _norm_path(filepath)
        if not filepath_norm.startswith(tools_prefix_norm):
            continue
        remainder = filepath_norm[len(tools_prefix_norm):]
        if "/" not in remainder:
            continue
        source_tool = remainder.split("/")[0]
        for target in entry["imports"]:
            target_norm = _norm_path(target)
            if not target_norm.startswith(tools_prefix_norm):
                continue
            target_tool = target_norm[len(tools_prefix_norm):].split("/")[0]
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
