"""Direct tests for split TypeScript phase/fixer helper modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.languages.typescript.fixers.logs_cleanup as logs_cleanup_mod
import desloppify.languages.typescript.fixers.logs_context as logs_context_mod
import desloppify.languages.typescript.phases_basic as phases_basic_mod
import desloppify.languages.typescript.phases_config as phases_config_mod
import desloppify.languages.typescript.phases_coupling as phases_coupling_mod
import desloppify.languages.typescript.phases_smells as phases_smells_mod
import desloppify.languages.typescript.phases_structural as phases_structural_mod


def test_logs_cleanup_helpers_cover_comment_marking_dead_vars_and_block_cleanup() -> None:
    lines = [
        "// DEBUG: remove with log\n",
        "// keep this note\n",
        "console.log(token)\n",
    ]
    to_remove = {2}
    logs_cleanup_mod.mark_orphaned_comments(lines, 2, to_remove)
    assert 0 in to_remove
    assert 1 not in to_remove

    dead_lines = logs_cleanup_mod.find_dead_log_variables(
        [
            "const dbg = token;\n",
            "console.log(dbg);\n",
            "const keep = token;\n",
            "doSomething(keep);\n",
        ],
        removed_indices={1},
    )
    assert dead_lines == {0}

    cleaned = logs_cleanup_mod.remove_empty_blocks(
        [
            "if (ok) {}\n",
            "promise.then(() => {})\n",
            "React.useEffect(() => {\n",
            "});\n",
            "keep();\n",
            "\n",
            "\n",
        ]
    )
    assert "keep();\n" in cleaned
    assert cleaned.count("\n") <= 1


def test_logs_context_helpers_cover_inline_and_previous_line_detection() -> None:
    assert logs_context_mod._normalize_wrapper_name("'Logger'") == "logger"
    assert logs_context_mod._is_logger_wrapper_name("Warn") is True

    inline = "const logger = () => console.log('x')"
    name = logs_context_mod._line_logger_wrapper_name(inline, logs_context_mod._INLINE_WRAPPER_PATTERNS)
    assert name == "logger"

    lines = ["", "const debug = () =>", "  console.log('x')"]
    assert logs_context_mod._previous_non_empty_line(lines, 2) == "const debug = () =>"
    assert logs_context_mod.is_logger_wrapper_context(lines, 2) is True
    assert logs_context_mod.is_logger_wrapper_context(["doWork()"], 0) is False


def test_phase_config_helpers_and_constants() -> None:
    destructure = phases_config_mod._compute_ts_destructure_props(
        "const {a,b,c,d,e,f,g,h,i} = props",
        [],
    )
    assert destructure is not None
    assert destructure[0] >= 9

    inline_types = phases_config_mod._compute_ts_inline_types(
        "\n".join(
            [
                "type A = {}",
                "interface B {}",
                "type C = {}",
                "interface D {}",
            ]
        ),
        [],
    )
    assert inline_types is not None
    assert "inline types" in inline_types[1]

    assert phases_config_mod.TS_COMPLEXITY_SIGNALS
    assert phases_config_mod.TS_GOD_RULES
    assert "index.ts" in phases_config_mod.TS_SKIP_NAMES


def test_phases_basic_cover_logs_unused_exports_and_deprecated(monkeypatch) -> None:
    lang = SimpleNamespace(zone_map=None)

    monkeypatch.setattr(
        phases_basic_mod.logs_detector_mod,
        "detect_logs_result",
        lambda _path: SimpleNamespace(
            entries=[
                {"file": "src/a.ts", "tag": "DEBUG", "line": 1},
                {"file": "src/a.ts", "tag": "DEBUG", "line": 2},
                {"file": "src/b.ts", "tag": "INFO", "line": 4},
            ],
            population_size=5,
        ),
    )
    issues, potentials = phases_basic_mod.phase_logs(Path("."), lang)
    assert len(issues) == 2
    assert potentials == {"logs": 5}

    monkeypatch.setattr(phases_basic_mod.unused_detector_mod, "detect_unused", lambda _path: ([{"file": "src/a.ts"}], 7))
    monkeypatch.setattr(phases_basic_mod, "make_unused_issues", lambda entries, _log: [{"entries": entries}])
    issues, potentials = phases_basic_mod.phase_unused(Path("."), lang)
    assert len(issues) == 1
    assert potentials == {"unused": 7}

    monkeypatch.setattr(
        phases_basic_mod.exports_detector_mod,
        "detect_dead_exports",
        lambda _path: (
            [{"file": "src/a.ts", "name": "deadExport", "line": 3, "kind": "function"}],
            4,
        ),
    )
    issues, potentials = phases_basic_mod.phase_exports(Path("."), lang)
    assert len(issues) == 1
    assert potentials == {"exports": 4}

    monkeypatch.setattr(
        phases_basic_mod.deprecated_detector_mod,
        "detect_deprecated_result",
        lambda _path: SimpleNamespace(
            entries=[
                {"kind": "property", "file": "src/a.ts", "symbol": "x", "importers": 0, "line": 1},
                {"kind": "function", "file": "src/a.ts", "symbol": "oldA", "importers": 0, "line": 2},
                {"kind": "function", "file": "src/b.ts", "symbol": "oldB", "importers": 2, "line": 5},
            ],
            population_size=6,
        ),
    )
    issues, potentials = phases_basic_mod.phase_deprecated(Path("."), lang)
    assert len(issues) == 2
    assert {issue["tier"] for issue in issues} == {1, 3}
    assert potentials == {"deprecated": 6}


def test_phase_smells_aggregates_smells_and_react_issues(monkeypatch) -> None:
    lang = SimpleNamespace(zone_map=None)

    monkeypatch.setattr(phases_smells_mod.smells_detector_mod, "detect_smells", lambda _path: ([{"id": "x"}], 9))
    monkeypatch.setattr(phases_smells_mod, "make_smell_issues", lambda entries, _log: [{"detector": "smells", "entries": entries}])
    monkeypatch.setattr(
        phases_smells_mod.react_state_sync_mod,
        "detect_state_sync",
        lambda _path: ([{"file": "src/a.tsx", "setters": ["setA"], "line": 7}], 4),
    )
    monkeypatch.setattr(
        phases_smells_mod.react_context_mod,
        "detect_context_nesting",
        lambda _path: ([{"file": "src/a.tsx", "depth": 5, "providers": ["P1", "P2"]}], 2),
    )
    monkeypatch.setattr(
        phases_smells_mod.react_hook_bloat_mod,
        "detect_hook_return_bloat",
        lambda _path: ([{"file": "src/a.tsx", "hook": "useFoo", "field_count": 8, "line": 10}], 1),
    )
    monkeypatch.setattr(
        phases_smells_mod.react_hook_bloat_mod,
        "detect_boolean_state_explosion",
        lambda _path: (
            [
                {
                    "file": "src/a.tsx",
                    "prefix": "is",
                    "count": 4,
                    "setters": ["setIsOpen"],
                    "states": ["isOpen"],
                    "line": 12,
                }
            ],
            1,
        ),
    )

    issues, potentials = phases_smells_mod.phase_smells(Path("."), lang)
    assert len(issues) >= 5
    assert potentials == {"smells": 9, "react": 4}


def test_phase_structural_and_subdetectors_cover_threshold_and_passthrough_paths(monkeypatch) -> None:
    lang = SimpleNamespace(
        file_finder=lambda _path: ["src/a.ts"],
        large_threshold=200,
        complexity_threshold=15,
        props_threshold=12,
        complexity_map={},
        zone_map=None,
    )

    monkeypatch.setattr(phases_structural_mod.large_detector_mod, "detect_large_files", lambda _path, **_kwargs: ([{"file": "src/large.ts", "loc": 350}], 8))
    monkeypatch.setattr(phases_structural_mod.complexity_detector_mod, "detect_complexity", lambda _path, **_kwargs: ([{"file": "src/complex.ts", "score": 22, "signals": ["TODOs"]}], 1))
    monkeypatch.setattr(
        phases_structural_mod.gods_detector_mod,
        "detect_gods",
        lambda _components, _rules, min_reasons=2: (
            [{"file": "src/view.tsx", "detail": {"hook_total": 12}, "reasons": ["hooks", "states"]}],
            min_reasons,
        ),
    )
    monkeypatch.setattr(
        phases_structural_mod.concerns_detector_mod,
        "detect_mixed_concerns",
        lambda _path: ([{"file": "src/service.ts", "concerns": ["io", "db", "auth"]}], 1),
    )
    monkeypatch.setattr(
        phases_structural_mod,
        "merge_structural_signals",
        lambda structural, _log: [{"detector": "structural", "files": sorted(structural.keys())}],
    )
    monkeypatch.setattr(
        phases_structural_mod.flat_dirs_detector_mod,
        "detect_flat_dirs",
        lambda _path, **_kwargs: ([{"directory": "src", "file_count": 30, "child_dir_count": 1, "combined_score": 31}], 3),
    )
    monkeypatch.setattr(
        phases_structural_mod.props_detector_mod,
        "detect_prop_interface_bloat",
        lambda _path, threshold: (
            [
                {"file": "src/view.tsx", "interface": "HugeProps", "prop_count": 55, "line": 4, "kind": "props"},
                {"file": "src/view.tsx", "interface": "SmallProps", "prop_count": 18, "line": 30, "kind": "props"},
            ],
            threshold,
        ),
    )
    monkeypatch.setattr(
        phases_structural_mod,
        "detect_passthrough_components",
        lambda _path: [
            {
                "file": "src/view.tsx",
                "component": "Wrapper",
                "tier": 3,
                "confidence": "medium",
                "passthrough": 8,
                "total_props": 10,
                "ratio": 0.8,
                "line": 20,
                "passthrough_props": ["a"],
                "direct_props": ["b"],
            }
        ],
    )

    issues, potentials = phases_structural_mod.phase_structural(Path("."), lang)
    assert len(issues) >= 4
    assert lang.complexity_map["src/complex.ts"] == 22
    assert potentials == {"structural": 8, "flat_dirs": 3, "props": 12}


def test_phases_coupling_helpers_and_orchestration(monkeypatch) -> None:
    lang = SimpleNamespace(
        zone_map=None,
        dep_graph=None,
        barrel_names={"index.ts"},
        get_area=lambda path: "shared" if "shared" in str(path) else "tool",
        extensions=[".ts", ".tsx"],
        entry_patterns=["src/main.ts"],
        file_finder=lambda _path: ["src/a.ts"],
    )
    graph = {
        "src/shared/a.ts": {
            "imports": {"src/tools/t.ts"},
            "importers": set(),
            "import_count": 1,
            "importer_count": 0,
        },
        "src/tools/t.ts": {
            "imports": set(),
            "importers": {"src/shared/a.ts"},
            "import_count": 0,
            "importer_count": 1,
        },
    }

    monkeypatch.setattr(
        phases_coupling_mod.single_use_detector_mod,
        "detect_single_use_abstractions",
        lambda _path, _graph, **_kwargs: (
            [{"file": "src/shared/dedupe.ts", "loc": 20, "sole_importer": "src/tools/t.ts"}],
            4,
        ),
    )
    monkeypatch.setattr(phases_coupling_mod, "filter_entries", lambda _zones, entries, _detector, file_key="file": entries)
    monkeypatch.setattr(phases_coupling_mod, "make_single_use_issues", lambda entries, _get_area, **_kwargs: [{"kind": "single", "entries": entries}])

    monkeypatch.setattr(
        phases_coupling_mod.coupling_detector_mod,
        "detect_coupling_violations",
        lambda *_args, **_kwargs: (
            [{"file": "src/shared/a.ts", "target": "src/tools/t.ts", "tool": "tool", "direction": "shared->tools"}],
            SimpleNamespace(eligible_edges=5),
        ),
    )
    monkeypatch.setattr(
        phases_coupling_mod.coupling_detector_mod,
        "detect_cross_tool_imports",
        lambda *_args, **_kwargs: (
            [{"file": "src/tools/a.ts", "target": "src/tools/b.ts", "source_tool": "a", "target_tool": "b", "direction": "a->b"}],
            SimpleNamespace(eligible_edges=6),
        ),
    )
    monkeypatch.setattr(
        phases_coupling_mod.coupling_detector_mod,
        "detect_boundary_candidates",
        lambda *_args, **_kwargs: (
            [
                {
                    "file": "src/shared/dedupe.ts",
                    "sole_tool": "tool",
                    "importer_count": 1,
                    "loc": 20,
                },
                {
                    "file": "src/shared/keep.ts",
                    "sole_tool": "tool",
                    "importer_count": 2,
                    "loc": 80,
                },
            ],
            3,
        ),
    )
    monkeypatch.setattr(phases_coupling_mod.graph_detector_mod, "detect_cycles", lambda _graph: ([{"length": 2, "files": ["src/shared/a.ts", "src/tools/t.ts"]}], 0))
    monkeypatch.setattr(
        phases_coupling_mod.orphaned_detector_mod,
        "detect_orphaned_files",
        lambda *_args, **_kwargs: ([{"file": "src/orphan.ts", "loc": 11}], 10),
    )
    monkeypatch.setattr(phases_coupling_mod, "make_cycle_issues", lambda entries, _log: [{"kind": "cycle", "entries": entries}])
    monkeypatch.setattr(phases_coupling_mod, "make_orphaned_issues", lambda entries, _log: [{"kind": "orphaned", "entries": entries}])

    monkeypatch.setattr(phases_coupling_mod.facade_detector_mod, "detect_reexport_facades", lambda _graph: ([{"file": "src/shared/facade.ts", "loc": 5}], 1))
    monkeypatch.setattr(phases_coupling_mod, "make_facade_issues", lambda entries, _log: [{"kind": "facade", "entries": entries}])

    monkeypatch.setattr(
        phases_coupling_mod.patterns_detector_mod,
        "detect_pattern_anomalies_result",
        lambda _path: SimpleNamespace(
            entries=[{"area": "shared", "family": "factory", "patterns_used": ["x", "y"], "pattern_count": 2, "review": "mixed patterns", "confidence": "low"}],
            population_size=3,
        ),
    )
    monkeypatch.setattr(
        phases_coupling_mod.naming_detector_mod,
        "detect_naming_inconsistencies",
        lambda _path, **_kwargs: (
            [{"directory": "src/shared", "minority": "snake", "minority_count": 1, "majority": "kebab", "majority_count": 3, "total_files": 4, "outliers": ["a_b.ts"]}],
            2,
        ),
    )

    monkeypatch.setattr(phases_coupling_mod.deps_detector_mod, "build_dep_graph", lambda _path: graph)
    monkeypatch.setattr(phases_coupling_mod, "get_src_path", lambda: "src")

    boundary_issues, total_shared = phases_coupling_mod.make_boundary_issues(
        [{"file": "src/shared/dedupe.ts", "loc": 20, "sole_importer": "src/tools/t.ts"}],
        Path("."),
        graph,
        lang,
        "src/shared/",
        "src/tools/",
    )
    assert len(boundary_issues) == 1
    assert total_shared == 3

    issues, potentials = phases_coupling_mod.phase_coupling(Path("."), lang)
    assert len(issues) >= 7
    assert lang.dep_graph == graph
    assert potentials == {
        "single_use": 4,
        "coupling": 11,
        "cycles": 10,
        "orphaned": 10,
        "patterns": 3,
        "naming": 2,
        "facade": 10,
    }
