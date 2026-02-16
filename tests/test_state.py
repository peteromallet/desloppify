"""Tests for desloppify.state — finding lifecycle, persistence, and merge logic."""

import json
from pathlib import Path

import pytest

from desloppify import state as state_mod
from desloppify.state import (
    _empty_state,
    _upsert_findings,
    load_state,
    make_finding,
    save_state,
    suppression_metrics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_finding(fid, *, detector="det", file="a.py", tier=3,
                      confidence="medium", summary="s", status="open",
                      lang=None, zone=None):
    """Build a minimal finding dict with explicit ID (bypasses rel())."""
    now = "2025-01-01T00:00:00+00:00"
    f = {
        "id": fid, "detector": detector, "file": file, "tier": tier,
        "confidence": confidence, "summary": summary, "detail": {},
        "status": status, "note": None, "first_seen": now, "last_seen": now,
        "resolved_at": None, "reopen_count": 0,
    }
    if lang:
        f["lang"] = lang
    if zone:
        f["zone"] = zone
    return f


# ---------------------------------------------------------------------------
# make_finding
# ---------------------------------------------------------------------------

class TestMakeFinding:
    """make_finding creates a normalised finding dict with a stable ID."""

    def test_id_includes_name(self, monkeypatch):
        monkeypatch.setattr(state_mod, "rel", lambda p: p)
        f = make_finding("dead_code", "src/foo.py", "bar",
                         tier=2, confidence="high", summary="unused")
        assert f["id"] == "dead_code::src/foo.py::bar"

    def test_id_excludes_name_when_empty(self, monkeypatch):
        monkeypatch.setattr(state_mod, "rel", lambda p: p)
        f = make_finding("lint", "src/foo.py", "",
                         tier=3, confidence="low", summary="lint issue")
        assert f["id"] == "lint::src/foo.py"

    def test_detail_defaults_to_empty_dict(self, monkeypatch):
        monkeypatch.setattr(state_mod, "rel", lambda p: p)
        f = make_finding("x", "a.py", "y", tier=1, confidence="high", summary="s")
        assert f["detail"] == {}

    def test_detail_passed_through(self, monkeypatch):
        monkeypatch.setattr(state_mod, "rel", lambda p: p)
        d = {"lines": [1, 2, 3]}
        f = make_finding("x", "a.py", "y", tier=1, confidence="high",
                         summary="s", detail=d)
        assert f["detail"] is d

    def test_default_field_values(self, monkeypatch):
        monkeypatch.setattr(state_mod, "rel", lambda p: p)
        f = make_finding("d", "f.py", "n", tier=2, confidence="medium", summary="sum")
        assert f["status"] == "open"
        assert f["note"] is None
        assert f["resolved_at"] is None
        assert f["reopen_count"] == 0
        assert f["first_seen"] == f["last_seen"]
        assert f["detector"] == "d"
        assert f["file"] == "f.py"
        assert f["tier"] == 2
        assert f["confidence"] == "medium"
        assert f["summary"] == "sum"


# ---------------------------------------------------------------------------
# _empty_state
# ---------------------------------------------------------------------------

class TestEmptyState:
    def test_structure(self):
        s = _empty_state()
        assert s["version"] == 1
        assert s["last_scan"] is None
        assert s["scan_count"] == 0
        assert "config" not in s  # config moved to config.json
        assert s["overall_score"] == 0
        assert s["objective_score"] == 0
        assert s["strict_score"] == 0
        assert s["stats"] == {}
        assert s["findings"] == {}
        assert "created" in s


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------

class TestLoadState:
    def test_nonexistent_file_returns_empty_state(self, tmp_path):
        s = load_state(tmp_path / "missing.json")
        assert s["version"] == 1
        assert s["findings"] == {}

    def test_valid_json_returns_parsed_data(self, tmp_path):
        p = tmp_path / "state.json"
        data = {"version": 1, "hello": "world"}
        p.write_text(json.dumps(data))
        s = load_state(p)
        assert s["hello"] == "world"

    def test_corrupt_json_tries_backup(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{bad json!!")
        backup = tmp_path / "state.json.bak"
        backup_data = {"version": 1, "source": "backup"}
        backup.write_text(json.dumps(backup_data))

        s = load_state(p)
        assert s["source"] == "backup"

    def test_corrupt_json_no_backup_returns_empty(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{bad json!!")
        s = load_state(p)
        assert s["version"] == 1
        assert s["findings"] == {}

    def test_corrupt_json_renames_file(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{bad json!!")
        load_state(p)
        assert (tmp_path / "state.json.corrupted").exists()

    def test_corrupt_json_and_corrupt_backup_returns_empty(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{bad")
        backup = tmp_path / "state.json.bak"
        backup.write_text("{also bad")

        s = load_state(p)
        assert s["version"] == 1
        assert s["findings"] == {}


# ---------------------------------------------------------------------------
# save_state
# ---------------------------------------------------------------------------

class TestSaveState:
    def test_creates_file_and_writes_valid_json(self, tmp_path):
        p = tmp_path / "sub" / "state.json"
        st = _empty_state()
        save_state(st, p)
        assert p.exists()
        loaded = json.loads(p.read_text())
        assert loaded["version"] == 1

    def test_creates_backup_of_previous(self, tmp_path):
        p = tmp_path / "state.json"
        # First save
        st = _empty_state()
        save_state(st, p)
        original_content = p.read_text()

        # Second save with different data
        st["scan_count"] = 42
        save_state(st, p)

        backup = tmp_path / "state.json.bak"
        assert backup.exists()
        backup_data = json.loads(backup.read_text())
        # Backup should be the *previous* save (before scan_count=42 was added
        # but after _recompute_stats ran on the first save).
        original_data = json.loads(original_content)
        assert backup_data["version"] == original_data["version"]

    def test_atomic_write_produces_valid_json(self, tmp_path):
        """Even with special types (sets, Paths), the output is valid JSON."""
        p = tmp_path / "state.json"
        st = _empty_state()
        st["findings"] = {}
        st["custom_set"] = {3, 1, 2}
        st["custom_path"] = Path("/tmp/hello")
        save_state(st, p)
        loaded = json.loads(p.read_text())
        assert loaded["custom_set"] == [1, 2, 3]  # sorted
        assert loaded["custom_path"] == "/tmp/hello"


# ---------------------------------------------------------------------------
# _upsert_findings
# ---------------------------------------------------------------------------

class TestUpsertFindings:
    """_upsert_findings merges a scan's findings into existing state."""

    def _call(self, existing, current, *, ignore=None, lang=None):
        now = "2025-06-01T00:00:00+00:00"
        return _upsert_findings(existing, current, ignore or [], now, lang=lang)

    # -- new findings --

    def test_new_finding_gets_added(self):
        existing = {}
        f = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        ids, new, reopened, by_det, _ign = self._call(existing, [f])
        assert "det::a.py::fn" in existing
        assert new == 1
        assert reopened == 0
        assert "det::a.py::fn" in ids

    # -- existing open finding --

    def test_existing_open_finding_updated_last_seen(self):
        old = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        old["last_seen"] = "2025-01-01T00:00:00+00:00"
        existing = {"det::a.py::fn": old}

        current = _make_raw_finding("det::a.py::fn", detector="det", file="a.py",
                                     summary="updated summary")
        ids, new, reopened, _, _ign = self._call(existing, [current])
        assert new == 0
        assert reopened == 0
        assert existing["det::a.py::fn"]["last_seen"] == "2025-06-01T00:00:00+00:00"
        assert existing["det::a.py::fn"]["summary"] == "updated summary"

    # -- resolved finding gets reopened --

    def test_resolved_finding_gets_reopened(self):
        old = _make_raw_finding("det::a.py::fn", detector="det", file="a.py",
                                status="auto_resolved")
        old["resolved_at"] = "2025-03-01T00:00:00+00:00"
        existing = {"det::a.py::fn": old}

        current = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        ids, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 1
        assert new == 0
        assert existing["det::a.py::fn"]["status"] == "open"
        assert existing["det::a.py::fn"]["reopen_count"] == 1
        assert existing["det::a.py::fn"]["resolved_at"] is None
        assert "Reopened" in existing["det::a.py::fn"]["note"]

    def test_fixed_finding_gets_reopened(self):
        old = _make_raw_finding("det::a.py::fn", detector="det", file="a.py",
                                status="fixed")
        old["resolved_at"] = "2025-03-01T00:00:00+00:00"
        existing = {"det::a.py::fn": old}

        current = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        ids, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 1
        assert existing["det::a.py::fn"]["status"] == "open"
        assert "was fixed" in existing["det::a.py::fn"]["note"]

    def test_reopen_increments_count(self):
        old = _make_raw_finding("det::a.py::fn", detector="det", file="a.py",
                                status="auto_resolved")
        old["reopen_count"] = 2
        existing = {"det::a.py::fn": old}

        current = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        self._call(existing, [current])
        assert existing["det::a.py::fn"]["reopen_count"] == 3

    # -- wontfix finding is NOT reopened --

    def test_wontfix_finding_not_reopened(self):
        old = _make_raw_finding("det::a.py::fn", detector="det", file="a.py",
                                status="wontfix")
        existing = {"det::a.py::fn": old}

        current = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        _, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 0
        assert existing["det::a.py::fn"]["status"] == "wontfix"

    # -- zone propagation --

    def test_zone_propagated_on_existing(self):
        old = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        existing = {"det::a.py::fn": old}

        current = _make_raw_finding("det::a.py::fn", detector="det", file="a.py",
                                     zone="production")
        self._call(existing, [current])
        assert existing["det::a.py::fn"]["zone"] == "production"

    # -- ignored findings --

    def test_ignored_finding_not_added(self):
        existing = {}
        f = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        ids, new, _, _, ignored = self._call(existing, [f], ignore=["det::*"])
        assert new == 0
        assert len(existing) == 0
        assert ignored == 1

    # -- lang tagging --

    def test_lang_set_on_new_finding(self):
        existing = {}
        f = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        self._call(existing, [f], lang="python")
        assert existing["det::a.py::fn"]["lang"] == "python"

    # -- by_detector counting --

    def test_by_detector_counts(self):
        f1 = _make_raw_finding("det_a::a.py::x", detector="det_a", file="a.py")
        f2 = _make_raw_finding("det_a::b.py::y", detector="det_a", file="b.py")
        f3 = _make_raw_finding("det_b::c.py::z", detector="det_b", file="c.py")
        _, _, _, by_det, _ign = self._call({}, [f1, f2, f3])
        assert by_det == {"det_a": 2, "det_b": 1}


# ---------------------------------------------------------------------------
# Integration: _upsert_findings used via merge_scan resolves missing findings
# ---------------------------------------------------------------------------

class TestMissingFindingsResolved:
    """Findings present in state but absent from scan get auto-resolved
    (tested via merge_scan which calls _auto_resolve_disappeared)."""

    def test_missing_finding_auto_resolved(self):
        """A finding that existed before but is absent from the new scan
        should be auto-resolved."""
        st = _empty_state()
        old = _make_raw_finding("det::a.py::fn", detector="det", file="a.py")
        old["lang"] = "python"
        st["findings"]["det::a.py::fn"] = old

        # Merge an empty scan — the old finding should disappear
        from desloppify.state import merge_scan
        diff = merge_scan(st, [], lang="python", force_resolve=True)
        assert diff["auto_resolved"] >= 1
        assert st["findings"]["det::a.py::fn"]["status"] == "auto_resolved"
        assert st["findings"]["det::a.py::fn"]["resolved_at"] is not None


# ---------------------------------------------------------------------------
# #53: Wontfix auto-resolution via potentials (ran_detectors)
# ---------------------------------------------------------------------------

class TestWontfixAutoResolution:
    """Wontfix findings should be auto-resolved when the detector ran
    (appears in potentials) but produced 0 findings for those files (#53)."""

    def test_wontfix_resolved_when_detector_ran(self):
        """Wontfix findings auto-resolve when detector is in potentials."""
        from desloppify.state import merge_scan
        st = _empty_state()
        # Pre-populate 3 open + 2 wontfix test_coverage findings
        for i in range(3):
            f = _make_raw_finding(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage", file=f"mod{i}.py", lang="python")
            st["findings"][f["id"]] = f
        for i in range(3, 5):
            f = _make_raw_finding(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage", file=f"mod{i}.py",
                status="wontfix", lang="python")
            st["findings"][f["id"]] = f

        # Simulate: user wrote tests for ALL files → 0 findings
        # test_coverage ran (in potentials) but found nothing
        diff = merge_scan(st, [], lang="python",
                          potentials={"test_coverage": 50, "smells": 100})
        assert diff["auto_resolved"] == 5
        for fid, finding in st["findings"].items():
            assert finding["status"] == "auto_resolved"

    def test_wontfix_not_resolved_when_detector_suspect(self):
        """Wontfix findings survive when detector didn't run (not in potentials)."""
        from desloppify.state import merge_scan
        st = _empty_state()
        # 4 open findings (>=3 triggers suspect detection)
        for i in range(4):
            f = _make_raw_finding(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage", file=f"mod{i}.py", lang="python")
            st["findings"][f["id"]] = f
        # 1 wontfix finding
        wf = _make_raw_finding(
            "test_coverage::mod4.py::untested_module",
            detector="test_coverage", file="mod4.py",
            status="wontfix", lang="python")
        st["findings"][wf["id"]] = wf

        # test_coverage NOT in potentials → suspect → wontfix preserved
        diff = merge_scan(st, [], lang="python",
                          potentials={"smells": 100})
        assert "test_coverage" in diff["suspect_detectors"]
        assert st["findings"]["test_coverage::mod4.py::untested_module"]["status"] == "wontfix"

    def test_wontfix_resolved_when_some_findings_remain(self):
        """Wontfix findings for fixed files are resolved even when other
        findings remain (detector not suspect because it produced findings)."""
        from desloppify.state import merge_scan
        st = _empty_state()
        # 2 wontfix + 2 open
        for i in range(2):
            f = _make_raw_finding(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage", file=f"mod{i}.py",
                status="wontfix", lang="python")
            st["findings"][f["id"]] = f
        for i in range(2, 4):
            f = _make_raw_finding(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage", file=f"mod{i}.py", lang="python")
            st["findings"][f["id"]] = f

        # User wrote tests for wontfix files only — 2 findings remain (open ones)
        current = [
            _make_raw_finding(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage", file=f"mod{i}.py")
            for i in range(2, 4)
        ]
        diff = merge_scan(st, current, lang="python",
                          potentials={"test_coverage": 50})
        # The 2 wontfix findings should be auto-resolved
        assert st["findings"]["test_coverage::mod0.py::untested_module"]["status"] == "auto_resolved"
        assert st["findings"]["test_coverage::mod1.py::untested_module"]["status"] == "auto_resolved"
        # The 2 open findings should still be open (they were re-emitted)
        assert st["findings"]["test_coverage::mod2.py::untested_module"]["status"] == "open"
        assert st["findings"]["test_coverage::mod3.py::untested_module"]["status"] == "open"

    def test_empty_potentials_dict_not_treated_as_none(self):
        """Empty potentials {} means 'scan ran but no detectors reported' —
        should not mark detectors suspect just because dict is falsy."""
        from desloppify.state import merge_scan, _find_suspect_detectors
        # Build a state with 3 open findings for a detector
        existing = {}
        for i in range(3):
            f = _make_raw_finding(
                f"det::mod{i}.py::x", detector="det", file=f"mod{i}.py")
            existing[f["id"]] = f
        # Empty potentials {} — ran_detectors should be set() not None
        suspect = _find_suspect_detectors(existing, {}, False, ran_detectors=set())
        # det had 3 open, returned 0, but set() means "ran" info was provided
        # Since det is NOT in ran_detectors=set(), it IS suspect
        assert "det" in suspect

    def test_potentials_none_means_no_info(self):
        """potentials=None means no ran_detectors info at all."""
        from desloppify.state import _find_suspect_detectors
        existing = {}
        for i in range(3):
            f = _make_raw_finding(
                f"det::mod{i}.py::x", detector="det", file=f"mod{i}.py")
            existing[f["id"]] = f
        suspect = _find_suspect_detectors(existing, {}, False, ran_detectors=None)
        assert "det" in suspect

    def test_merge_potentials_preserves_existing_detector_counts(self):
        """merge_potentials=True should update only provided detector keys."""
        from desloppify.state import merge_scan

        st = _empty_state()
        st["potentials"] = {"python": {"unused": 10, "smells": 20}}

        merge_scan(
            st,
            [],
            lang="python",
            potentials={"review": 3},
            merge_potentials=True,
            force_resolve=True,
        )

        pots = st["potentials"]["python"]
        assert pots["unused"] == 10
        assert pots["smells"] == 20
        assert pots["review"] == 3

    def test_zero_active_checks_defaults_objective_to_neutral(self):
        """When all detector potentials are zero and no assessments exist,
        objective health should be neutral (100) rather than 0."""
        from desloppify.state import merge_scan

        st = _empty_state()
        merge_scan(
            st,
            [],
            lang="typescript",
            potentials={"logs": 0, "unused": 0, "subjective_review": 0},
            force_resolve=True,
        )

        assert st["objective_score"] == 100.0
        assert st["strict_score"] == 100.0
        assert st["overall_score"] == 100.0
        assert st["dimension_scores"] == {}

    def test_zero_active_checks_with_assessments_keeps_subjective_scoring(self):
        """Subjective assessments should still drive objective score when present."""
        from desloppify.state import merge_scan

        st = _empty_state()
        st["subjective_assessments"] = {"naming_quality": {"score": 40}}
        merge_scan(
            st,
            [],
            lang="typescript",
            potentials={"logs": 0, "unused": 0, "subjective_review": 0},
            force_resolve=True,
        )

        # Objective excludes subjective dimensions; overall/strict include them.
        assert st["objective_score"] == 100.0
        assert st["overall_score"] < 100.0
        assert st["strict_score"] < 100.0


class TestSuppressionAccounting:
    def test_merge_scan_records_ignored_metrics_in_history_and_diff(self):
        from desloppify.state import merge_scan

        st = _empty_state()
        findings = [
            _make_raw_finding("smells::a.py::x", detector="smells", file="a.py"),
            _make_raw_finding("smells::b.py::y", detector="smells", file="b.py"),
            _make_raw_finding("logs::c.py::z", detector="logs", file="c.py"),
        ]

        diff = merge_scan(st, findings, lang="python", ignore=["smells::*"], force_resolve=True)

        assert diff["ignored"] == 2
        assert diff["raw_findings"] == 3
        assert diff["suppressed_pct"] == pytest.approx(66.7, abs=0.1)

        hist = st["scan_history"][-1]
        assert hist["ignored"] == 2
        assert hist["raw_findings"] == 3
        assert hist["suppressed_pct"] == pytest.approx(66.7, abs=0.1)
        assert hist["ignore_patterns"] == 1

    def test_suppression_metrics_aggregates_recent_history(self):
        from desloppify.state import merge_scan

        st = _empty_state()
        merge_scan(
            st,
            [
                _make_raw_finding("smells::a.py::x", detector="smells", file="a.py"),
                _make_raw_finding("logs::b.py::x", detector="logs", file="b.py"),
            ],
            lang="python",
            ignore=["smells::*"],
            force_resolve=True,
        )
        merge_scan(
            st,
            [
                _make_raw_finding("smells::a.py::x", detector="smells", file="a.py"),
                _make_raw_finding("logs::b.py::x", detector="logs", file="b.py"),
                _make_raw_finding("logs::c.py::x", detector="logs", file="c.py"),
            ],
            lang="python",
            ignore=["smells::*"],
            force_resolve=True,
        )

        sup = suppression_metrics(st, window=5)
        assert sup["last_ignored"] == 1
        assert sup["last_raw_findings"] == 3
        assert sup["recent_scans"] == 2
        assert sup["recent_ignored"] == 2
        assert sup["recent_raw_findings"] == 5
        assert sup["recent_suppressed_pct"] == 40.0
