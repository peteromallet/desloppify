"""Tests for desloppify.state — issue lifecycle, persistence, and merge logic."""

import json
from pathlib import Path


from desloppify.engine._state import filtering as state_query_mod
from desloppify.engine._state.issue_semantics import MECHANICAL_DEFECT, SCAN_ORIGIN
from desloppify.engine._state.schema import CURRENT_VERSION
from desloppify.state import (
    MergeScanOptions,
    apply_issue_noise_budget,
    empty_state,
    ensure_state_defaults,
    load_state,
    make_issue,
    resolve_issue_noise_budget,
    resolve_issue_noise_global_budget,
    resolve_issue_noise_settings,
    save_state,
    upsert_issues,
    validate_state_invariants,
)
from desloppify.state import (
    merge_scan as _merge_scan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def merge_scan(state, current_issues, *args, **kwargs):
    options = kwargs.pop("options", None)
    if args:
        if len(args) != 1:
            raise TypeError("merge_scan test helper accepts at most one positional option")
        options = args[0]
    if options is None:
        options = MergeScanOptions(**kwargs)
    return _merge_scan(state, current_issues, options=options)


def _make_raw_issue(
    fid,
    *,
    detector="det",
    file="a.py",
    tier=3,
    confidence="medium",
    summary="s",
    status="open",
    lang=None,
    zone=None,
):
    """Build a minimal issue dict with explicit ID (bypasses rel())."""
    now = "2025-01-01T00:00:00+00:00"
    f = {
        "id": fid,
        "detector": detector,
        "file": file,
        "tier": tier,
        "confidence": confidence,
        "summary": summary,
        "detail": {},
        "status": status,
        "note": None,
        "first_seen": now,
        "last_seen": now,
        "resolved_at": None,
        "reopen_count": 0,
    }
    if lang:
        f["lang"] = lang
    if zone:
        f["zone"] = zone
    return f


# ---------------------------------------------------------------------------
# apply_issue_noise_budget
# ---------------------------------------------------------------------------


class TestApplyIssueNoiseBudget:
    def test_budget_zero_keeps_all(self):
        issues = [
            _make_raw_issue("unused::a.py::x", detector="unused"),
            _make_raw_issue("unused::b.py::y", detector="unused"),
        ]
        surfaced, hidden = apply_issue_noise_budget(issues, budget=0)
        assert len(surfaced) == 2
        assert hidden == {}

    def test_caps_per_detector_and_reports_hidden(self):
        issues = [
            _make_raw_issue("unused::a.py::x", detector="unused"),
            _make_raw_issue("unused::b.py::y", detector="unused"),
            _make_raw_issue("unused::c.py::z", detector="unused"),
            _make_raw_issue("smells::d.py::w", detector="smells"),
        ]
        surfaced, hidden = apply_issue_noise_budget(issues, budget=2)
        assert len(surfaced) == 3
        assert hidden == {"unused": 1}

    def test_global_budget_round_robins_across_detectors(self):
        issues = [
            _make_raw_issue(
                "unused::a.py::x1", detector="unused", tier=1, confidence="high"
            ),
            _make_raw_issue(
                "unused::a.py::x2", detector="unused", tier=1, confidence="high"
            ),
            _make_raw_issue(
                "unused::a.py::x3", detector="unused", tier=1, confidence="high"
            ),
            _make_raw_issue(
                "smells::b.py::y1", detector="smells", tier=2, confidence="medium"
            ),
            _make_raw_issue(
                "smells::b.py::y2", detector="smells", tier=2, confidence="medium"
            ),
        ]
        surfaced, hidden = apply_issue_noise_budget(
            issues, budget=0, global_budget=3
        )
        detectors = [f["detector"] for f in surfaced]
        assert detectors.count("unused") == 2
        assert detectors.count("smells") == 1
        assert hidden == {"smells": 1, "unused": 1}


# ---------------------------------------------------------------------------
# resolve_issue_noise_budget
# ---------------------------------------------------------------------------


class TestResolveIssueNoiseBudget:
    def test_uses_default_when_config_missing(self):
        assert resolve_issue_noise_budget(None) == 10

    def test_reads_valid_int_from_config(self):
        assert resolve_issue_noise_budget({"issue_noise_budget": 25}) == 25

    def test_invalid_value_falls_back_to_default(self):
        assert resolve_issue_noise_budget({"issue_noise_budget": "oops"}) == 10

    def test_negative_value_clamps_to_zero(self):
        assert resolve_issue_noise_budget({"issue_noise_budget": -5}) == 0


class TestResolveIssueNoiseGlobalBudget:
    def test_uses_default_when_config_missing(self):
        assert resolve_issue_noise_global_budget(None) == 0

    def test_reads_valid_int_from_config(self):
        assert (
            resolve_issue_noise_global_budget({"issue_noise_global_budget": 25})
            == 25
        )

    def test_invalid_value_falls_back_to_default(self):
        assert (
            resolve_issue_noise_global_budget({"issue_noise_global_budget": "oops"})
            == 0
        )

    def test_negative_value_clamps_to_zero(self):
        assert (
            resolve_issue_noise_global_budget({"issue_noise_global_budget": -5})
            == 0
        )


class TestResolveIssueNoiseSettings:
    def test_returns_warning_for_invalid_values(self):
        per, global_budget, warning = resolve_issue_noise_settings(
            {
                "issue_noise_budget": "oops",
                "issue_noise_global_budget": -2,
            }
        )
        assert per == 10
        assert global_budget == 0
        assert warning is not None
        assert "issue_noise_budget" in warning
        assert "issue_noise_global_budget" in warning


# ---------------------------------------------------------------------------
# make_issue
# ---------------------------------------------------------------------------


class TestMakeIssue:
    """make_issue creates a normalised issue dict with a stable ID."""

    def test_id_includes_name(self, monkeypatch):
        monkeypatch.setattr(state_query_mod, "rel", lambda p: p)
        f = make_issue(
            "dead_code",
            "src/foo.py",
            "bar",
            tier=2,
            confidence="high",
            summary="unused",
        )
        assert f["id"] == "dead_code::src/foo.py::bar"

    def test_id_excludes_name_when_empty(self, monkeypatch):
        monkeypatch.setattr(state_query_mod, "rel", lambda p: p)
        f = make_issue(
            "lint", "src/foo.py", "", tier=3, confidence="low", summary="lint issue"
        )
        assert f["id"] == "lint::src/foo.py"

    def test_detail_defaults_to_empty_dict(self, monkeypatch):
        monkeypatch.setattr(state_query_mod, "rel", lambda p: p)
        f = make_issue("x", "a.py", "y", tier=1, confidence="high", summary="s")
        assert f["detail"] == {}

    def test_detail_passed_through(self, monkeypatch):
        monkeypatch.setattr(state_query_mod, "rel", lambda p: p)
        d = {"lines": [1, 2, 3]}
        f = make_issue(
            "x", "a.py", "y", tier=1, confidence="high", summary="s", detail=d
        )
        assert f["detail"] is d

    def test_default_field_values(self, monkeypatch):
        monkeypatch.setattr(state_query_mod, "rel", lambda p: p)
        f = make_issue("d", "f.py", "n", tier=2, confidence="medium", summary="sum")
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
        assert f["issue_kind"] == MECHANICAL_DEFECT
        assert f["origin"] == SCAN_ORIGIN


# ---------------------------------------------------------------------------
# _empty_state
# ---------------------------------------------------------------------------


class TestEmptyState:
    def test_structure(self):
        s = empty_state()
        assert s["version"] == CURRENT_VERSION
        assert s["last_scan"] is None
        assert s["scan_count"] == 0
        assert "config" not in s  # config moved to config.json
        assert s["overall_score"] == 0
        assert s["objective_score"] == 0
        assert s["strict_score"] == 0
        assert s["stats"] == {}
        assert s["issues"] == {}
        assert s["subjective_integrity"] == {}
        assert "created" in s


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------


class TestLoadState:
    def test_nonexistent_file_returns_empty_state(self, tmp_path):
        s = load_state(tmp_path / "missing.json")
        assert s["version"] == CURRENT_VERSION
        assert s["issues"] == {}

    def test_valid_json_returns_parsed_data(self, tmp_path):
        p = tmp_path / "state.json"
        data = {"version": 1, "hello": "world"}
        p.write_text(json.dumps(data))
        s = load_state(p)
        assert s["hello"] == "world"
        validate_state_invariants(s)

    def test_legacy_payload_gets_normalized(self, tmp_path):
        p = tmp_path / "state.json"
        # Legacy/minimal state payload with missing keys.
        p.write_text(
            json.dumps({"version": 1, "issues": {"x": {"id": "x", "tier": 3}}})
        )
        s = load_state(p)
        assert s["scan_count"] == 0
        assert s["stats"] == {}
        assert s["issues"]["x"]["status"] == "open"
        assert s["issues"]["x"]["issue_kind"] == MECHANICAL_DEFECT
        assert s["issues"]["x"]["origin"] == SCAN_ORIGIN
        validate_state_invariants(s)

    def test_work_items_payload_gets_normalized(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text(
            json.dumps({"version": 2, "work_items": {"x": {"id": "x", "tier": 3}}})
        )
        s = load_state(p)
        assert s["issues"]["x"]["status"] == "open"
        assert s["issues"]["x"]["work_item_kind"] == MECHANICAL_DEFECT
        validate_state_invariants(s)

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
        assert s["version"] == CURRENT_VERSION
        assert s["issues"] == {}

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
        assert s["version"] == CURRENT_VERSION
        assert s["issues"] == {}


# ---------------------------------------------------------------------------
# save_state
# ---------------------------------------------------------------------------


class TestSaveState:
    def test_creates_file_and_writes_valid_json(self, tmp_path):
        p = tmp_path / "sub" / "state.json"
        st = empty_state()
        save_state(st, p)
        assert p.exists()
        loaded = json.loads(p.read_text())
        assert loaded["version"] == CURRENT_VERSION
        assert "work_items" in loaded
        assert "issues" not in loaded

    def test_creates_backup_of_previous(self, tmp_path):
        p = tmp_path / "state.json"
        # First save
        st = empty_state()
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
        st = empty_state()
        st["issues"] = {}
        st["custom_set"] = {3, 1, 2}
        st["custom_path"] = Path("/tmp/hello")
        save_state(st, p)
        loaded = json.loads(p.read_text())
        assert loaded["custom_set"] == [1, 2, 3]  # sorted
        assert loaded["custom_path"] == "/tmp/hello"
        assert "work_items" in loaded

    def test_invalid_status_gets_normalized_before_save(self, tmp_path):
        p = tmp_path / "state.json"
        st = empty_state()
        st["issues"]["x"] = _make_raw_issue("x", status="oops")
        ensure_state_defaults(st)
        save_state(st, p)
        loaded = json.loads(p.read_text())
        assert loaded["work_items"]["x"]["status"] == "open"


# ---------------------------------------------------------------------------
# _upsert_issues
# ---------------------------------------------------------------------------


class TestUpsertIssues:
    """_upsert_issues merges a scan's issues into existing state."""

    def _call(self, existing, current, *, ignore=None, lang=None):
        now = "2025-06-01T00:00:00+00:00"
        result = upsert_issues(existing, current, ignore or [], now, lang=lang)
        return result[:5]  # backward compat — omit changed_detectors

    # -- new issues --

    def test_new_issue_gets_added(self):
        existing = {}
        f = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        ids, new, reopened, by_det, _ign = self._call(existing, [f])
        assert "det::a.py::fn" in existing
        assert new == 1
        assert reopened == 0
        assert "det::a.py::fn" in ids

    # -- existing open issue --

    def test_existing_open_issue_updated_last_seen(self):
        old = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        old["last_seen"] = "2025-01-01T00:00:00+00:00"
        existing = {"det::a.py::fn": old}

        current = _make_raw_issue(
            "det::a.py::fn", detector="det", file="a.py", summary="updated summary"
        )
        ids, new, reopened, _, _ign = self._call(existing, [current])
        assert new == 0
        assert reopened == 0
        assert existing["det::a.py::fn"]["last_seen"] == "2025-06-01T00:00:00+00:00"
        assert existing["det::a.py::fn"]["summary"] == "updated summary"

    # -- resolved issue gets reopened --

    def test_resolved_issue_gets_reopened(self):
        old = _make_raw_issue(
            "det::a.py::fn", detector="det", file="a.py", status="auto_resolved"
        )
        old["resolved_at"] = "2025-03-01T00:00:00+00:00"
        existing = {"det::a.py::fn": old}

        current = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        ids, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 1
        assert new == 0
        assert existing["det::a.py::fn"]["status"] == "open"
        assert existing["det::a.py::fn"]["reopen_count"] == 1
        assert existing["det::a.py::fn"]["resolved_at"] is None
        assert "Reopened" in existing["det::a.py::fn"]["note"]

    def test_fixed_issue_gets_reopened(self):
        old = _make_raw_issue(
            "det::a.py::fn", detector="det", file="a.py", status="fixed"
        )
        old["resolved_at"] = "2025-03-01T00:00:00+00:00"
        existing = {"det::a.py::fn": old}

        current = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        ids, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 1
        assert existing["det::a.py::fn"]["status"] == "open"
        assert "was fixed" in existing["det::a.py::fn"]["note"]

    def test_reopen_increments_count(self):
        old = _make_raw_issue(
            "det::a.py::fn", detector="det", file="a.py", status="auto_resolved"
        )
        old["reopen_count"] = 2
        existing = {"det::a.py::fn": old}

        current = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        self._call(existing, [current])
        assert existing["det::a.py::fn"]["reopen_count"] == 3

    # -- wontfix issue is NOT reopened --

    def test_wontfix_issue_not_reopened(self):
        old = _make_raw_issue(
            "det::a.py::fn", detector="det", file="a.py", status="wontfix"
        )
        existing = {"det::a.py::fn": old}

        current = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        _, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 0
        assert existing["det::a.py::fn"]["status"] == "wontfix"

    # -- zone propagation --

    def test_zone_propagated_on_existing(self):
        old = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        existing = {"det::a.py::fn": old}

        current = _make_raw_issue(
            "det::a.py::fn", detector="det", file="a.py", zone="production"
        )
        self._call(existing, [current])
        assert existing["det::a.py::fn"]["zone"] == "production"

    # -- ignored issues --

    def test_ignored_issue_not_added(self):
        existing = {}
        f = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        ids, new, _, _, ignored = self._call(existing, [f], ignore=["det::*"])
        assert "det::a.py::fn" in ids
        assert new == 0
        assert len(existing) == 1
        assert existing["det::a.py::fn"]["suppressed"] is True
        assert existing["det::a.py::fn"]["status"] == "open"
        assert ignored == 1

    # -- lang tagging --

    def test_lang_set_on_new_issue(self):
        existing = {}
        f = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        self._call(existing, [f], lang="python")
        assert existing["det::a.py::fn"]["lang"] == "python"

    # -- by_detector counting --

    def test_by_detector_counts(self):
        f1 = _make_raw_issue("det_a::a.py::x", detector="det_a", file="a.py")
        f2 = _make_raw_issue("det_a::b.py::y", detector="det_a", file="b.py")
        f3 = _make_raw_issue("det_b::c.py::z", detector="det_b", file="c.py")
        _, _, _, by_det, _ign = self._call({}, [f1, f2, f3])
        assert by_det == {"det_a": 2, "det_b": 1}

    # -- subjective_review reopen guard (#158 / #156) --

    def test_subjective_review_import_fixed_not_reopened(self):
        """subjective_review fixed by import stays fixed when scan echoes it."""
        old = _make_raw_issue(
            "subjective_review::a.py::holistic_stale",
            detector="subjective_review",
            file="a.py",
            status="fixed",
        )
        old["resolution_attestation"] = {
            "kind": "agent_import",
            "text": "Resolved by holistic import",
            "attested_at": "2025-05-01T00:00:00+00:00",
            "scan_verified": False,
        }
        existing = {"subjective_review::a.py::holistic_stale": old}

        current = _make_raw_issue(
            "subjective_review::a.py::holistic_stale",
            detector="subjective_review",
            file="a.py",
        )
        _, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 0
        assert existing["subjective_review::a.py::holistic_stale"]["status"] == "fixed"

    def test_subjective_review_fixed_by_user_still_reopened(self):
        """subjective_review manually fixed DOES reopen (condition persists)."""
        old = _make_raw_issue(
            "subjective_review::a.py::holistic_stale",
            detector="subjective_review",
            file="a.py",
            status="fixed",
        )
        old["resolution_attestation"] = {
            "kind": "manual",
            "text": "User fixed",
            "attested_at": "2025-05-01T00:00:00+00:00",
        }
        existing = {"subjective_review::a.py::holistic_stale": old}

        current = _make_raw_issue(
            "subjective_review::a.py::holistic_stale",
            detector="subjective_review",
            file="a.py",
        )
        _, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 1
        assert existing["subjective_review::a.py::holistic_stale"]["status"] == "open"

    def test_mechanical_auto_resolved_still_reopened(self):
        """Non-subjective auto_resolved issue still reopens normally."""
        old = _make_raw_issue(
            "unused::a.py::x",
            detector="unused",
            file="a.py",
            status="auto_resolved",
        )
        old["resolution_attestation"] = {
            "kind": "scan_verified",
            "text": "Disappeared from scan",
            "attested_at": "2025-05-01T00:00:00+00:00",
            "scan_verified": True,
        }
        existing = {"unused::a.py::x": old}

        current = _make_raw_issue(
            "unused::a.py::x",
            detector="unused",
            file="a.py",
        )
        _, new, reopened, _, _ign = self._call(existing, [current])
        assert reopened == 1
        assert existing["unused::a.py::x"]["status"] == "open"


# ---------------------------------------------------------------------------
# Integration: _upsert_issues used via merge_scan resolves missing issues
# ---------------------------------------------------------------------------


class TestMissingIssuesResolved:
    """Issues present in state but absent from scan stay user-controlled."""

    def test_missing_issue_stays_open_when_file_exists(self, tmp_path):
        """An open issue whose file still exists stays open until resolved."""
        (tmp_path / "a.py").write_text("# exists")
        st = empty_state()
        old = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        old["lang"] = "python"
        st["issues"]["det::a.py::fn"] = old

        diff = merge_scan(st, [], MergeScanOptions(lang="python", force_resolve=True, project_root=str(tmp_path)))
        assert diff["auto_resolved"] == 0
        assert st["issues"]["det::a.py::fn"]["status"] == "open"
        assert st["issues"]["det::a.py::fn"]["resolved_at"] is None

    def test_missing_issue_auto_resolved_when_file_deleted(self, tmp_path):
        """An open issue for a deleted file is auto-resolved on rescan."""
        st = empty_state()
        old = _make_raw_issue("det::a.py::fn", detector="det", file="a.py")
        old["lang"] = "python"
        st["issues"]["det::a.py::fn"] = old

        diff = merge_scan(st, [], MergeScanOptions(lang="python", force_resolve=True, project_root=str(tmp_path)))
        assert diff["auto_resolved"] == 1
        assert st["issues"]["det::a.py::fn"]["status"] == "auto_resolved"
        assert "no longer exists" in st["issues"]["det::a.py::fn"]["note"]

    def test_missing_fixed_issue_gets_scan_verified(self):
        """A manually fixed issue stays fixed and gains scan corroboration."""
        st = empty_state()
        old = _make_raw_issue(
            "det::a.py::fn",
            detector="det",
            file="a.py",
            status="fixed",
        )
        old["lang"] = "python"
        old["resolution_attestation"] = {
            "kind": "manual",
            "text": "fixed manually",
            "attested_at": "2025-01-01T00:00:00+00:00",
            "scan_verified": False,
        }
        st["issues"]["det::a.py::fn"] = old

        diff = merge_scan(st, [], MergeScanOptions(lang="python", force_resolve=True))
        assert diff["auto_resolved"] == 1
        assert st["issues"]["det::a.py::fn"]["status"] == "fixed"
        assert st["issues"]["det::a.py::fn"]["resolution_attestation"]["scan_verified"] is True
        assert "scan_verified_at" in st["issues"]["det::a.py::fn"]["resolution_attestation"]


# ---------------------------------------------------------------------------
# #53: Wontfix auto-resolution via potentials (ran_detectors)
# ---------------------------------------------------------------------------


class TestWontfixAutoResolution:
    """Wontfix issues stay authoritative when the detector produces no findings."""

    def test_wontfix_stays_wontfix_when_detector_ran(self):
        """Open test coverage issues auto-resolve while wontfix stays authoritative."""
        st = empty_state()
        # Pre-populate 3 open + 2 wontfix test_coverage issues
        for i in range(3):
            f = _make_raw_issue(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage",
                file=f"mod{i}.py",
                lang="python",
            )
            st["issues"][f["id"]] = f
        for i in range(3, 5):
            f = _make_raw_issue(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage",
                file=f"mod{i}.py",
                status="wontfix",
                lang="python",
            )
            st["issues"][f["id"]] = f

        # Simulate: user wrote tests for ALL files → 0 issues
        # test_coverage ran (in potentials) but found nothing
        diff = merge_scan(
            st, [], MergeScanOptions(lang="python", potentials={"test_coverage": 50, "smells": 100})
        )
        assert diff["auto_resolved"] == 5
        assert (
            st["issues"]["test_coverage::mod0.py::untested_module"]["status"]
            == "auto_resolved"
        )
        assert (
            st["issues"]["test_coverage::mod3.py::untested_module"]["status"]
            == "wontfix"
        )
        assert (
            st["issues"]["test_coverage::mod4.py::untested_module"]["resolution_attestation"]["scan_verified"]
            is True
        )

    def test_wontfix_not_resolved_when_detector_suspect(self):
        """Wontfix issues survive when detector didn't run (not in potentials)."""
        st = empty_state()
        # 4 open issues (>=3 triggers suspect detection)
        for i in range(4):
            f = _make_raw_issue(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage",
                file=f"mod{i}.py",
                lang="python",
            )
            st["issues"][f["id"]] = f
        # 1 wontfix issue
        wf = _make_raw_issue(
            "test_coverage::mod4.py::untested_module",
            detector="test_coverage",
            file="mod4.py",
            status="wontfix",
            lang="python",
        )
        st["issues"][wf["id"]] = wf

        # test_coverage NOT in potentials → suspect → wontfix preserved
        diff = merge_scan(st, [], MergeScanOptions(lang="python", potentials={"smells": 100}))
        assert "test_coverage" in diff["suspect_detectors"]
        assert (
            st["issues"]["test_coverage::mod4.py::untested_module"]["status"]
            == "wontfix"
        )

    def test_wontfix_stays_wontfix_when_some_issues_remain(self):
        """Wontfix issues stay wontfix even when other issues remain open."""
        st = empty_state()
        # 2 wontfix + 2 open
        for i in range(2):
            f = _make_raw_issue(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage",
                file=f"mod{i}.py",
                status="wontfix",
                lang="python",
            )
            st["issues"][f["id"]] = f
        for i in range(2, 4):
            f = _make_raw_issue(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage",
                file=f"mod{i}.py",
                lang="python",
            )
            st["issues"][f["id"]] = f

        # User wrote tests for wontfix files only — 2 issues remain (open ones)
        current = [
            _make_raw_issue(
                f"test_coverage::mod{i}.py::untested_module",
                detector="test_coverage",
                file=f"mod{i}.py",
            )
            for i in range(2, 4)
        ]
        _ = merge_scan(st, current, MergeScanOptions(lang="python", potentials={"test_coverage": 50}))
        # The 2 wontfix issues stay wontfix and become scan-verified.
        assert (
            st["issues"]["test_coverage::mod0.py::untested_module"]["status"]
            == "wontfix"
        )
        assert (
            st["issues"]["test_coverage::mod1.py::untested_module"]["status"]
            == "wontfix"
        )
        assert (
            st["issues"]["test_coverage::mod0.py::untested_module"]["resolution_attestation"]["scan_verified"]
            is True
        )
        # The 2 open issues should still be open (they were re-emitted)
        assert (
            st["issues"]["test_coverage::mod2.py::untested_module"]["status"]
            == "open"
        )
        assert (
            st["issues"]["test_coverage::mod3.py::untested_module"]["status"]
            == "open"
        )

    def test_open_test_coverage_issues_auto_resolve_when_detector_runs_clean(self):
        """Disappeared open coverage issues should not linger as stale debt."""
        st = empty_state()
        issue = _make_raw_issue(
            "test_coverage::mod.py::untested_module",
            detector="test_coverage",
            file="mod.py",
            lang="python",
        )
        st["issues"][issue["id"]] = issue

        diff = merge_scan(
            st,
            [],
            MergeScanOptions(lang="python", potentials={"test_coverage": 10}),
        )

        assert diff["auto_resolved"] == 1
        assert st["issues"][issue["id"]]["status"] == "auto_resolved"
        assert (
            st["issues"][issue["id"]]["note"]
            == "Auto-resolved: test coverage gap absent from latest scan"
        )

    def test_empty_potentials_dict_not_treated_as_none(self):
        """Empty potentials {} means 'scan ran but no detectors reported' —
        should not mark detectors suspect just because dict is falsy."""
        from desloppify.state import find_suspect_detectors

        # Build a state with 3 open issues for a detector
        existing = {}
        for i in range(3):
            f = _make_raw_issue(
                f"det::mod{i}.py::x", detector="det", file=f"mod{i}.py"
            )
            existing[f["id"]] = f
        # Empty potentials {} — ran_detectors should be set() not None
        suspect = find_suspect_detectors(existing, {}, False, ran_detectors=set())
        # det had 3 open, returned 0, but set() means "ran" info was provided
        # Since det is NOT in ran_detectors=set(), it IS suspect
        assert "det" in suspect

    def test_potentials_none_means_no_info(self):
        """potentials=None means no ran_detectors info at all."""
        from desloppify.state import find_suspect_detectors

        existing = {}
        for i in range(3):
            f = _make_raw_issue(
                f"det::mod{i}.py::x", detector="det", file=f"mod{i}.py"
            )
            existing[f["id"]] = f
        suspect = find_suspect_detectors(existing, {}, False, ran_detectors=None)
        assert "det" in suspect

    def test_merge_potentials_preserves_existing_detector_counts(self):
        """merge_potentials=True should update only provided detector keys."""
        st = empty_state()
        st["potentials"] = {"python": {"unused": 10, "smells": 20}}

        merge_scan(
            st,
            [],
            MergeScanOptions(lang="python", potentials={"review": 3}, merge_potentials=True, force_resolve=True),
        )

        pots = st["potentials"]["python"]
        assert pots["unused"] == 10
        assert pots["smells"] == 20
        assert pots["review"] == 3

    def test_zero_active_checks_defaults_objective_to_neutral(self):
        """When all detector potentials are zero and no assessments exist,
        objective health should be neutral (100) rather than 0."""
        st = empty_state()
        merge_scan(
            st,
            [],
            MergeScanOptions(lang="typescript", potentials={"logs": 0, "unused": 0, "subjective_review": 0}, force_resolve=True),
        )

        assert st["objective_score"] == 100.0
        assert st["strict_score"] == 100.0
        assert st["overall_score"] == 100.0
        assert st["dimension_scores"] == {}

    def test_zero_active_checks_with_assessments_keeps_subjective_scoring(self):
        """Assessment scores drive subjective dimensions directly."""
        st = empty_state()
        st["subjective_assessments"] = {"naming_quality": {"score": 40}}
        merge_scan(
            st,
            [],
            MergeScanOptions(lang="typescript", potentials={"logs": 0, "unused": 0, "subjective_review": 0}, force_resolve=True),
        )

        # Objective excludes subjective dimensions.
        assert st["objective_score"] == 100.0
        # Overall/strict are dragged down by the low assessment score.
        assert st["overall_score"] < 100.0
        assert st["strict_score"] < 100.0
