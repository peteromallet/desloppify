"""Direct tests for split Python security/dict-key/smell helper modules."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import desloppify.languages.python._security as py_security_mod
import desloppify.languages.python.detectors.dict_keys.schema as schema_mod
import desloppify.languages.python.detectors.dict_keys.shared as shared_mod
import desloppify.languages.python.detectors.dict_keys.visitor_helpers as visitor_helpers_mod
import desloppify.languages.python.detectors.smells_ast._node_detectors_complexity as complexity_mod
import desloppify.languages.python.detectors.smells_ast._node_detectors_nesting as nesting_mod


def test_python_security_prerequisites_and_detection_flow(monkeypatch, tmp_path) -> None:
    missing = py_security_mod.missing_bandit_coverage()
    assert missing.detector == "security"
    assert missing.status == "reduced"
    assert missing.reason == "missing_dependency"

    monkeypatch.setattr(py_security_mod.shutil, "which", lambda _cmd: None)
    prereqs = py_security_mod.python_scan_coverage_prerequisites()
    assert len(prereqs) == 1

    monkeypatch.setattr(py_security_mod.shutil, "which", lambda _cmd: "/usr/bin/bandit")
    assert py_security_mod.python_scan_coverage_prerequisites() == []

    monkeypatch.setattr(py_security_mod, "scan_root_from_files", lambda _files: None)
    empty = py_security_mod.detect_python_security(["a.py"], zone_map=None)
    assert empty.entries == []
    assert empty.files_scanned == 0

    class _Status:
        def coverage(self):
            return {"detector": "security", "status": "full"}

    monkeypatch.setattr(py_security_mod, "scan_root_from_files", lambda _files: tmp_path)
    monkeypatch.setattr(py_security_mod, "collect_exclude_dirs", lambda _root: [".venv", "build"])

    captured_files: list[str] = []

    def _fake_bandit(detected_files, _zone_map, *, exclude_dirs, skip_tests=None):
        captured_files.extend(detected_files)
        return SimpleNamespace(
            entries=[{"file": "a.py", "line": 1}],
            files_scanned=3,
            status=_Status(),
            exclude_dirs=exclude_dirs,
        )

    monkeypatch.setattr(
        py_security_mod,
        "detect_with_bandit_files",
        _fake_bandit,
    )

    result = py_security_mod.detect_python_security(["a.py", "b.py"], zone_map=None)
    assert len(result.entries) == 1
    assert result.files_scanned == 3
    assert result.coverage["status"] == "full"
    assert captured_files == ["a.py", "b.py"]


def test_dict_key_shared_helpers_cover_names_keys_and_distance() -> None:
    assert shared_mod._levenshtein("kitten", "sitting") == 3
    assert shared_mod._is_singular_plural("user", "users") is True
    assert shared_mod._is_singular_plural("city", "cities") is True

    name_node = ast.parse("value", mode="eval").body
    attr_node = ast.parse("self.state", mode="eval").body
    key_node = ast.parse("'token'", mode="eval").body

    assert shared_mod._get_name(name_node) == "value"
    assert shared_mod._get_name(attr_node) == "self.state"
    assert shared_mod._get_name(ast.parse("x + y", mode="eval").body) is None
    assert shared_mod._get_str_key(key_node) == "token"
    assert shared_mod._get_str_key(ast.parse("123", mode="eval").body) is None


def test_schema_helpers_cover_parsing_clustering_and_issue_generation(monkeypatch, tmp_path) -> None:
    assert schema_mod._jaccard(frozenset(), frozenset()) == 1.0
    assert schema_mod._jaccard(frozenset({"a", "b"}), frozenset({"b", "c"})) == 1 / 3

    source_file = (tmp_path / "sample.py").resolve()
    source_file.write_text("value = {'a': 1, 'b': 2, 'c': 3}\n", encoding="utf-8")
    assert schema_mod._read_python_file(str(source_file)) is not None
    assert schema_mod._parse_python_ast("def broken(:\n", filepath=str(source_file)) is None

    dict_node = ast.parse("{'a': 1, 'b': 2, 'c': 3}", mode="eval").body
    assert schema_mod._extract_literal_keyset(dict_node) == frozenset({"a", "b", "c"})

    literals = [
        {"file": "a.py", "line": 10, "keys": frozenset({"name", "email", "count"})},
        {"file": "b.py", "line": 20, "keys": frozenset({"name", "email", "count"})},
        {"file": "c.py", "line": 30, "keys": frozenset({"name", "email", "count"})},
        {"file": "d.py", "line": 40, "keys": frozenset({"name", "email", "count"})},
        {"file": "e.py", "line": 50, "keys": frozenset({"names", "email", "count"})},
    ]
    clusters = schema_mod._cluster_by_jaccard(literals, threshold=0.5)
    assert len(clusters) == 1

    issues = schema_mod._build_schema_drift_issues(clusters)
    assert issues
    assert issues[0]["kind"] == "schema_drift"

    monkeypatch.setattr(schema_mod, "find_py_files", lambda _path: ["a.py", "b.py", "c.py"])
    monkeypatch.setattr(schema_mod, "_collect_schema_literals", lambda _files: literals)
    monkeypatch.setattr(schema_mod, "_cluster_by_jaccard", lambda _literals, threshold=0.8: [literals])
    detected, checked = schema_mod.detect_schema_drift(Path("."))
    assert checked == 5
    assert detected


def test_visitor_helpers_track_calls_escapes_and_scope_issues() -> None:
    tracked = shared_mod.TrackedDict(name="state", created_line=1, locally_created=True)

    class _Visitor:
        filepath = "src/service.py"

        def _get_tracked(self, name: str):
            return tracked if name == "state" else None

    visitor = _Visitor()

    tuple_expr = ast.parse("(state, [state], {'k': state})", mode="eval").body
    visitor_helpers_mod.mark_returned_or_passed(visitor, tuple_expr)
    assert tracked.returned_or_passed is True

    tracked.returned_or_passed = False
    assign = ast.parse("target[0] = state").body[0]
    assert isinstance(assign, ast.Assign)
    visitor_helpers_mod.mark_assignment_escape(visitor, assign.targets, assign.value)
    assert tracked.returned_or_passed is True

    tracked.returned_or_passed = False
    tracked.has_dynamic_key = False
    tracked.has_star_unpack = False
    tracked.bulk_read = False
    tracked.writes.clear()
    tracked.reads.clear()

    calls = ast.parse(
        "\n".join(
            [
                "state.get('token')",
                "state.setdefault('count', 1)",
                "state.update({'name': 'x'}, age=1)",
                "state.items()",
                "fn(**state)",
            ]
        )
    ).body
    for stmt in calls:
        assert isinstance(stmt, ast.Expr)
        visitor_helpers_mod.record_call_interactions(visitor, stmt.value)

    assert tracked.reads["token"]
    assert tracked.writes["count"]
    assert tracked.writes["name"]
    assert tracked.writes["age"]
    assert tracked.bulk_read is True
    assert tracked.has_star_unpack is True

    tracked.returned_or_passed = False
    tracked.has_dynamic_key = False
    tracked.has_star_unpack = False
    tracked.bulk_read = False
    tracked.writes = {"apples": [2], "count": [10, 12]}
    tracked.reads = {"apple": [3], "count": [20]}

    issues = visitor_helpers_mod.analyze_scope_issues(visitor, {"state": tracked}, "process")
    kinds = {issue["kind"] for issue in issues}
    assert {"dead_write", "phantom_read", "near_miss", "overwritten_key"}.issubset(kinds)


def test_complexity_and_nesting_node_detectors(monkeypatch) -> None:
    fn_node = ast.parse(
        """

def run(x):
    if x and x > 1:
        return 1
    for i in range(3):
        if i:
            return i
    return 0
"""
    ).body[0]
    assert isinstance(fn_node, ast.FunctionDef)

    score = complexity_mod._compute_cyclomatic_complexity(fn_node)
    assert score >= 4

    monkeypatch.setattr(complexity_mod, "_compute_cyclomatic_complexity", lambda _node: 13)
    high = complexity_mod._detect_high_cyclomatic_complexity("a.py", fn_node)
    assert high and "cyclomatic complexity" in high[0]["content"]

    module_tree = ast.parse(
        """
from functools import lru_cache
state = []

@lru_cache(maxsize=32)
def cached(n):
    return len(state) + n
"""
    )
    cached_fn = next(node for node in module_tree.body if isinstance(node, ast.FunctionDef))
    mutable = complexity_mod._detect_lru_cache_mutable("mod.py", cached_fn, module_tree)
    assert mutable and "mutable global" in mutable[0]["content"]

    no_cache_tree = ast.parse("def plain(x):\n    return x\n")
    plain_fn = no_cache_tree.body[0]
    assert isinstance(plain_fn, ast.FunctionDef)
    assert complexity_mod._detect_lru_cache_mutable("mod.py", plain_fn, no_cache_tree) == []

    nested_tree = ast.parse(
        """

def outer():
    x = [0]
    def inner():
        def deep():
            return x[0]
        return deep()
    return inner()
"""
    )
    outer_fn = nested_tree.body[0]
    assert isinstance(outer_fn, ast.FunctionDef)

    nested_issues = nesting_mod._detect_nested_closures("a.py", outer_fn)
    assert nested_issues and "inner defs" in nested_issues[0]["content"]

    mutable_ref_issues = nesting_mod._detect_mutable_ref_hack("a.py", outer_fn)
    assert mutable_ref_issues and "mutable-list ref hack" in mutable_ref_issues[0]["content"]

    inner_defs: list[ast.AST] = []
    max_depth = nesting_mod._walk_inner_defs(outer_fn.body, 0, inner_defs)
    assert max_depth >= 2
    assert "inner" in nesting_mod._format_inner_def_names(inner_defs)

    used = nesting_mod._find_subscript_zero_refs(outer_fn, {"x"})
    assert used == {"x"}
