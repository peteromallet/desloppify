"""Direct tests for shared framework review/structural split helper modules."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from types import SimpleNamespace

import desloppify.languages._framework.base.shared_phases_review as review_mod
import desloppify.languages._framework.base.shared_phases_structural as structural_mod
import desloppify.languages._framework.generic_support.structural as generic_structural_mod
from desloppify.engine.policy.zones import Zone
from desloppify.languages._framework.base.types import LangSecurityResult


def test_phase_dupes_filters_non_production_functions(monkeypatch) -> None:
    functions = [
        SimpleNamespace(file="src/a.py", name="a"),
        SimpleNamespace(file="tests/a_test.py", name="a_test"),
    ]
    lang = SimpleNamespace(
        extract_functions=lambda _path: functions,
        zone_map=SimpleNamespace(
            get=lambda file_path: Zone.TEST if "tests/" in str(file_path) else Zone.PRODUCTION
        ),
        review_cache={},
    )

    captured: dict[str, int] = {}

    def _fake_detect(filtered, **kwargs):
        captured["count"] = len(filtered)
        cache_payload = kwargs.get("cache")
        assert isinstance(cache_payload, dict)
        captured["cache_size"] = len(cache_payload)
        return [{"id": "pair"}], len(filtered)

    monkeypatch.setattr(review_mod, "detect_duplicates", _fake_detect)
    monkeypatch.setattr(review_mod, "make_dupe_issues", lambda entries, _log: [{"entries": entries}])

    issues, potentials = review_mod.phase_dupes(Path("."), lang)

    assert len(issues) == 1
    assert captured["count"] == 1
    assert "detectors" in lang.review_cache
    assert "dupes" in lang.review_cache["detectors"]
    assert potentials == {"dupes": 1}


def test_phase_boilerplate_duplication_handles_none_and_entries(monkeypatch) -> None:
    lang = SimpleNamespace(zone_map=None)
    monkeypatch.setattr(review_mod, "detect_with_jscpd", lambda _path: None)
    issues, potentials = review_mod.phase_boilerplate_duplication(Path("."), lang)
    assert issues == []
    assert potentials == {}

    entries = [
        {
            "id": "cluster-1",
            "distinct_files": 2,
            "window_size": 8,
            "sample": "x = y",
            "locations": [
                {"file": "src/a.py", "line": 10},
                {"file": "src/b.py", "line": 20},
            ],
        }
    ]
    monkeypatch.setattr(review_mod, "detect_with_jscpd", lambda _path: entries)
    monkeypatch.setattr(review_mod, "_filter_boilerplate_entries_by_zone", lambda items, _zone: items)

    issues, potentials = review_mod.phase_boilerplate_duplication(Path("."), lang)

    assert len(issues) == 1
    assert issues[0]["detector"] == "boilerplate_duplication"
    assert potentials == {"boilerplate_duplication": 2}


def test_phase_boilerplate_duplication_reuses_cached_entries(monkeypatch, tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('a')\n")

    calls = {"count": 0}
    entries = [
        {
            "id": "cluster-1",
            "distinct_files": 2,
            "window_size": 6,
            "sample": ["x = 1"],
            "locations": [
                {"file": "src/a.py", "line": 1},
                {"file": "src/b.py", "line": 2},
            ],
        }
    ]
    lang = SimpleNamespace(
        zone_map=None,
        name="python",
        review_cache={},
        file_finder=lambda _path: ["src/a.py"],
    )

    def _fake_detect(_path):
        calls["count"] += 1
        return entries

    monkeypatch.setattr(review_mod, "detect_with_jscpd", _fake_detect)
    monkeypatch.setattr(review_mod, "_filter_boilerplate_entries_by_zone", lambda items, _zone: items)

    first_issues, first_potentials = review_mod.phase_boilerplate_duplication(tmp_path, lang)
    second_issues, second_potentials = review_mod.phase_boilerplate_duplication(tmp_path, lang)

    assert calls["count"] == 1
    assert len(first_issues) == 1
    assert len(second_issues) == 1
    assert first_potentials == {"boilerplate_duplication": 2}
    assert second_potentials == {"boilerplate_duplication": 2}


def test_phase_boilerplate_duplication_uses_prefetched_result(monkeypatch, tmp_path) -> None:
    class _ImmediateExecutor:
        def submit(self, fn, *args, **kwargs):
            future: concurrent.futures.Future = concurrent.futures.Future()
            future.set_result(fn(*args, **kwargs))
            return future

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('a')\n")
    calls = {"count": 0}
    entries = [
        {
            "id": "cluster-1",
            "distinct_files": 2,
            "window_size": 6,
            "sample": ["x = 1"],
            "locations": [
                {"file": "src/a.py", "line": 1},
                {"file": "src/b.py", "line": 2},
            ],
        }
    ]
    lang = SimpleNamespace(
        zone_map=None,
        name="python",
        review_cache={},
        file_finder=lambda _path: ["src/a.py"],
    )

    monkeypatch.setattr(review_mod, "_PREFETCH_EXECUTOR", _ImmediateExecutor())
    monkeypatch.setattr(
        review_mod,
        "detect_with_jscpd",
        lambda _path: (calls.__setitem__("count", calls["count"] + 1), entries)[1],
    )
    monkeypatch.setattr(review_mod, "_filter_boilerplate_entries_by_zone", lambda items, _zone: items)

    review_mod.prewarm_review_phase_detectors(
        tmp_path,
        lang,
        [SimpleNamespace(label="Boilerplate duplication", run=review_mod.phase_boilerplate_duplication)],
    )
    issues, potentials = review_mod.phase_boilerplate_duplication(tmp_path, lang)

    assert calls["count"] == 1
    assert len(issues) == 1
    assert potentials == {"boilerplate_duplication": 2}


def test_phase_security_records_default_coverage_when_missing(monkeypatch) -> None:
    lang = SimpleNamespace(
        zone_map=None,
        file_finder=lambda _path: ["src/a.py", "src/b.py"],
        name="python",
        detector_coverage={},
        detect_lang_security_detailed=lambda _files, _zones: SimpleNamespace(
            entries=[
                {
                    "file": "src/lang.py",
                    "tier": 2,
                    "confidence": "medium",
                    "summary": "lang issue",
                    "name": "lang",
                }
            ],
            files_scanned=5,
            coverage=None,
        ),
    )

    monkeypatch.setattr(review_mod, "filter_entries", lambda _zones, entries, _detector: entries)
    monkeypatch.setattr(
        review_mod,
        "_entries_to_issues",
        lambda detector, entries, **_kwargs: [{"detector": detector, "file": e["file"]} for e in entries],
    )
    monkeypatch.setattr(review_mod, "_log_phase_summary", lambda *_args, **_kwargs: None)

    issues, potentials = review_mod.phase_security(
        Path("."),
        lang,
        detect_security_issues=lambda _files, _zones, _name, scan_root: (
            [
                {
                    "file": str(scan_root / "src" / "cross.py"),
                    "tier": 2,
                    "confidence": "high",
                    "summary": "cross issue",
                    "name": "cross",
                }
            ],
            2,
        ),
    )

    assert len(issues) == 2
    assert potentials == {"security": 5}
    assert lang.detector_coverage["security"]["status"] == "full"


def test_phase_security_reuses_lang_security_cache(monkeypatch, tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('a')\n")

    calls = {"count": 0}
    lang = SimpleNamespace(
        zone_map=None,
        file_finder=lambda _path: ["src/a.py"],
        name="python",
        review_cache={},
        detector_coverage={},
        detect_lang_security_detailed=lambda _files, _zones: (
            calls.__setitem__("count", calls["count"] + 1),
            LangSecurityResult(
                entries=[
                    {
                        "file": "src/lang.py",
                        "tier": 2,
                        "confidence": "medium",
                        "summary": "lang issue",
                        "name": "lang",
                    }
                ],
                files_scanned=3,
            ),
        )[1],
    )

    monkeypatch.setattr(review_mod, "filter_entries", lambda _zones, entries, _detector: entries)
    monkeypatch.setattr(
        review_mod,
        "_entries_to_issues",
        lambda detector, entries, **_kwargs: [{"detector": detector, "file": e["file"]} for e in entries],
    )
    monkeypatch.setattr(review_mod, "_log_phase_summary", lambda *_args, **_kwargs: None)

    first_issues, first_potentials = review_mod.phase_security(
        tmp_path,
        lang,
        detect_security_issues=lambda _files, _zones, _name, scan_root: (
            [
                {
                    "file": str(scan_root / "src" / "cross.py"),
                    "tier": 2,
                    "confidence": "high",
                    "summary": "cross issue",
                    "name": "cross",
                }
            ],
            1,
        ),
    )
    second_issues, second_potentials = review_mod.phase_security(
        tmp_path,
        lang,
        detect_security_issues=lambda _files, _zones, _name, scan_root: (
            [
                {
                    "file": str(scan_root / "src" / "cross.py"),
                    "tier": 2,
                    "confidence": "high",
                    "summary": "cross issue",
                    "name": "cross",
                }
            ],
            1,
        ),
    )

    assert calls["count"] == 1
    assert len(first_issues) == 2
    assert len(second_issues) == 2
    assert first_potentials == {"security": 3}
    assert second_potentials == {"security": 3}


def test_phase_security_uses_prefetched_lang_result(monkeypatch, tmp_path) -> None:
    class _ImmediateExecutor:
        def submit(self, fn, *args, **kwargs):
            future: concurrent.futures.Future = concurrent.futures.Future()
            future.set_result(fn(*args, **kwargs))
            return future

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('a')\n")
    calls = {"count": 0}
    lang = SimpleNamespace(
        zone_map=None,
        file_finder=lambda _path: ["src/a.py"],
        name="python",
        review_cache={},
        detector_coverage={},
        detect_lang_security_detailed=lambda _files, _zones: (
            calls.__setitem__("count", calls["count"] + 1),
            LangSecurityResult(
                entries=[],
                files_scanned=4,
            ),
        )[1],
    )

    monkeypatch.setattr(review_mod, "_PREFETCH_EXECUTOR", _ImmediateExecutor())
    monkeypatch.setattr(review_mod, "filter_entries", lambda _zones, entries, _detector: entries)
    monkeypatch.setattr(review_mod, "_entries_to_issues", lambda *_a, **_k: [])
    monkeypatch.setattr(review_mod, "_log_phase_summary", lambda *_args, **_kwargs: None)

    review_mod.prewarm_review_phase_detectors(
        tmp_path,
        lang,
        [SimpleNamespace(label="Security", run=review_mod.phase_security)],
    )
    issues, potentials = review_mod.phase_security(
        tmp_path,
        lang,
        detect_security_issues=lambda _files, _zones, _name, **_kwargs: ([], 1),
    )

    assert calls["count"] == 1
    assert issues == []
    assert potentials == {"security": 4}


def test_review_function_extraction_cached_across_signature_and_dupes(monkeypatch, tmp_path) -> None:
    calls = {"count": 0}
    functions = [SimpleNamespace(file="src/a.py", name="foo")]
    lang = SimpleNamespace(
        extract_functions=lambda _path: (
            calls.__setitem__("count", calls["count"] + 1),
            functions,
        )[1],
        zone_map=None,
        review_cache={},
    )

    monkeypatch.setattr(
        "desloppify.engine.detectors.signature.detect_signature_variance",
        lambda _functions, **_kwargs: ([], 0),
    )
    monkeypatch.setattr(review_mod, "detect_duplicates", lambda _functions, **_kwargs: ([], 1))
    monkeypatch.setattr(review_mod, "make_dupe_issues", lambda *_args, **_kwargs: [])

    review_mod.phase_signature(tmp_path, lang)
    review_mod.phase_dupes(tmp_path, lang)

    assert calls["count"] == 1


def test_phase_test_coverage_and_private_imports_paths(monkeypatch) -> None:
    lang_without_zones = SimpleNamespace(zone_map=None)
    assert review_mod.phase_test_coverage(Path("."), lang_without_zones) == ([], {})

    test_calls: dict[str, object] = {}
    lang = SimpleNamespace(
        zone_map=SimpleNamespace(),
        dep_graph=None,
        build_dep_graph=lambda _path: {"src/a.py": {"imports": set(), "importers": set()}},
        name="python",
        complexity_map={"src/a.py": 2.0},
        detect_private_imports=lambda _graph, _zones: (
            [
                {
                    "file": "src/a.py",
                    "tier": 3,
                    "confidence": "medium",
                    "summary": "private import",
                    "name": "a",
                }
            ],
            4,
        ),
    )

    monkeypatch.setattr(review_mod, "_find_external_test_files", lambda _path, _lang: {"tests/a_test.py"})

    def _fake_detect_test_coverage(graph, zone_map, name, *, extra_test_files, complexity_map):
        test_calls["graph"] = graph
        test_calls["extra_test_files"] = extra_test_files
        test_calls["complexity_map"] = complexity_map
        test_calls["name"] = name
        return (
            [
                {
                    "file": "src/a.py",
                    "tier": 3,
                    "confidence": "medium",
                    "summary": "missing test",
                    "name": "a",
                }
            ],
            6,
        )

    monkeypatch.setattr(review_mod, "detect_test_coverage", _fake_detect_test_coverage)
    monkeypatch.setattr(review_mod, "filter_entries", lambda _zones, entries, _detector: entries)
    monkeypatch.setattr(
        review_mod,
        "_entries_to_issues",
        lambda detector, entries, **_kwargs: [{"detector": detector, "file": e["file"]} for e in entries],
    )
    monkeypatch.setattr(review_mod, "_log_phase_summary", lambda *_args, **_kwargs: None)

    issues, potentials = review_mod.phase_test_coverage(Path("."), lang)
    assert len(issues) == 1
    assert potentials == {"test_coverage": 6}
    assert test_calls["name"] == "python"
    assert test_calls["extra_test_files"] == {"tests/a_test.py"}
    assert test_calls["complexity_map"] == {"src/a.py": 2.0}

    private_issues, private_potentials = review_mod.phase_private_imports(Path("."), lang)
    assert len(private_issues) == 1
    assert private_potentials == {"private_imports": 4}


def test_phase_subjective_review_normalizes_cache_shape(monkeypatch) -> None:
    """phase_subjective_review now creates one issue per unassessed/stale dimension."""

    lang = SimpleNamespace(
        zone_map=None,
        review_max_age_days=45,
        file_finder=lambda _path: ["src/a.py", "src/b.py"],
        review_cache={"holistic": {"updated_at": "today"}, "src/a.py": {"score": 90}},
        name="python",
        review_low_value_pattern=None,
        subjective_assessments={},
    )

    monkeypatch.setattr(
        "desloppify.base.subjective_dimensions.default_dimension_keys_for_lang",
        lambda _lang_name: ("naming_quality", "logic_clarity"),
    )
    monkeypatch.setattr(
        "desloppify.base.subjective_dimensions.dimension_display_name",
        lambda dim_key, lang_name=None: dim_key.replace("_", " ").title(),
    )
    monkeypatch.setattr(review_mod, "_log_phase_summary", lambda *_args, **_kwargs: None)

    issues, potentials = review_mod.phase_subjective_review(Path("."), lang)

    # Both dimensions unassessed → 2 issues
    assert len(issues) == 2
    assert potentials == {"subjective_review": 2}
    assert all(issue["detector"] == "subjective_review" for issue in issues)
    assert all(issue["file"] == "." for issue in issues)
    dim_keys = {issue["detail"]["dimension"] for issue in issues}
    assert dim_keys == {"naming_quality", "logic_clarity"}


def test_phase_signature_reports_variance(monkeypatch) -> None:
    lang = SimpleNamespace(
        extract_functions=lambda _path: [SimpleNamespace(name="run", file="src/a.py", line=1)],
    )

    monkeypatch.setattr(
        "desloppify.engine.detectors.signature.detect_signature_variance",
        lambda _functions, min_occurrences: (
            [
                {
                    "name": "run",
                    "files": ["src/a.py", "src/b.py"],
                    "signature_count": 2,
                    "file_count": 2,
                }
            ],
            min_occurrences,
        ),
    )

    issues, potentials = review_mod.phase_signature(Path("."), lang)

    assert len(issues) == 1
    assert issues[0]["detector"] == "signature"
    assert potentials == {"signature": 1}


def test_run_structural_phase_merges_large_complexity_and_flat_dirs(monkeypatch) -> None:
    lang = SimpleNamespace(
        file_finder=lambda _path: ["src/a.py"],
        large_threshold=100,
        complexity_threshold=10,
        complexity_map={},
        zone_map=None,
    )

    monkeypatch.setattr(
        structural_mod,
        "detect_large_files",
        lambda _path, **_kwargs: ([{"file": "src/large.py", "loc": 200}], 3),
    )
    monkeypatch.setattr(
        structural_mod,
        "detect_complexity",
        lambda _path, **_kwargs: ([{"file": "src/complex.py", "score": 21, "signals": ["TODOs"]}], 1),
    )
    monkeypatch.setattr(
        structural_mod,
        "merge_structural_signals",
        lambda _signals, _log_fn: [{"detector": "structural", "file": "src/large.py"}],
    )
    monkeypatch.setattr(
        structural_mod,
        "detect_flat_dirs",
        lambda _path, **_kwargs: (
            [
                {
                    "directory": "src",
                    "file_count": 22,
                    "child_dir_count": 1,
                    "combined_score": 23,
                }
            ],
            7,
        ),
    )

    logs: list[str] = []
    issues, potentials = structural_mod.run_structural_phase(
        Path("."),
        lang,
        complexity_signals=[],
        log_fn=logs.append,
    )

    assert len(issues) == 2
    assert any(issue["detector"] == "flat_dirs" for issue in issues)
    assert lang.complexity_map["src/complex.py"] == 21
    assert potentials == {"structural": 3, "flat_dirs": 7}


def test_run_coupling_phase_wires_single_cycles_orphaned_and_post_process(monkeypatch) -> None:
    lang = SimpleNamespace(
        dep_graph=None,
        zone_map=None,
        barrel_names={"index.py"},
        get_area=lambda _path: "core",
        extensions=[".py"],
        entry_patterns=["main.py"],
    )
    graph = {
        "src/a.py": {"imports": {"src/b.py"}, "importers": set()},
        "src/b.py": {"imports": set(), "importers": {"src/a.py"}},
    }

    monkeypatch.setattr(
        structural_mod,
        "detect_single_use_abstractions",
        lambda _path, _graph, **_kwargs: ([{"file": "src/a.py"}], 2),
    )
    monkeypatch.setattr(structural_mod, "filter_entries", lambda _zones, entries, _detector, file_key="file": entries)
    monkeypatch.setattr(structural_mod, "make_single_use_issues", lambda entries, _get_area, stderr_fn=None: [{"kind": "single", "entries": entries}])
    monkeypatch.setattr(structural_mod, "detect_cycles", lambda _graph: ([{"length": 2, "files": ["src/a.py", "src/b.py"]}], 0))
    monkeypatch.setattr(structural_mod, "make_cycle_issues", lambda entries, _log_fn: [{"kind": "cycle", "entries": entries}])
    monkeypatch.setattr(
        structural_mod,
        "detect_orphaned_files",
        lambda _path, _graph, **_kwargs: ([{"file": "src/c.py", "loc": 8}], 5),
    )
    monkeypatch.setattr(structural_mod, "make_orphaned_issues", lambda entries, _log_fn: [{"kind": "orphaned", "entries": entries}])

    post_process_calls: list[tuple[int, int]] = []

    def _post_process(issues, entries, _lang):
        post_process_calls.append((len(issues), len(entries)))

    issues, potentials = structural_mod.run_coupling_phase(
        Path("."),
        lang,
        build_dep_graph_fn=lambda _path: graph,
        log_fn=lambda _msg: None,
        post_process_fn=_post_process,
    )

    assert len(issues) == 3
    assert lang.dep_graph == graph
    assert potentials == {"single_use": 2, "cycles": 5, "orphaned": 5}
    assert post_process_calls == [(1, 1), (1, 1)]


def test_make_structural_coupling_phase_pair_delegates_to_runners(monkeypatch) -> None:
    monkeypatch.setattr(
        structural_mod,
        "run_structural_phase",
        lambda path, lang, **_kwargs: ([{"phase": "structural", "path": str(path)}], {"structural": 1}),
    )
    monkeypatch.setattr(
        structural_mod,
        "run_coupling_phase",
        lambda path, lang, **_kwargs: ([{"phase": "coupling", "path": str(path)}], {"cycles": 1}),
    )

    phase_structural, phase_coupling = structural_mod.make_structural_coupling_phase_pair(
        complexity_signals=[],
        build_dep_graph_fn=lambda _path: {},
        log_fn=lambda _msg: None,
    )

    structural_issues, structural_potentials = phase_structural(Path("."), SimpleNamespace())
    coupling_issues, coupling_potentials = phase_coupling(Path("."), SimpleNamespace())

    assert structural_issues[0]["phase"] == "structural"
    assert structural_potentials == {"structural": 1}
    assert coupling_issues[0]["phase"] == "coupling"
    assert coupling_potentials == {"cycles": 1}


def test_generic_structural_phase_and_coupling_delegate(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def _fake_run_structural_phase(path, lang, **kwargs):
        calls["structural"] = {
            "path": path,
            "lang": lang,
            "signals": kwargs["complexity_signals"],
            "min_loc": kwargs["min_loc"],
            "god_rules": kwargs["god_rules"],
        }
        return ([{"ok": True}], {"structural": 2})

    def _fake_run_coupling_phase(path, lang, **kwargs):
        calls["coupling"] = {
            "path": path,
            "lang": lang,
            "builder": kwargs["build_dep_graph_fn"],
        }
        return ([{"ok": True}], {"cycles": 2})

    monkeypatch.setattr(
        "desloppify.languages._framework.base.shared_phases.run_structural_phase",
        _fake_run_structural_phase,
    )
    monkeypatch.setattr(
        "desloppify.languages._framework.base.shared_phases.run_coupling_phase",
        _fake_run_coupling_phase,
    )

    structural_phase = generic_structural_mod._make_structural_phase()
    coupling_builder = lambda _path: {"graph": True}
    coupling_phase = generic_structural_mod._make_coupling_phase(coupling_builder)

    structural_issues, structural_potentials = structural_phase.run(Path("."), SimpleNamespace(file_finder=lambda _p: []))
    coupling_issues, coupling_potentials = coupling_phase.run(Path("."), SimpleNamespace())

    assert structural_phase.label == "Structural analysis"
    assert structural_issues == [{"ok": True}]
    assert structural_potentials == {"structural": 2}
    assert calls["structural"]["min_loc"] == 40
    assert calls["structural"]["signals"]
    assert coupling_phase.label == "Coupling + cycles + orphaned"
    assert coupling_issues == [{"ok": True}]
    assert coupling_potentials == {"cycles": 2}
    assert calls["coupling"]["builder"] is coupling_builder


def test_extract_ts_classes_populates_methods_and_handles_errors(monkeypatch) -> None:
    fake_class = SimpleNamespace(file="src/a.py", line=10, loc=10, methods=[])
    in_class_fn = SimpleNamespace(file="src/a.py", line=15)
    out_of_class_fn = SimpleNamespace(file="src/a.py", line=40)

    monkeypatch.setattr(
        "desloppify.languages._framework.treesitter.analysis.extractors.ts_extract_classes",
        lambda _path, _spec, _files: [fake_class],
    )
    monkeypatch.setattr(
        "desloppify.languages._framework.treesitter.analysis.extractors.ts_extract_functions",
        lambda _path, _spec, _files: [in_class_fn, out_of_class_fn],
    )

    classes = generic_structural_mod._extract_ts_classes(
        Path("."),
        treesitter_spec=SimpleNamespace(),
        file_finder=lambda _path: ["src/a.py"],
    )
    assert classes == [fake_class]
    assert fake_class.methods == [in_class_fn]

    monkeypatch.setattr(
        "desloppify.languages._framework.treesitter.analysis.extractors.ts_extract_classes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError("missing tree-sitter")),
    )
    assert (
        generic_structural_mod._extract_ts_classes(
            Path("."),
            treesitter_spec=SimpleNamespace(),
            file_finder=lambda _path: ["src/a.py"],
        )
        == []
    )
