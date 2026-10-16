"""Tests for desloppify.engine.detectors.dupes — duplicate/near-duplicate function detection."""

import hashlib

import desloppify.engine.detectors.dupes as dupes_mod
from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.detectors.dupes import detect_duplicates


def _make_fn(
    name: str, file: str, body: str, line: int = 1, loc: int | None = None
) -> FunctionInfo:
    """Create a FunctionInfo with auto-computed hash and normalized body."""
    lines = body.strip().splitlines()
    actual_loc = loc if loc is not None else len(lines)
    normalized = "\n".join(line_text.strip() for line_text in lines)
    body_hash = hashlib.sha256(normalized.encode()).hexdigest()
    return FunctionInfo(
        name=name,
        file=file,
        line=line,
        end_line=line + actual_loc,
        loc=actual_loc,
        body=body,
        normalized=normalized,
        body_hash=body_hash,
    )


def _set_span(fn: FunctionInfo, start: int, end: int) -> FunctionInfo:
    fn.line = start
    fn.end_line = end
    return fn


class TestDetectDuplicates:
    def test_empty_input(self):
        entries, total = detect_duplicates([])
        assert entries == []
        assert total == 0

    def test_no_duplicates(self):
        fns = [
            _make_fn("foo", "a.py", "x = 1\ny = 2\nreturn x + y"),
            _make_fn("bar", "b.py", "a = 10\nb = 20\nreturn a - b"),
        ]
        entries, total = detect_duplicates(fns)
        assert entries == []
        assert total == 2

    def test_exact_duplicates_detected(self):
        body = "x = 1\ny = 2\nreturn x + y"
        fns = [
            _make_fn("foo", "a.py", body),
            _make_fn("bar", "b.py", body),
        ]
        entries, total = detect_duplicates(fns)
        assert len(entries) == 1
        assert entries[0]["kind"] == "exact"
        assert entries[0]["similarity"] == 1.0
        assert entries[0]["cluster_size"] == 2
        assert total == 2

    def test_near_duplicates_detected(self):
        """Functions with high similarity but different hashes should be found."""
        # Build bodies that are very similar but not identical, each >= 15 LOC
        # Use long repetitive lines so a single-char change yields high ratio
        base_lines = [f"    result = compute_value_{i}(x, y, z)" for i in range(20)]
        body_a = "\n".join(base_lines)
        # Change just one line slightly
        modified_lines = base_lines.copy()
        modified_lines[19] = "    result = compute_value_19(x, y, w)"
        body_b = "\n".join(modified_lines)

        fns = [
            _make_fn("foo", "a.py", body_a, loc=20),
            _make_fn("bar", "b.py", body_b, loc=20),
        ]
        entries, total = detect_duplicates(fns, threshold=0.8)
        assert len(entries) == 1
        assert entries[0]["kind"] == "near-duplicate"
        assert entries[0]["similarity"] >= 0.8
        assert total == 2

    def test_near_duplicates_under_threshold_not_detected(self):
        """Functions below the similarity threshold should not be flagged."""
        body_a = "\n".join(f"    a_{i} = {i}" for i in range(20))
        body_b = "\n".join(f"    b_{i} = {i * 100}" for i in range(20))
        fns = [
            _make_fn("foo", "a.py", body_a, loc=20),
            _make_fn("bar", "b.py", body_b, loc=20),
        ]
        entries, total = detect_duplicates(fns, threshold=0.95)
        assert entries == []

    def test_near_duplicates_require_15_loc(self):
        """Near-duplicate detection only applies to functions >= 15 LOC."""
        base_lines = [f"    line_{i} = {i}" for i in range(10)]
        body_a = "\n".join(base_lines)
        modified_lines = base_lines.copy()
        modified_lines[5] = "    line_5 = 999"
        body_b = "\n".join(modified_lines)

        fns = [
            _make_fn("foo", "a.py", body_a, loc=10),
            _make_fn("bar", "b.py", body_b, loc=10),
        ]
        # These have different hashes so won't be exact matches,
        # and loc < 15 so won't be near-duplicate candidates
        entries, total = detect_duplicates(fns, threshold=0.5)
        assert entries == []

    def test_small_exact_duplicates_still_found(self):
        """Exact duplicates should be found regardless of LOC."""
        body = "return 1"
        fns = [
            _make_fn("foo", "a.py", body, loc=1),
            _make_fn("bar", "b.py", body, loc=1),
        ]
        entries, total = detect_duplicates(fns)
        assert len(entries) == 1
        assert entries[0]["kind"] == "exact"

    def test_single_function_no_duplicates(self):
        fns = [_make_fn("foo", "a.py", "return 1")]
        entries, total = detect_duplicates(fns)
        assert entries == []
        assert total == 1

    def test_cluster_size_with_three_exact_copies(self):
        body = "x = 1\ny = 2\nreturn x + y"
        fns = [
            _make_fn("foo", "a.py", body),
            _make_fn("bar", "b.py", body),
            _make_fn("baz", "c.py", body),
        ]
        entries, total = detect_duplicates(fns)
        assert len(entries) == 1
        assert entries[0]["cluster_size"] == 3
        assert len(entries[0]["cluster"]) == 3

    def test_entry_structure(self):
        body = "x = 1\ny = 2\nreturn x + y"
        fns = [
            _make_fn("foo", "a.py", body, line=5),
            _make_fn("bar", "b.py", body, line=10),
        ]
        entries, total = detect_duplicates(fns)
        entry = entries[0]
        assert "fn_a" in entry
        assert "fn_b" in entry
        assert "similarity" in entry
        assert "kind" in entry
        assert "cluster_size" in entry
        assert "cluster" in entry
        # fn_a and fn_b should have file, name, line, loc
        for fn_key in ("fn_a", "fn_b"):
            fn = entry[fn_key]
            assert "file" in fn
            assert "name" in fn
            assert "line" in fn
            assert "loc" in fn

    def test_sorted_by_similarity_descending(self):
        """Entries should be sorted by similarity descending."""
        body_exact = "x = 1\ny = 2\nreturn x + y"
        # Build near-duplicate bodies with high similarity
        base_lines = [f"    result = compute_value_{i}(x, y, z)" for i in range(20)]
        body_near_a = "\n".join(base_lines)
        modified = base_lines.copy()
        modified[19] = "    result = compute_value_19(x, y, w)"
        body_near_b = "\n".join(modified)

        fns = [
            _make_fn("exact1", "a.py", body_exact),
            _make_fn("exact2", "b.py", body_exact),
            _make_fn("near1", "c.py", body_near_a, loc=20),
            _make_fn("near2", "d.py", body_near_b, loc=20),
        ]
        entries, total = detect_duplicates(fns, threshold=0.8)
        assert len(entries) == 2
        assert entries[0]["similarity"] >= entries[1]["similarity"]

    def test_prunes_near_dupes_when_line_count_bound_cannot_meet_threshold(
        self, monkeypatch
    ):
        """Skip expensive matcher work when line-count upper bound is impossible."""
        body_a = "\n".join(f"a_{i}" for i in range(16))
        body_b = "\n".join(f"b_{i}" for i in range(24))
        fns = [
            _make_fn("short_fn", "a.py", body_a, loc=16),
            _make_fn("long_fn", "b.py", body_b, loc=24),
        ]

        class _ShouldNotInstantiate:
            def __init__(self, *_args, **_kwargs):
                raise AssertionError(
                    "SequenceMatcher should not be created for pruned pairs"
                )

        monkeypatch.setattr(
            "desloppify.engine.detectors.dupes.difflib.SequenceMatcher",
            _ShouldNotInstantiate,
        )

        entries, total = detect_duplicates(fns, threshold=0.81)
        assert entries == []
        assert total == 2

    def test_does_not_prune_true_near_duplicates_with_uneven_line_lengths(self):
        """Length pruning should not drop near-duplicates that differ by line text length."""
        base = ["x" for _ in range(20)]
        modified = base.copy()
        modified[-1] = "y" * 1000
        fns = [
            _make_fn("a", "a.py", "\n".join(base), loc=20),
            _make_fn("b", "b.py", "\n".join(modified), loc=20),
        ]

        entries, total = detect_duplicates(fns, threshold=0.9)
        assert len(entries) == 1
        assert entries[0]["kind"] == "near-duplicate"
        assert entries[0]["similarity"] >= 0.9
        assert total == 2

    def test_same_file_same_name_pairs_do_not_collapse(self):
        """Same-file/same-name functions at different lines keep distinct pair keys."""
        body_a = "x = 1\ny = 2\nreturn x + y"
        body_b = "a = 10\nb = 20\nreturn a - b"
        fns = [
            _make_fn("dup", "same.py", body_a, line=1),
            _make_fn("dup", "same.py", body_a, line=20),
            _make_fn("dup", "same.py", body_b, line=40),
            _make_fn("dup", "same.py", body_b, line=60),
        ]

        entries, total = detect_duplicates(fns)
        assert total == 4
        assert len(entries) == 2
        assert all(entry["kind"] == "exact" for entry in entries)

    def test_exact_duplicates_skip_nested_and_identical_source_spans(self):
        body = "return 1"
        overlapping_pairs = [
            [
                _set_span(_make_fn("outer", "same.py", body), 1, 30),
                _set_span(_make_fn("nested", "same.py", body), 5, 12),
            ],
            [
                _set_span(_make_fn("same_span", "same.py", body), 40, 50),
                _set_span(_make_fn("same_span_copy", "same.py", body), 40, 50),
            ],
        ]
        for fns in overlapping_pairs:
            entries, total = detect_duplicates(fns)
            assert total == 2
            assert entries == []

        for file_a, file_b, start_a, end_a, start_b, end_b in (
            ("same.py", "same.py", 60, 65, 70, 75),
            ("same.py", "other.py", 1, 10, 1, 10),
        ):
            fns = [
                _set_span(_make_fn("a", file_a, body), start_a, end_a),
                _set_span(_make_fn("b", file_b, body), start_b, end_b),
            ]
            entries, total = detect_duplicates(fns)
            assert total == 2
            assert len(entries) == 1

    def test_exact_duplicates_keep_ambiguous_single_line_intersections(self):
        body = "return 1"
        same_row = [
            _set_span(_make_fn("first", "same.py", body, line=10), 10, 10),
            _set_span(_make_fn("second", "same.py", body, line=10), 10, 10),
        ]
        boundary_touch = [
            _set_span(_make_fn("first", "same.py", body), 1, 10),
            _set_span(_make_fn("second", "same.py", body), 10, 20),
        ]

        for fns in (same_row, boundary_touch):
            entries, total = detect_duplicates(fns)
            assert total == 2
            assert len(entries) == 1
            assert entries[0]["kind"] == "exact"

    def test_exact_duplicates_keep_pairs_with_missing_end_bounds(self):
        fns = [
            _set_span(_make_fn("first", "same.py", "return 1"), 10, 10),
            _set_span(_make_fn("second", "same.py", "return 1"), 10, 10),
        ]
        fns[0].end_line = None  # type: ignore[assignment]

        entries, total = detect_duplicates(fns)

        assert total == 2
        assert len(entries) == 1
        assert entries[0]["kind"] == "exact"

    def test_near_duplicates_skip_nested_and_identical_source_spans(self):
        base = [f"value_{i} = compute({i})" for i in range(20)]
        changed = base.copy()
        changed[-1] = "value_19 = compute(other)"
        for start_a, end_a, start_b, end_b in ((1, 40, 10, 30), (50, 70, 50, 70)):
            fns = [
                _set_span(
                    _make_fn("a", "same.py", "\n".join(base), loc=20),
                    start_a,
                    end_a,
                ),
                _set_span(
                    _make_fn("b", "same.py", "\n".join(changed), loc=20),
                    start_b,
                    end_b,
                ),
            ]
            entries, total = detect_duplicates(fns, threshold=0.8)
            assert total == 2
            assert entries == []

        for file_a, file_b, start_a, end_a, start_b, end_b in (
            ("same.py", "same.py", 80, 100, 110, 130),
            ("same.py", "other.py", 1, 40, 1, 40),
        ):
            fns = [
                _set_span(
                    _make_fn("a", file_a, "\n".join(base), loc=20), start_a, end_a
                ),
                _set_span(
                    _make_fn("b", file_b, "\n".join(changed), loc=20), start_b, end_b
                ),
            ]
            entries, total = detect_duplicates(fns, threshold=0.8)
            assert total == 2
            assert len(entries) == 1
            assert entries[0]["kind"] == "near-duplicate"

    def test_cached_near_pairs_prune_overlapping_spans(self):
        base = [f"value_{i} = compute({i})" for i in range(20)]
        changed = base.copy()
        changed[-1] = "value_19 = compute(other)"
        fns = [
            _set_span(_make_fn("outer", "same.py", "\n".join(base), loc=20), 1, 40),
            _set_span(_make_fn("nested", "same.py", "\n".join(changed), loc=20), 10, 30),
        ]
        function_meta, _ = dupes_mod._build_function_cache_map(fns)
        left_id = dupes_mod._function_identity(fns[0])
        right_id = dupes_mod._function_identity(fns[1])
        cache: dict[str, object] = {
            "version": dupes_mod._DUPES_CACHE_VERSION,
            "threshold": 0.8,
            "functions": function_meta,
            "near_pairs": [{"a": left_id, "b": right_id, "similarity": 0.99}],
        }

        entries, total = detect_duplicates(fns, threshold=0.8, cache=cache)

        assert total == 2
        assert entries == []
        assert cache["near_pairs"] == []

    def test_near_duplicate_cache_reuses_pairs_without_matcher(self, monkeypatch):
        base_lines = [f"    result = compute_value_{i}(x, y, z)" for i in range(20)]
        body_a = "\n".join(base_lines)
        changed = base_lines.copy()
        changed[-1] = "    result = compute_value_19(x, y, w)"
        body_b = "\n".join(changed)
        fns = [
            _make_fn("foo", "a.py", body_a, loc=20),
            _make_fn("bar", "b.py", body_b, loc=20),
        ]
        cache: dict[str, object] = {}
        first_entries, total = detect_duplicates(fns, threshold=0.8, cache=cache)
        assert total == 2
        assert len(first_entries) == 1
        assert isinstance(cache.get("near_pairs"), list)
        assert cache.get("near_pairs")

        class _NoMatcher:
            def __init__(self, *_args, **_kwargs):
                raise AssertionError("near matcher should not run for unchanged cached pairs")

        monkeypatch.setattr(
            "desloppify.engine.detectors.dupes.difflib.SequenceMatcher",
            _NoMatcher,
        )
        second_entries, second_total = detect_duplicates(
            fns,
            threshold=0.8,
            cache=cache,
        )
        assert second_total == 2
        assert len(second_entries) == 1
        assert second_entries[0]["kind"] == "near-duplicate"

    def test_cache_threshold_mismatch_falls_back_to_full_near_pass(self, monkeypatch):
        base_lines = [f"    result = compute_value_{i}(x, y, z)" for i in range(20)]
        body_a = "\n".join(base_lines)
        changed = base_lines.copy()
        changed[-1] = "    result = compute_value_19(x, y, w)"
        body_b = "\n".join(changed)
        fns = [
            _make_fn("foo", "a.py", body_a, loc=20),
            _make_fn("bar", "b.py", body_b, loc=20),
        ]
        cache: dict[str, object] = {}
        detect_duplicates(fns, threshold=0.8, cache=cache)

        real_matcher = dupes_mod.difflib.SequenceMatcher
        calls = {"count": 0}

        class _CountingMatcher(real_matcher):
            def __init__(self, *args, **kwargs):
                calls["count"] += 1
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(
            "desloppify.engine.detectors.dupes.difflib.SequenceMatcher",
            _CountingMatcher,
        )
        entries, total = detect_duplicates(fns, threshold=0.95, cache=cache)
        assert total == 2
        assert calls["count"] > 0
        assert len(entries) == 1
        assert cache["threshold"] == 0.95
