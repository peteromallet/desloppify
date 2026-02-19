"""Tests for desloppify.engine.detectors.complexity — detect_complexity function."""

import textwrap

from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.engine.detectors.complexity import detect_complexity


def _write_file(tmp_path, name, content):
    """Helper: write a file and return its absolute path string."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return str(p)


def _file_finder_for(*paths):
    """Return a file_finder that always returns the given paths."""

    def finder(path):
        return list(paths)

    return finder


# ── Basic pattern matching ───────────────────────────────────


def test_single_pattern_above_threshold(tmp_path):
    """File with many pattern matches scores above threshold."""
    # Create a file with 60 lines, 20 of which match the pattern
    lines = ["if True:\n"] * 20 + ["x = 1\n"] * 40
    content = "".join(lines)
    fp = _write_file(tmp_path, "big.py", content)

    signals = [
        ComplexitySignal(name="conditionals", pattern=r"^if\b", weight=1, threshold=5)
    ]
    finder = _file_finder_for(fp)

    entries, total = detect_complexity(
        tmp_path, signals, finder, threshold=10, min_loc=10
    )
    assert total == 1
    assert len(entries) == 1
    assert entries[0]["file"] == fp
    assert entries[0]["score"] == 15  # (20 - 5) * 1
    assert "20 conditionals" in entries[0]["signals"][0]


def test_pattern_below_threshold_not_flagged(tmp_path):
    """File with few pattern matches is not flagged."""
    lines = ["if True:\n"] * 3 + ["x = 1\n"] * 57
    content = "".join(lines)
    fp = _write_file(tmp_path, "small.py", content)

    signals = [
        ComplexitySignal(name="conditionals", pattern=r"^if\b", weight=1, threshold=5)
    ]
    finder = _file_finder_for(fp)

    entries, total = detect_complexity(
        tmp_path, signals, finder, threshold=10, min_loc=10
    )
    assert total == 1
    assert len(entries) == 0


def test_min_loc_filter(tmp_path):
    """Files with fewer lines than min_loc are skipped entirely."""
    lines = ["if True:\n"] * 30
    content = "".join(lines)
    fp = _write_file(tmp_path, "short.py", content)

    signals = [
        ComplexitySignal(name="conditionals", pattern=r"^if\b", weight=1, threshold=0)
    ]
    finder = _file_finder_for(fp)

    entries, total = detect_complexity(
        tmp_path, signals, finder, threshold=1, min_loc=50
    )
    assert total == 1
    assert len(entries) == 0


# ── Compute-based signals ───────────────────────────────────


def test_compute_signal(tmp_path):
    """Compute-based signal contributes to score."""
    lines = ["x = 1\n"] * 60
    content = "".join(lines)
    fp = _write_file(tmp_path, "nested.py", content)

    def deep_nesting(content, lines):
        return (25, "25 deep nesting levels")

    signals = [
        ComplexitySignal(name="nesting", compute=deep_nesting, weight=1, threshold=0)
    ]
    finder = _file_finder_for(fp)

    entries, total = detect_complexity(
        tmp_path, signals, finder, threshold=15, min_loc=10
    )
    assert len(entries) == 1
    assert entries[0]["score"] == 25
    assert "25 deep nesting levels" in entries[0]["signals"]


def test_compute_signal_with_threshold(tmp_path):
    """Compute signal: only excess above threshold counts toward score."""
    lines = ["x = 1\n"] * 60
    fp = _write_file(tmp_path, "moderate.py", "".join(lines))

    def moderate_nesting(content, lines):
        return (20, "20 nesting")

    signals = [
        ComplexitySignal(
            name="nesting", compute=moderate_nesting, weight=2, threshold=10
        )
    ]
    finder = _file_finder_for(fp)

    entries, _ = detect_complexity(tmp_path, signals, finder, threshold=15, min_loc=10)
    assert len(entries) == 1
    # excess = max(0, 20 - 10) = 10; score = 10 * 2 = 20
    assert entries[0]["score"] == 20


def test_compute_returning_none_is_skipped(tmp_path):
    """Compute signal returning None contributes nothing."""
    lines = ["x = 1\n"] * 60
    fp = _write_file(tmp_path, "clean.py", "".join(lines))

    def no_issue(content, lines):
        return None

    signals = [ComplexitySignal(name="nothing", compute=no_issue, weight=5)]
    finder = _file_finder_for(fp)

    entries, _ = detect_complexity(tmp_path, signals, finder, threshold=1, min_loc=10)
    assert len(entries) == 0


# ── Multiple signals ─────────────────────────────────────────


def test_multiple_signals_combine_scores(tmp_path):
    """Multiple signals combine into a single score per file."""
    lines = ["if True:\n", "for x in y:\n"] * 20 + ["x = 1\n"] * 20
    fp = _write_file(tmp_path, "complex.py", "".join(lines))

    signals = [
        ComplexitySignal(name="ifs", pattern=r"^if\b", weight=1, threshold=5),
        ComplexitySignal(name="loops", pattern=r"^for\b", weight=2, threshold=5),
    ]
    finder = _file_finder_for(fp)

    entries, _ = detect_complexity(tmp_path, signals, finder, threshold=1, min_loc=10)
    assert len(entries) == 1
    # ifs: (20 - 5) * 1 = 15
    # loops: (20 - 5) * 2 = 30
    assert entries[0]["score"] == 45
    assert len(entries[0]["signals"]) == 2


# ── Sorting ──────────────────────────────────────────────────


def test_entries_sorted_by_score_descending(tmp_path):
    """Returned entries are sorted highest score first."""
    # File A: high score
    fa = _write_file(tmp_path, "a.py", "".join(["if True:\n"] * 30 + ["x = 1\n"] * 30))
    # File B: moderate score
    fb = _write_file(tmp_path, "b.py", "".join(["if True:\n"] * 20 + ["x = 1\n"] * 40))

    signals = [ComplexitySignal(name="ifs", pattern=r"^if\b", weight=1, threshold=5)]
    finder = _file_finder_for(fa, fb)

    entries, total = detect_complexity(
        tmp_path, signals, finder, threshold=10, min_loc=10
    )
    assert total == 2
    assert len(entries) == 2
    assert entries[0]["score"] >= entries[1]["score"]
    assert entries[0]["file"] == fa


# ── Edge cases ───────────────────────────────────────────────


def test_unreadable_file_is_skipped(tmp_path):
    """Files that raise OSError are silently skipped."""
    fp = str(tmp_path / "nonexistent.py")
    signals = [ComplexitySignal(name="ifs", pattern=r"^if\b")]
    finder = _file_finder_for(fp)

    entries, total = detect_complexity(
        tmp_path, signals, finder, threshold=1, min_loc=1
    )
    assert total == 1
    assert len(entries) == 0


def test_empty_file_list(tmp_path):
    """Empty file list returns empty results."""
    signals = [ComplexitySignal(name="ifs", pattern=r"^if\b")]
    finder = _file_finder_for()

    entries, total = detect_complexity(
        tmp_path, signals, finder, threshold=1, min_loc=1
    )
    assert total == 0
    assert entries == []


def test_no_signals_no_findings(tmp_path):
    """No signals means no file can be flagged."""
    lines = ["x = 1\n"] * 60
    fp = _write_file(tmp_path, "plain.py", "".join(lines))
    finder = _file_finder_for(fp)

    entries, total = detect_complexity(tmp_path, [], finder, threshold=1, min_loc=10)
    assert total == 1
    assert len(entries) == 0


def test_entry_contains_loc(tmp_path):
    """Each entry reports the LOC of the file."""
    lines = ["if True:\n"] * 60
    fp = _write_file(tmp_path, "loc.py", "".join(lines))

    signals = [ComplexitySignal(name="ifs", pattern=r"^if\b", weight=1, threshold=0)]
    finder = _file_finder_for(fp)

    entries, _ = detect_complexity(tmp_path, signals, finder, threshold=1, min_loc=10)
    assert entries[0]["loc"] == 60
