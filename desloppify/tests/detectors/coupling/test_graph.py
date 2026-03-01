"""Tests for desloppify.engine.detectors.graph — iterative Tarjan's SCC cycle detection."""

from desloppify.engine.detectors.graph import detect_cycles


def _make_graph(edges: dict[str, set[str]]) -> dict:
    """Build a graph dict from {node: {targets}} mapping.

    Constructs the full graph structure with imports/importers/counts
    that detect_cycles expects.
    """
    all_nodes = set(edges.keys())
    for targets in edges.values():
        all_nodes.update(targets)

    graph: dict[str, dict] = {}
    for node in all_nodes:
        graph[node] = {
            "imports": edges.get(node, set()),
            "importers": set(),
            "import_count": 0,
            "importer_count": 0,
        }

    # Populate importers
    for node, targets in edges.items():
        for target in targets:
            if target in graph:
                graph[target]["importers"].add(node)

    # Compute counts
    for v in graph.values():
        v["import_count"] = len(v["imports"])
        v["importer_count"] = len(v["importers"])

    return graph


class TestDetectCycles:
    def test_empty_graph(self):
        entries, total = detect_cycles({})
        assert entries == []
        assert total == 0

    def test_acyclic_graph(self):
        graph = _make_graph(
            {
                "a.py": {"b.py"},
                "b.py": {"c.py"},
                "c.py": set(),
            }
        )
        entries, total = detect_cycles(graph)
        assert entries == []
        assert total == 3

    def test_simple_two_node_cycle(self):
        graph = _make_graph(
            {
                "a.py": {"b.py"},
                "b.py": {"a.py"},
            }
        )
        entries, total = detect_cycles(graph)
        assert len(entries) == 1
        assert sorted(entries[0]["files"]) == ["a.py", "b.py"]
        assert entries[0]["length"] == 2
        assert total == 2

    def test_three_node_cycle(self):
        graph = _make_graph(
            {
                "a.py": {"b.py"},
                "b.py": {"c.py"},
                "c.py": {"a.py"},
            }
        )
        entries, total = detect_cycles(graph)
        assert len(entries) == 1
        assert sorted(entries[0]["files"]) == ["a.py", "b.py", "c.py"]
        assert entries[0]["length"] == 3
        assert total == 3

    def test_multiple_separate_cycles(self):
        graph = _make_graph(
            {
                "a.py": {"b.py"},
                "b.py": {"a.py"},
                "c.py": {"d.py"},
                "d.py": {"c.py"},
                "e.py": set(),
            }
        )
        entries, total = detect_cycles(graph)
        assert len(entries) == 2
        assert total == 5
        # Cycles sorted by length descending (both length 2 here)
        cycle_sets = [set(e["files"]) for e in entries]
        assert {"a.py", "b.py"} in cycle_sets
        assert {"c.py", "d.py"} in cycle_sets

    def test_self_loop_not_detected(self):
        """Self-loops produce a component of size 1, which is filtered out by Tarjan's.

        The algorithm only reports SCCs with len > 1.
        """
        graph = _make_graph(
            {
                "a.py": {"a.py"},
            }
        )
        entries, total = detect_cycles(graph)
        # Self-loop creates a component of size 1 — Tarjan's only reports size >= 2
        assert entries == []
        assert total == 1

    def test_mixed_cyclic_and_acyclic(self):
        graph = _make_graph(
            {
                "a.py": {"b.py"},
                "b.py": {"a.py"},
                "c.py": {"a.py"},
                "d.py": {"c.py"},
            }
        )
        entries, total = detect_cycles(graph)
        assert len(entries) == 1
        assert sorted(entries[0]["files"]) == ["a.py", "b.py"]
        assert total == 4

    def test_deferred_imports_skipped_by_default(self):
        """Deferred imports (inside functions) should be excluded from cycle detection."""
        graph = _make_graph(
            {
                "a.py": {"b.py"},
                "b.py": {"a.py"},
            }
        )
        # Mark b.py -> a.py as deferred
        graph["b.py"]["deferred_imports"] = {"a.py"}

        entries, total = detect_cycles(graph, skip_deferred=True)
        assert entries == []

    def test_deferred_imports_included_when_disabled(self):
        """When skip_deferred=False, deferred imports are included."""
        graph = _make_graph(
            {
                "a.py": {"b.py"},
                "b.py": {"a.py"},
            }
        )
        graph["b.py"]["deferred_imports"] = {"a.py"}

        entries, total = detect_cycles(graph, skip_deferred=False)
        assert len(entries) == 1
        assert sorted(entries[0]["files"]) == ["a.py", "b.py"]

    def test_edges_only_within_graph(self):
        """Edges pointing to nodes not in the graph should be ignored."""
        graph = _make_graph(
            {
                "a.py": {"b.py", "external.py"},
                "b.py": {"a.py"},
            }
        )
        # Remove external.py from graph to simulate it not being a tracked file
        del graph["external.py"]

        entries, total = detect_cycles(graph)
        assert len(entries) == 1
        assert total == 2

    def test_large_cycle(self):
        """A cycle of many nodes should be detected as one SCC."""
        nodes = [f"mod_{i}.py" for i in range(10)]
        edges = {nodes[i]: {nodes[(i + 1) % 10]} for i in range(10)}
        graph = _make_graph(edges)

        entries, total = detect_cycles(graph)
        assert len(entries) == 1
        assert entries[0]["length"] == 10
        assert total == 10

    def test_return_format(self):
        graph = _make_graph(
            {
                "a.py": {"b.py"},
                "b.py": {"a.py"},
            }
        )
        entries, total = detect_cycles(graph)
        assert isinstance(entries, list)
        assert isinstance(total, int)
        entry = entries[0]
        assert "files" in entry
        assert "length" in entry
        assert isinstance(entry["files"], list)
        assert isinstance(entry["length"], int)
