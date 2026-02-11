"""Language-agnostic dependency graph algorithms.

The graph structure is: {resolved_path: {"imports": set, "importers": set, "import_count": int, "importer_count": int}}
Language-specific modules build the graph; this module provides shared algorithms.
"""

from ..utils import rel, resolve_path


def finalize_graph(graph: dict) -> dict:
    """Add counts to a raw graph (imports/importers sets only)."""
    for v in graph.values():
        v["import_count"] = len(v["imports"])
        v["importer_count"] = len(v["importers"])
    return graph


def detect_cycles(graph: dict, *, skip_deferred: bool = True) -> tuple[list[dict], int]:
    """Find import cycles using Tarjan's strongly connected components.

    When skip_deferred=True (default), deferred imports (inside functions) are
    excluded from cycle detection — they can't cause circular import errors.

    Returns (entries, total_edges). Each entry: {"files": [abs_paths], "length": int}
    """
    index_counter = [0]
    stack: list[str] = []
    lowlinks: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    def _get_edges(v: str) -> set:
        node = graph.get(v, {})
        imports = node.get("imports", set())
        if skip_deferred:
            imports = imports - node.get("deferred_imports", set())
        return imports

    def strongconnect(v: str):
        index[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in _get_edges(v):
            if w not in graph:
                continue  # external dep, not in graph
            if w not in index:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack.get(w, False):
                lowlinks[v] = min(lowlinks[v], index[w])

        if lowlinks[v] == index[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                component.sort()
                sccs.append(component)

    for v in graph:
        if v not in index:
            strongconnect(v)

    total_edges = sum(len(_get_edges(v)) for v in graph)
    return [{"files": scc, "length": len(scc)} for scc in sorted(sccs, key=lambda s: -len(s))], total_edges


def get_coupling_score(filepath: str, graph: dict) -> dict:
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
