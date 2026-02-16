"""Language-agnostic dependency graph algorithms.

The graph structure is: {resolved_path: {"imports": set, "importers": set, "import_count": int, "importer_count": int}}
Language-specific modules build the graph; this module provides shared algorithms.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import rel, resolve_path, PROJECT_ROOT


def finalize_graph(graph: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Add counts to a raw graph (imports/importers sets only).

    Also filters out nodes matching global --exclude patterns, and removes
    references to excluded files from all import/importer sets.
    """
    from .. import utils as _utils_mod
    _extra_exclusions = _utils_mod._extra_exclusions

    # Remove excluded nodes and clean up references
    # Use relative paths for exclusion matching to avoid false positives
    # when an exclude pattern (e.g. "Wan2GP") matches the project root
    # directory name (e.g. "Headless-Wan2GP").
    if _extra_exclusions:
        excluded_keys = set()
        for k in graph:
            try:
                rel_k = str(Path(k).relative_to(PROJECT_ROOT))
            except ValueError:
                rel_k = k
            if any(_utils_mod.matches_exclusion(rel_k, ex) for ex in _extra_exclusions):
                excluded_keys.add(k)
        for k in excluded_keys:
            del graph[k]
        # Clean import/importer sets of references to removed nodes
        for v in graph.values():
            v["imports"] = v["imports"] - excluded_keys
            v["importers"] = v["importers"] - excluded_keys
            if "deferred_imports" in v:
                v["deferred_imports"] = v["deferred_imports"] - excluded_keys

    for v in graph.values():
        v["import_count"] = len(v["imports"])
        v["importer_count"] = len(v["importers"])
    return graph


def detect_cycles(graph: dict[str, dict[str, Any]], *, skip_deferred: bool = True) -> tuple[list[dict[str, Any]], int]:
    """Find import cycles using Tarjan's strongly connected components (iterative).

    When skip_deferred=True (default), deferred imports (inside functions) are
    excluded from cycle detection — they can't cause circular import errors.

    Returns (entries, total_files). Each entry: {"files": [abs_paths], "length": int}
    """
    index_counter = 0
    scc_stack: list[str] = []
    lowlinks: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    def _get_edges(v: str) -> list[str]:
        node = graph.get(v, {})
        imports = node.get("imports", set())
        if skip_deferred:
            imports = imports - node.get("deferred_imports", set())
        return [w for w in imports if w in graph]

    for root in graph:
        if root in index:
            continue

        # Iterative Tarjan's using an explicit call stack.
        # Each frame is (node, edge_iterator, is_root_call).
        # When we first visit a node we assign index/lowlink and push to SCC stack.
        # When we finish iterating edges we check for SCC root.
        call_stack: list[tuple[str, list[str], int]] = []
        index[root] = lowlinks[root] = index_counter
        index_counter += 1
        scc_stack.append(root)
        on_stack[root] = True
        edges = _get_edges(root)
        call_stack.append((root, edges, 0))

        while call_stack:
            v, edges, ei = call_stack[-1]

            if ei < len(edges):
                w = edges[ei]
                call_stack[-1] = (v, edges, ei + 1)

                if w not in index:
                    # "Recurse" into w
                    index[w] = lowlinks[w] = index_counter
                    index_counter += 1
                    scc_stack.append(w)
                    on_stack[w] = True
                    w_edges = _get_edges(w)
                    call_stack.append((w, w_edges, 0))
                elif on_stack.get(w, False):
                    lowlinks[v] = min(lowlinks[v], index[w])
            else:
                # Done with all edges for v — check for SCC root
                if lowlinks[v] == index[v]:
                    component: list[str] = []
                    while True:
                        w = scc_stack.pop()
                        on_stack[w] = False
                        component.append(w)
                        if w == v:
                            break
                    if len(component) > 1:
                        component.sort()
                        sccs.append(component)

                call_stack.pop()
                # Propagate lowlink to parent
                if call_stack:
                    parent = call_stack[-1][0]
                    lowlinks[parent] = min(lowlinks[parent], lowlinks[v])

    return [{"files": scc, "length": len(scc)} for scc in sorted(sccs, key=lambda s: -len(s))], len(graph)


def get_coupling_score(filepath: str, graph: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Get coupling metrics for a file."""
    resolved = resolve_path(filepath)
    entry = graph.get(resolved, {"imports": set(), "importers": set(), "import_count": 0, "importer_count": 0})
    fan_in = entry["importer_count"]
    fan_out = entry["import_count"]
    instability = fan_out / (fan_in + fan_out) if (fan_in + fan_out) > 0 else 0
    return {
        "fan_in": fan_in,
        "fan_out": fan_out,
        "instability": round(instability, 2),
        "importers": [rel(p) for p in sorted(entry["importers"])],
        "imports": [rel(p) for p in sorted(entry["imports"])],
    }
