"""Tests for desloppify.engine.detectors.signature — detect_signature_variance."""

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.detectors.signature import _ALLOWLIST, detect_signature_variance


def _fn(name, file, params=None, line=1, return_annotation=None):
    """Helper: create a FunctionInfo with given name, file, and params."""
    return FunctionInfo(
        name=name,
        file=file,
        line=line,
        end_line=line + 5,
        loc=5,
        body="pass",
        params=params or [],
        return_annotation=return_annotation,
    )


# ── Basic variance detection ────────────────────────────────


def test_detects_variance_across_files():
    """Functions with the same name but different params across 3+ files are flagged."""
    functions = [
        _fn("process", "a.py", ["data"]),
        _fn("process", "b.py", ["data", "strict"]),
        _fn("process", "c.py", ["data"]),
    ]
    entries, total = detect_signature_variance(functions)
    assert total == 3
    assert len(entries) == 1
    assert entries[0]["name"] == "process"
    assert entries[0]["occurrences"] == 3
    assert entries[0]["file_count"] == 3
    assert entries[0]["signature_count"] == 2


def test_no_variance_identical_signatures():
    """Identical signatures across 3+ files produce no findings."""
    functions = [
        _fn("process", "a.py", ["data", "strict"]),
        _fn("process", "b.py", ["data", "strict"]),
        _fn("process", "c.py", ["data", "strict"]),
    ]
    entries, total = detect_signature_variance(functions)
    assert total == 3
    assert len(entries) == 0


def test_fewer_than_min_occurrences_skipped():
    """Functions in fewer than min_occurrences distinct files are skipped."""
    functions = [
        _fn("process", "a.py", ["data"]),
        _fn("process", "b.py", ["data", "extra"]),
    ]
    entries, total = detect_signature_variance(functions)
    assert len(entries) == 0


def test_custom_min_occurrences():
    """Custom min_occurrences lowers the threshold."""
    functions = [
        _fn("process", "a.py", ["data"]),
        _fn("process", "b.py", ["data", "extra"]),
    ]
    entries, _ = detect_signature_variance(functions, min_occurrences=2)
    assert len(entries) == 1
    assert entries[0]["name"] == "process"


def test_detects_return_annotation_variance():
    """Same param signature but different return annotations should be flagged."""
    functions = [
        _fn("process", "a.py", ["data"], return_annotation="list[str]"),
        _fn("process", "b.py", ["data"], return_annotation="dict[str, int]"),
        _fn("process", "c.py", ["data"], return_annotation="list[str]"),
    ]
    entries, _ = detect_signature_variance(functions)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["has_return_variance"] is True
    assert entry["return_signature_count"] == 2
    assert entry["has_param_variance"] is False


def test_missing_return_annotations_do_not_trigger_return_variance():
    """Missing annotations are ignored for return-variance detection."""
    functions = [
        _fn("process", "a.py", ["data"], return_annotation="list[str]"),
        _fn("process", "b.py", ["data"], return_annotation=None),
        _fn("process", "c.py", ["data"], return_annotation="list[str]"),
    ]
    entries, _ = detect_signature_variance(functions)
    assert entries == []


def test_phase_pattern_grouping_detects_variance_for_private_phase_functions():
    """_phase_* and phase_* functions are compared via the phase_* naming group."""
    functions = [
        _fn("_phase_unused", "lang/python/phases.py", ["path", "lang"],
            return_annotation="tuple[list[dict], dict[str, int]]"),
        _fn("_phase_smells", "lang/typescript/phases.py", ["path", "lang"],
            return_annotation="tuple[list[Finding], dict[str, int]]"),
        _fn("phase_dupes", "lang/base.py", ["path", "lang"],
            return_annotation="tuple[list[Finding], dict[str, int]]"),
    ]
    entries, _ = detect_signature_variance(functions, min_occurrences=3)
    phase_entries = [e for e in entries if e["name"] == "phase_*" and e["group_type"] == "pattern"]
    assert len(phase_entries) == 1
    assert phase_entries[0]["has_return_variance"] is True


# ── Filtering rules ─────────────────────────────────────────


def test_private_functions_skipped():
    """Single-underscore private functions are skipped."""
    functions = [
        _fn("_helper", "a.py", ["x"]),
        _fn("_helper", "b.py", ["x", "y"]),
        _fn("_helper", "c.py", ["x", "y", "z"]),
    ]
    entries, _ = detect_signature_variance(functions)
    assert len(entries) == 0


def test_dunder_methods_not_skipped_but_allowlisted():
    """Dunder methods like __init__ are in the allowlist and thus skipped."""
    functions = [
        _fn("__init__", "a.py", ["self"]),
        _fn("__init__", "b.py", ["self", "x"]),
        _fn("__init__", "c.py", ["self", "x", "y"]),
    ]
    entries, _ = detect_signature_variance(functions)
    assert len(entries) == 0


def test_allowlisted_names_skipped():
    """Names in the allowlist (e.g., 'main', 'get', 'post') are skipped."""
    for name in ["main", "get", "post", "setUp", "handle"]:
        assert name in _ALLOWLIST
        functions = [
            _fn(name, "a.py", ["x"]),
            _fn(name, "b.py", ["x", "y"]),
            _fn(name, "c.py", []),
        ]
        entries, _ = detect_signature_variance(functions)
        assert len(entries) == 0, f"{name} should be skipped"


def test_test_functions_skipped():
    """Functions starting with test_ are skipped."""
    functions = [
        _fn("test_something", "a.py", ["x"]),
        _fn("test_something", "b.py", ["x", "y"]),
        _fn("test_something", "c.py", []),
    ]
    entries, _ = detect_signature_variance(functions)
    assert len(entries) == 0


# ── self/cls filtering ───────────────────────────────────────


def test_self_and_cls_ignored_in_comparison():
    """Parameters named 'self' and 'cls' are excluded from signature comparison."""
    functions = [
        _fn("process", "a.py", ["self", "data"]),
        _fn("process", "b.py", ["cls", "data"]),
        _fn("process", "c.py", ["data"]),
    ]
    entries, _ = detect_signature_variance(functions)
    # After stripping self/cls, all have ["data"]
    assert len(entries) == 0


def test_self_stripped_but_variance_remains():
    """Even after stripping self/cls, actual param differences are caught."""
    functions = [
        _fn("process", "a.py", ["self", "data"]),
        _fn("process", "b.py", ["self", "data", "extra"]),
        _fn("process", "c.py", ["data"]),
    ]
    entries, _ = detect_signature_variance(functions)
    assert len(entries) == 1
    assert entries[0]["signature_count"] == 2


# ── Sorting ──────────────────────────────────────────────────


def test_entries_sorted_by_signature_count_then_occurrences():
    """Results sorted by descending signature_count, then descending occurrences."""
    functions = [
        # "alpha" has 3 variants across 4 files
        _fn("alpha", "a.py", ["x"]),
        _fn("alpha", "b.py", ["x", "y"]),
        _fn("alpha", "c.py", ["x", "y", "z"]),
        _fn("alpha", "d.py", ["x"]),
        # "beta" has 2 variants across 3 files
        _fn("beta", "e.py", ["a"]),
        _fn("beta", "f.py", ["a", "b"]),
        _fn("beta", "g.py", ["a"]),
    ]
    entries, _ = detect_signature_variance(functions)
    assert len(entries) == 2
    assert entries[0]["name"] == "alpha"
    assert entries[1]["name"] == "beta"


# ── Same file duplicates ────────────────────────────────────


def test_same_file_multiple_definitions_needs_distinct_files():
    """Multiple definitions in the same file still need min distinct files."""
    functions = [
        _fn("process", "a.py", ["x"], line=1),
        _fn("process", "a.py", ["x", "y"], line=20),
        _fn("process", "b.py", ["x"]),
    ]
    # Only 2 distinct files, default min_occurrences=3
    entries, _ = detect_signature_variance(functions)
    assert len(entries) == 0


# ── Empty input ──────────────────────────────────────────────


def test_empty_functions_list():
    """Empty input returns empty results."""
    entries, total = detect_signature_variance([])
    assert total == 0
    assert entries == []


# ── Variants detail ──────────────────────────────────────────


def test_variants_contain_correct_detail():
    """Each entry's variants list has file, line, params, param_count."""
    functions = [
        _fn("process", "a.py", ["data"], line=10),
        _fn("process", "b.py", ["data", "strict"], line=20),
        _fn("process", "c.py", ["data"], line=30),
    ]
    entries, _ = detect_signature_variance(functions)
    assert len(entries) == 1
    variants = entries[0]["variants"]
    assert len(variants) == 3
    for v in variants:
        assert "file" in v
        assert "line" in v
        assert "params" in v
        assert "param_count" in v
    # Check specific variant
    a_variant = [v for v in variants if v["file"] == "a.py"][0]
    assert a_variant["line"] == 10
    assert a_variant["params"] == ["data"]
    assert a_variant["param_count"] == 1
