"""Tests for framework finding factories and structural signal helpers."""

from desloppify.languages.framework.base.structural import (
    add_structural_signal,
    merge_structural_signals,
)
from desloppify.languages.framework.finding_factories import (
    SMELL_TIER_MAP,
    make_cycle_findings,
    make_dupe_findings,
    make_facade_findings,
    make_orphaned_findings,
    make_passthrough_findings,
    make_single_use_findings,
    make_smell_findings,
    make_unused_findings,
)


def _noop_log(msg):
    """No-op stderr function for tests."""
    pass


def _capture_log():
    """Return a list that captures logged messages and a log function."""
    messages = []

    def log(msg):
        messages.append(msg)

    return messages, log


# ── make_unused_findings ─────────────────────────────────────


class TestMakeUnusedFindings:
    def test_imports_get_tier1(self):
        """Unused imports produce tier 1 findings."""
        entries = [
            {"file": "/proj/a.py", "name": "os", "line": 1, "category": "imports"}
        ]
        results = make_unused_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 1
        assert results[0]["confidence"] == "high"
        assert results[0]["detector"] == "unused"
        assert "Unused imports: os" in results[0]["summary"]

    def test_non_imports_get_tier2(self):
        """Unused non-imports (exports, variables) produce tier 2 findings."""
        entries = [
            {"file": "/proj/a.py", "name": "foo", "line": 5, "category": "exports"}
        ]
        results = make_unused_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 2

    def test_empty_entries(self):
        """Empty entries produce empty results."""
        results = make_unused_findings([], _noop_log)
        assert results == []

    def test_multiple_entries(self):
        """Multiple entries each produce one finding."""
        entries = [
            {"file": "/proj/a.py", "name": "os", "line": 1, "category": "imports"},
            {"file": "/proj/b.py", "name": "sys", "line": 2, "category": "imports"},
        ]
        results = make_unused_findings(entries, _noop_log)
        assert len(results) == 2

    def test_stderr_called(self):
        """Stderr function is called with count info."""
        messages, log = _capture_log()
        entries = [
            {"file": "/proj/a.py", "name": "os", "line": 1, "category": "imports"}
        ]
        make_unused_findings(entries, log)
        assert len(messages) == 1
        assert "1 instances" in messages[0]


# ── make_dupe_findings ───────────────────────────────────────


class TestMakeDupeFindings:
    def _make_entry(self, kind="exact", similarity=1.0, loc_a=50, loc_b=50):
        return {
            "fn_a": {"file": "/proj/a.py", "name": "foo", "line": 10, "loc": loc_a},
            "fn_b": {"file": "/proj/b.py", "name": "bar", "line": 20, "loc": loc_b},
            "similarity": similarity,
            "kind": kind,
        }

    def test_exact_dupe_tier2(self):
        """Exact duplicates produce tier 2 findings."""
        entries = [self._make_entry(kind="exact")]
        results = make_dupe_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 2
        assert results[0]["confidence"] == "high"
        assert "Exact dupe" in results[0]["summary"]

    def test_near_dupe_tier3(self):
        """Near duplicates produce tier 3 findings."""
        entries = [self._make_entry(kind="near", similarity=0.85)]
        results = make_dupe_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 3
        assert results[0]["confidence"] == "low"
        assert "Near dupe" in results[0]["summary"]

    def test_small_functions_suppressed(self):
        """Both functions under 10 LOC are suppressed."""
        entries = [self._make_entry(loc_a=5, loc_b=8)]
        results = make_dupe_findings(entries, _noop_log)
        assert len(results) == 0

    def test_one_large_function_not_suppressed(self):
        """Only one function under 10 LOC: not suppressed."""
        entries = [self._make_entry(loc_a=5, loc_b=50)]
        results = make_dupe_findings(entries, _noop_log)
        assert len(results) == 1

    def test_cluster_size_in_summary(self):
        """Cluster size > 2 triggers cluster summary format."""
        entry = self._make_entry()
        entry["cluster_size"] = 4
        entry["cluster"] = [entry["fn_a"], entry["fn_b"]]
        results = make_dupe_findings([entry], _noop_log)
        assert "cluster (4 functions" in results[0]["summary"]

    def test_detector_is_dupes(self):
        """Findings have detector='dupes'."""
        entries = [self._make_entry()]
        results = make_dupe_findings(entries, _noop_log)
        assert results[0]["detector"] == "dupes"


# ── add_structural_signal / merge_structural_signals ─────────


class TestStructuralSignals:
    def test_add_structural_signal_creates_entry(self):
        """add_structural_signal creates a new file entry."""
        structural = {}
        add_structural_signal(
            structural, "/proj/big.py", "large (600 LOC)", {"loc": 600}
        )
        # The key may be resolved, but the data should be present
        assert len(structural) == 1
        entry = list(structural.values())[0]
        assert "large (600 LOC)" in entry["signals"]
        assert entry["detail"]["loc"] == 600

    def test_add_structural_signal_accumulates(self):
        """Multiple signals for the same file accumulate."""
        structural = {}
        filepath = "/proj/big.py"
        add_structural_signal(structural, filepath, "large (600 LOC)", {"loc": 600})
        add_structural_signal(
            structural, filepath, "complexity (30)", {"complexity_score": 30}
        )
        entry = list(structural.values())[0]
        assert len(entry["signals"]) == 2
        assert entry["detail"]["loc"] == 600
        assert entry["detail"]["complexity_score"] == 30

    def test_merge_structural_3plus_signals_tier4(self, tmp_path):
        """3+ signals produce tier 4 / high confidence."""
        filepath = str(tmp_path / "god.py")
        (tmp_path / "god.py").write_text("\n".join(["x = 1"] * 100))
        structural = {}
        structural[filepath] = {
            "signals": ["large", "complexity", "god_class"],
            "detail": {"loc": 100},
        }
        results = merge_structural_signals(structural, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 4
        assert results[0]["confidence"] == "high"
        assert "Needs decomposition" in results[0]["summary"]

    def test_merge_structural_1_2_signals_tier3(self, tmp_path):
        """1-2 signals produce tier 3 / medium confidence."""
        filepath = str(tmp_path / "big.py")
        (tmp_path / "big.py").write_text("\n".join(["x = 1"] * 100))
        structural = {}
        structural[filepath] = {
            "signals": ["large", "complexity"],
            "detail": {"loc": 100},
        }
        results = merge_structural_signals(structural, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 3
        assert results[0]["confidence"] == "medium"

    def test_merge_complexity_only_below_min_suppressed(self, tmp_path):
        """Complexity-only findings below complexity_only_min are suppressed."""
        filepath = str(tmp_path / "moderate.py")
        (tmp_path / "moderate.py").write_text("\n".join(["x = 1"] * 100))
        structural = {}
        structural[filepath] = {
            "signals": ["complexity (20)"],
            "detail": {"loc": 100, "complexity_score": 20},
        }
        messages, log = _capture_log()
        results = merge_structural_signals(structural, log, complexity_only_min=35)
        assert len(results) == 0
        assert any("below threshold" in m for m in messages)

    def test_merge_complexity_only_above_min_not_suppressed(self, tmp_path):
        """Complexity-only findings at or above complexity_only_min pass through."""
        filepath = str(tmp_path / "complex.py")
        (tmp_path / "complex.py").write_text("\n".join(["x = 1"] * 100))
        structural = {}
        structural[filepath] = {
            "signals": ["complexity (40)"],
            "detail": {"loc": 100, "complexity_score": 40},
        }
        results = merge_structural_signals(
            structural, _noop_log, complexity_only_min=35
        )
        assert len(results) == 1

    def test_merge_empty_structural(self):
        """Empty structural dict produces empty results."""
        results = merge_structural_signals({}, _noop_log)
        assert results == []


# ── make_smell_findings ──────────────────────────────────────


class TestMakeSmellFindings:
    def test_high_severity_tier2(self):
        """High severity smells produce tier 2 findings."""
        entries = [
            {
                "id": "eval_exec",
                "label": "eval/exec usage",
                "severity": "high",
                "count": 2,
                "files": 1,
                "matches": [
                    {"file": "/proj/a.py", "line": 10, "content": "eval(x)"},
                    {"file": "/proj/a.py", "line": 20, "content": "exec(y)"},
                ],
            }
        ]
        results = make_smell_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 2
        assert results[0]["confidence"] == "medium"

    def test_medium_severity_tier3(self):
        """Medium severity smells produce tier 3 findings."""
        entries = [
            {
                "id": "todo",
                "label": "TODO comment",
                "severity": "medium",
                "count": 1,
                "files": 1,
                "matches": [{"file": "/proj/a.py", "line": 5, "content": "# TODO"}],
            }
        ]
        results = make_smell_findings(entries, _noop_log)
        assert results[0]["tier"] == 3

    def test_low_severity_low_confidence(self):
        """Low severity smells get low confidence."""
        entries = [
            {
                "id": "magic_number",
                "label": "Magic number",
                "severity": "low",
                "count": 1,
                "files": 1,
                "matches": [{"file": "/proj/a.py", "line": 5, "content": "x = 42"}],
            }
        ]
        results = make_smell_findings(entries, _noop_log)
        assert results[0]["confidence"] == "low"
        assert results[0]["tier"] == 3

    def test_grouped_by_file(self):
        """Matches across multiple files produce separate findings."""
        entries = [
            {
                "id": "eval_exec",
                "label": "eval/exec",
                "severity": "high",
                "count": 3,
                "files": 2,
                "matches": [
                    {"file": "/proj/a.py", "line": 10, "content": "eval(x)"},
                    {"file": "/proj/a.py", "line": 20, "content": "eval(y)"},
                    {"file": "/proj/b.py", "line": 5, "content": "exec(z)"},
                ],
            }
        ]
        results = make_smell_findings(entries, _noop_log)
        assert len(results) == 2  # One per file

    def test_empty_entries(self):
        """Empty entries produce empty results."""
        results = make_smell_findings([], _noop_log)
        assert results == []

    def test_detail_contains_smell_info(self):
        """Finding detail has smell_id, severity, count, lines."""
        entries = [
            {
                "id": "eval_exec",
                "label": "eval usage",
                "severity": "high",
                "count": 1,
                "files": 1,
                "matches": [{"file": "/proj/a.py", "line": 10, "content": "eval(x)"}],
            }
        ]
        results = make_smell_findings(entries, _noop_log)
        d = results[0]["detail"]
        assert d["smell_id"] == "eval_exec"
        assert d["severity"] == "high"
        assert d["count"] == 1
        assert d["lines"] == [10]


# ── make_cycle_findings ──────────────────────────────────────


class TestMakeCycleFindings:
    def test_short_cycle_tier3(self):
        """Cycles of length <= 3 produce tier 3."""
        entries = [{"files": ["/proj/a.py", "/proj/b.py", "/proj/c.py"], "length": 3}]
        results = make_cycle_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 3
        assert results[0]["confidence"] == "high"

    def test_long_cycle_tier4(self):
        """Cycles of length > 3 produce tier 4."""
        files = [f"/proj/{c}.py" for c in "abcde"]
        entries = [{"files": files, "length": 5}]
        results = make_cycle_findings(entries, _noop_log)
        assert results[0]["tier"] == 4

    def test_empty_entries(self):
        """Empty entries produce empty results."""
        results = make_cycle_findings([], _noop_log)
        assert results == []

    def test_summary_contains_cycle_info(self):
        """Summary mentions cycle length and file names."""
        entries = [{"files": ["/proj/a.py", "/proj/b.py"], "length": 2}]
        results = make_cycle_findings(entries, _noop_log)
        assert "Import cycle (2 files)" in results[0]["summary"]

    def test_long_cycle_name_truncated(self):
        """Cycles >4 files have '+N' in the ID name."""
        files = [f"/proj/{chr(97 + i)}.py" for i in range(6)]
        entries = [{"files": files, "length": 6}]
        results = make_cycle_findings(entries, _noop_log)
        assert "+2" in results[0]["id"]


# ── make_orphaned_findings ───────────────────────────────────


class TestMakeOrphanedFindings:
    def test_produces_tier3_medium(self):
        """Orphaned files produce tier 3 / medium findings."""
        entries = [{"file": "/proj/orphan.py", "loc": 150}]
        results = make_orphaned_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 3
        assert results[0]["confidence"] == "medium"
        assert "Orphaned file" in results[0]["summary"]
        assert "150 LOC" in results[0]["summary"]

    def test_empty_entries(self):
        """Empty entries produce empty results."""
        results = make_orphaned_findings([], _noop_log)
        assert results == []


# ── make_single_use_findings ─────────────────────────────────


class TestMakeSingleUseFindings:
    def _make_entries(self, loc=300):
        return [{"file": "/proj/utils.py", "loc": loc, "sole_importer": "app/main.py"}]

    def test_outside_loc_range_produces_finding(self):
        """Files outside the suppression LOC range produce findings."""
        entries = self._make_entries(loc=300)
        results = make_single_use_findings(
            entries,
            get_area=None,
            loc_range=(50, 200),
            suppress_colocated=False,
            stderr_fn=_noop_log,
        )
        assert len(results) == 1
        assert results[0]["tier"] == 3

    def test_within_loc_range_suppressed(self):
        """Files within the LOC range are suppressed (appropriate abstractions)."""
        entries = self._make_entries(loc=100)
        results = make_single_use_findings(
            entries,
            get_area=None,
            loc_range=(50, 200),
            suppress_colocated=False,
            stderr_fn=_noop_log,
        )
        assert len(results) == 0

    def test_colocated_suppressed(self):
        """Co-located files are suppressed when suppress_colocated=True."""
        entries = self._make_entries(loc=300)

        def same_area(path):
            return "shared"

        results = make_single_use_findings(
            entries,
            get_area=same_area,
            loc_range=(50, 200),
            suppress_colocated=True,
            stderr_fn=_noop_log,
        )
        assert len(results) == 0

    def test_different_areas_not_suppressed(self):
        """Files in different areas are not suppressed."""
        entries = self._make_entries(loc=300)
        areas = {"utils.py": "utils", "app/main.py": "app"}

        def get_area(path):
            return areas.get(path, "unknown")

        results = make_single_use_findings(
            entries,
            get_area=get_area,
            loc_range=(50, 200),
            suppress_colocated=True,
            stderr_fn=_noop_log,
        )
        assert len(results) == 1

    def test_skip_dir_names(self):
        """Files in skip_dir_names directories are suppressed."""
        entries = [
            {"file": "/proj/commands/run.py", "loc": 300, "sole_importer": "main.py"}
        ]
        results = make_single_use_findings(
            entries,
            get_area=None,
            loc_range=(50, 200),
            suppress_colocated=False,
            skip_dir_names={"commands"},
            stderr_fn=_noop_log,
        )
        assert len(results) == 0

    def test_empty_entries(self):
        """Empty entries produce empty results."""
        results = make_single_use_findings(
            [],
            get_area=None,
            suppress_colocated=False,
            stderr_fn=_noop_log,
        )
        assert results == []


# ── make_passthrough_findings ────────────────────────────────


class TestMakePassthroughFindings:
    def test_produces_findings_with_correct_fields(self):
        """Passthrough entries produce props findings with correct structure."""
        entries = [
            {
                "file": "/proj/component.tsx",
                "component": "Wrapper",
                "total_props": 10,
                "passthrough": 8,
                "ratio": 0.8,
                "tier": 4,
                "confidence": "high",
                "line": 15,
            }
        ]
        results = make_passthrough_findings(
            entries,
            name_key="component",
            total_key="total_props",
            stderr_fn=_noop_log,
        )
        assert len(results) == 1
        assert results[0]["detector"] == "props"
        assert "Passthrough: Wrapper" in results[0]["summary"]
        assert "8/10 forwarded" in results[0]["summary"]
        assert "80%" in results[0]["summary"]

    def test_empty_entries(self):
        """Empty entries produce empty results."""
        results = make_passthrough_findings(
            [],
            name_key="component",
            total_key="total_props",
            stderr_fn=_noop_log,
        )
        assert results == []


# ── make_facade_findings ─────────────────────────────────────


class TestMakeFacadeFindings:
    def test_file_facade(self):
        """File-kind facades produce T2 findings with re-export summary."""
        entries = [
            {
                "file": "/proj/index.ts",
                "kind": "file",
                "loc": 50,
                "importers": 3,
                "imports_from": ["./utils", "./helpers"],
            }
        ]
        results = make_facade_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["tier"] == 2
        assert results[0]["confidence"] == "medium"  # importers > 0
        assert "Re-export facade" in results[0]["summary"]

    def test_directory_facade(self):
        """Directory-kind facades mention file count."""
        entries = [
            {
                "file": "/proj/shared/",
                "kind": "directory",
                "loc": 200,
                "importers": 0,
                "imports_from": [],
                "file_count": 5,
            }
        ]
        results = make_facade_findings(entries, _noop_log)
        assert len(results) == 1
        assert results[0]["confidence"] == "high"  # importers == 0
        assert "Facade directory" in results[0]["summary"]
        assert "5 files" in results[0]["summary"]

    def test_zero_importers_high_confidence(self):
        """Zero importers get high confidence (dead facade)."""
        entries = [
            {
                "file": "/proj/index.ts",
                "kind": "file",
                "loc": 30,
                "importers": 0,
                "imports_from": ["./a"],
            }
        ]
        results = make_facade_findings(entries, _noop_log)
        assert results[0]["confidence"] == "high"

    def test_empty_entries(self):
        """Empty entries produce empty results."""
        results = make_facade_findings([], _noop_log)
        assert results == []


# ── SMELL_TIER_MAP ───────────────────────────────────────────


def test_smell_tier_map_values():
    """SMELL_TIER_MAP has expected severity->tier mappings."""
    assert SMELL_TIER_MAP["high"] == 2
    assert SMELL_TIER_MAP["medium"] == 3
    assert SMELL_TIER_MAP["low"] == 3
