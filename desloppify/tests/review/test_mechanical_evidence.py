"""Tests for mechanical evidence aggregation."""

from __future__ import annotations

from desloppify.intelligence.review.context_holistic.mechanical import (
    gather_mechanical_evidence,
)


def _finding(
    *,
    id: str,
    detector: str,
    file: str,
    tier: int = 2,
    detail: dict | None = None,
    status: str = "open",
) -> dict:
    return {
        "id": id,
        "detector": detector,
        "file": file,
        "tier": tier,
        "confidence": "high",
        "summary": f"{detector} finding in {file}",
        "detail": detail or {},
        "status": status,
        "note": None,
        "first_seen": "2025-01-01T00:00:00+00:00",
        "last_seen": "2025-01-01T00:00:00+00:00",
        "resolved_at": None,
        "reopen_count": 0,
    }


class TestGatherMechanicalEvidence:
    def test_empty_state(self):
        assert gather_mechanical_evidence({}) == {}

    def test_empty_findings(self):
        assert gather_mechanical_evidence({"findings": {}}) == {}

    def test_skips_resolved_findings(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="structural",
                    file="a.py",
                    detail={"signals": {"loc": 500}},
                    status="fixed",
                ),
            }
        }
        assert gather_mechanical_evidence(state) == {}

    def test_allowed_files_scope_filters_evidence(self):
        state = {
            "findings": {
                "in_scope": _finding(
                    id="in_scope",
                    detector="structural",
                    file="source/worker.py",
                    detail={"signals": {"loc": 420, "complexity_score": 9}},
                ),
                "out_scope": _finding(
                    id="out_scope",
                    detector="structural",
                    file="Wan2GP/wgp.py",
                    detail={"signals": {"loc": 900, "complexity_score": 20}},
                ),
            }
        }

        evidence = gather_mechanical_evidence(
            state,
            allowed_files={"source/worker.py"},
        )
        hotspots = evidence.get("complexity_hotspots", [])
        assert len(hotspots) == 1
        assert hotspots[0]["file"] == "source/worker.py"

    def test_complexity_hotspots(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="structural",
                    file="big.py",
                    detail={
                        "signals": {
                            "loc": 1000,
                            "complexity_score": 20,
                            "component_count": 5,
                            "function_count": 30,
                            "max_params": 8,
                            "max_nesting": 6,
                        }
                    },
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        hotspots = evidence.get("complexity_hotspots", [])
        assert len(hotspots) == 1
        assert hotspots[0]["file"] == "big.py"
        assert hotspots[0]["loc"] == 1000
        assert "8 params" in hotspots[0]["signals"]
        assert "nesting depth 6" in hotspots[0]["signals"]

    def test_error_hotspots_threshold(self):
        """Files with <3 error smells should not appear."""
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="smells",
                    file="ok.py",
                    detail={"smell_id": "broad_except"},
                ),
                "f2": _finding(
                    id="f2",
                    detector="smells",
                    file="ok.py",
                    detail={"smell_id": "silent_except"},
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        assert "error_hotspots" not in evidence

    def test_error_hotspots_above_threshold(self):
        state = {
            "findings": {
                f"f{i}": _finding(
                    id=f"f{i}",
                    detector="smells",
                    file="bad.py",
                    detail={"smell_id": smell},
                )
                for i, smell in enumerate(
                    ["broad_except", "silent_except", "empty_except"]
                )
            }
        }
        evidence = gather_mechanical_evidence(state)
        hotspots = evidence["error_hotspots"]
        assert len(hotspots) == 1
        assert hotspots[0]["file"] == "bad.py"
        assert hotspots[0]["total"] == 3

    def test_mutable_globals(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="global_mutable_config",
                    file="registry.py",
                    detail={"name": "_registry", "mutations": 5},
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        mg = evidence["mutable_globals"]
        assert len(mg) == 1
        assert mg[0]["file"] == "registry.py"
        assert "_registry" in mg[0]["names"]

    def test_boundary_violations(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="coupling",
                    file="a.py",
                    detail={"target": "b.py", "direction": "shared->tools"},
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        bv = evidence["boundary_violations"]
        assert len(bv) == 1
        assert bv[0]["target"] == "b.py"

    def test_dead_code(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="orphaned",
                    file="dead.py",
                    detail={"signals": {"loc": 100}},
                ),
                "f2": _finding(
                    id="f2",
                    detector="uncalled_functions",
                    file="utils.py",
                    detail={"loc": 50},
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        dc = evidence["dead_code"]
        assert len(dc) == 2
        kinds = {d["kind"] for d in dc}
        assert kinds == {"orphaned", "uncalled"}

    def test_deferred_import_density(self):
        state = {
            "findings": {
                f"f{i}": _finding(
                    id=f"f{i}",
                    detector="smells",
                    file="generic.py",
                    detail={"smell_id": "deferred_import"},
                )
                for i in range(3)
            }
        }
        evidence = gather_mechanical_evidence(state)
        deferred = evidence["deferred_import_density"]
        assert len(deferred) == 1
        assert deferred[0]["file"] == "generic.py"
        assert deferred[0]["count"] == 3

    def test_duplicate_clusters(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="dupes",
                    file="a.py",
                    detail={
                        "kind": "exact",
                        "name": "helper_fn",
                        "files": ["a.py", "b.py", "c.py"],
                    },
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        dc = evidence["duplicate_clusters"]
        assert len(dc) == 1
        assert dc[0]["cluster_size"] == 3

    def test_signal_density(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="structural",
                    file="hot.py",
                    detail={"signals": {"loc": 500}},
                ),
                "f2": _finding(
                    id="f2",
                    detector="smells",
                    file="hot.py",
                    detail={"smell_id": "broad_except"},
                ),
                "f3": _finding(
                    id="f3",
                    detector="coupling",
                    file="hot.py",
                    detail={},
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        sd = evidence["signal_density"]
        assert len(sd) == 1
        assert sd[0]["file"] == "hot.py"
        assert sd[0]["detector_count"] == 3
        assert set(sd[0]["detectors"]) == {"structural", "smells", "coupling"}

    def test_systemic_patterns(self):
        """Smell appearing in 5+ files should be flagged."""
        findings = {}
        for i in range(6):
            findings[f"f{i}"] = _finding(
                id=f"f{i}",
                detector="smells",
                file=f"module{i}.py",
                detail={"smell_id": "broad_except"},
            )
        state = {"findings": findings}
        evidence = gather_mechanical_evidence(state)
        sp = evidence["systemic_patterns"]
        assert len(sp) == 1
        assert sp[0]["pattern"] == "broad_except"
        assert sp[0]["file_count"] == 6

    def test_systemic_patterns_below_threshold(self):
        """Smell in <5 files should not be systemic."""
        findings = {}
        for i in range(4):
            findings[f"f{i}"] = _finding(
                id=f"f{i}",
                detector="smells",
                file=f"module{i}.py",
                detail={"smell_id": "broad_except"},
            )
        state = {"findings": findings}
        evidence = gather_mechanical_evidence(state)
        assert "systemic_patterns" not in evidence

    def test_security_hotspots(self):
        findings = {}
        for i in range(4):
            findings[f"f{i}"] = _finding(
                id=f"f{i}",
                detector="security",
                file="insecure.py",
                detail={"severity": "high" if i < 2 else "medium"},
            )
        state = {"findings": findings}
        evidence = gather_mechanical_evidence(state)
        sh = evidence["security_hotspots"]
        assert len(sh) == 1
        assert sh[0]["high_severity"] == 2
        assert sh[0]["total"] == 4

    def test_large_file_distribution(self):
        findings = {}
        for i, loc in enumerate([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]):
            findings[f"f{i}"] = _finding(
                id=f"f{i}",
                detector="structural",
                file=f"file{i}.py",
                detail={"signals": {"loc": loc}},
            )
        state = {"findings": findings}
        evidence = gather_mechanical_evidence(state)
        dist = evidence["large_file_distribution"]
        assert dist["count"] == 10
        assert dist["median_loc"] == 600  # locs[5] when sorted

    def test_naming_drift(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="naming",
                    file="commands/fixCmd.py",
                    detail={"expected_convention": "snake_case"},
                ),
                "f2": _finding(
                    id="f2",
                    detector="naming",
                    file="commands/listView.py",
                    detail={"expected_convention": "snake_case"},
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        nd = evidence["naming_drift"]
        assert len(nd) == 1
        assert nd[0]["directory"] == "commands/"
        assert nd[0]["minority_count"] == 2

    def test_flat_dir_findings(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="flat_dirs",
                    file="commands/review/",
                    detail={"kind": "overload", "file_count": 15, "score": 45},
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        fd = evidence["flat_dir_findings"]
        assert len(fd) == 1
        assert fd[0]["directory"] == "commands/review/"
        assert fd[0]["combined_score"] == 45

    def test_private_crossings(self):
        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="private_imports",
                    file="a.py",
                    detail={"symbol": "_internal", "source": "b.py"},
                ),
            }
        }
        evidence = gather_mechanical_evidence(state)
        pc = evidence["private_crossings"]
        assert len(pc) == 1
        assert pc[0]["symbol"] == "_internal"


class TestConcernsIntegration:
    """Verify the lowered concern thresholds work."""

    def test_one_judgment_plus_mechanical_triggers(self):
        """1 judgment detector + 2 additional findings should now trigger."""
        from desloppify.engine.concerns import generate_concerns

        state = {
            "findings": {
                "f1": _finding(
                    id="f1",
                    detector="structural",  # judgment detector
                    file="target.py",
                    detail={"signals": {"loc": 100}},
                ),
                "f2": _finding(
                    id="f2",
                    detector="unused",  # non-judgment
                    file="target.py",
                ),
                "f3": _finding(
                    id="f3",
                    detector="test_coverage",  # non-judgment
                    file="target.py",
                ),
            },
            "concern_dismissals": {},
        }
        concerns = generate_concerns(state)
        files = {c.file for c in concerns}
        assert "target.py" in files

    def test_systemic_smell_concern(self):
        """Smell in 5+ files should generate systemic concern."""
        from desloppify.engine.concerns import generate_concerns

        findings = {}
        for i in range(6):
            findings[f"smell_{i}"] = _finding(
                id=f"smell_{i}",
                detector="smells",
                file=f"mod{i}.py",
                detail={"smell_id": "broad_except"},
            )
        state = {"findings": findings, "concern_dismissals": {}}
        concerns = generate_concerns(state)
        systemic = [c for c in concerns if c.type == "systemic_smell"]
        assert len(systemic) == 1
        assert "broad_except" in systemic[0].summary


class TestMechanicalStaleness:
    """Verify that mechanical finding changes mark subjective assessments stale."""

    def test_new_findings_mark_assessments_stale(self):
        from desloppify.engine._state.merge import merge_scan
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        state["subjective_assessments"] = {
            "design_coherence": {"score": 75.0},
            "initialization_coupling": {"score": 80.0},
        }
        new_findings = [
            _finding(id="s1", detector="structural", file="big.py",
                     detail={"signals": {"loc": 500}}),
        ]
        merge_scan(state, new_findings)

        dc = state["subjective_assessments"]["design_coherence"]
        assert dc["needs_review_refresh"] is True
        assert dc["refresh_reason"] == "mechanical_findings_changed"
        assert dc["stale_since"] is not None

    def test_unrelated_detector_doesnt_mark_stale(self):
        from desloppify.engine._state.merge import merge_scan
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        state["subjective_assessments"] = {
            "initialization_coupling": {"score": 80.0},
        }
        # 'unused' has no subjective dimension mapping
        new_findings = [
            _finding(id="u1", detector="unused", file="a.py"),
        ]
        merge_scan(state, new_findings)

        ic = state["subjective_assessments"]["initialization_coupling"]
        assert "needs_review_refresh" not in ic

    def test_no_change_doesnt_mark_stale(self):
        from desloppify.engine._state.merge import merge_scan
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        state["subjective_assessments"] = {
            "design_coherence": {"score": 75.0},
        }
        # Empty scan — no new, no resolved
        merge_scan(state, [])

        dc = state["subjective_assessments"]["design_coherence"]
        assert "needs_review_refresh" not in dc

    def test_already_stale_not_overwritten(self):
        from desloppify.engine._state.merge import merge_scan
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        state["subjective_assessments"] = {
            "design_coherence": {
                "score": 75.0,
                "needs_review_refresh": True,
                "refresh_reason": "review_finding_fixed",
                "stale_since": "2025-01-01T00:00:00+00:00",
            },
        }
        new_findings = [
            _finding(id="s1", detector="structural", file="big.py",
                     detail={"signals": {"loc": 500}}),
        ]
        merge_scan(state, new_findings)

        dc = state["subjective_assessments"]["design_coherence"]
        # Should keep original reason, not overwrite
        assert dc["refresh_reason"] == "review_finding_fixed"

    def test_global_mutable_config_marks_init_coupling(self):
        from desloppify.engine._state.merge import merge_scan
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        state["subjective_assessments"] = {
            "initialization_coupling": {"score": 80.0},
        }
        new_findings = [
            _finding(id="g1", detector="global_mutable_config", file="registry.py",
                     detail={"name": "_registry"}),
        ]
        merge_scan(state, new_findings)

        ic = state["subjective_assessments"]["initialization_coupling"]
        assert ic["needs_review_refresh"] is True
        assert ic["refresh_reason"] == "mechanical_findings_changed"

    def test_unchanged_detector_doesnt_stale_unrelated_dimension(self):
        """Pre-populate structural finding, rescan with same structural + new unused
        → design_coherence must NOT be marked stale (structural didn't change)."""
        from desloppify.engine._state.merge import merge_scan
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        state["subjective_assessments"] = {
            "design_coherence": {"score": 75.0},
        }
        # First scan: populate a structural finding
        structural = _finding(
            id="structural::big.py::large_file",
            detector="structural",
            file="big.py",
            detail={"signals": {"loc": 500}},
        )
        merge_scan(state, [structural])
        # Clear the stale flag set by the first scan
        state["subjective_assessments"]["design_coherence"] = {"score": 75.0}

        # Second scan: same structural finding + new unused finding
        unused = _finding(id="unused::a.py::x", detector="unused", file="a.py")
        merge_scan(state, [structural, unused])

        dc = state["subjective_assessments"]["design_coherence"]
        # structural was unchanged (same finding re-emitted) so design_coherence
        # should NOT be marked stale; only unused changed, and unused has no
        # subjective dimension mapping.
        assert "needs_review_refresh" not in dc or not dc.get("needs_review_refresh")

    def test_auto_resolved_detector_marks_its_dimensions_stale(self):
        """Structural finding disappears → design_coherence IS marked stale."""
        from desloppify.engine._state.merge import MergeScanOptions, merge_scan
        from desloppify.engine._state.schema import empty_state

        state = empty_state()
        state["subjective_assessments"] = {
            "design_coherence": {"score": 75.0},
        }
        # First scan: structural finding exists
        structural = _finding(
            id="structural::big.py::large_file",
            detector="structural",
            file="big.py",
            detail={"signals": {"loc": 500}},
        )
        merge_scan(state, [structural], MergeScanOptions(force_resolve=True))
        # Clear stale flag
        state["subjective_assessments"]["design_coherence"] = {"score": 75.0}

        # Second scan: structural finding disappears
        merge_scan(state, [], MergeScanOptions(force_resolve=True))

        dc = state["subjective_assessments"]["design_coherence"]
        assert dc["needs_review_refresh"] is True


class TestStaleReminderGating:
    """Verify that stale assessment reminders are suppressed while queue has open findings."""

    def test_stale_reminder_suppressed_when_queue_has_open_findings(self):
        from desloppify.intelligence.narrative.reminders import _stale_assessment_reminder

        state = {
            "subjective_assessments": {
                "design_coherence": {
                    "score": 75.0,
                    "needs_review_refresh": True,
                    "refresh_reason": "mechanical_findings_changed",
                    "stale_since": "2025-01-01T00:00:00+00:00",
                },
            },
            "findings": {
                "f1": {"status": "open", "suppressed": False},
            },
        }
        assert _stale_assessment_reminder(state) == []

    def test_stale_reminder_shown_when_queue_fully_cleared(self):
        from desloppify.intelligence.narrative.reminders import _stale_assessment_reminder

        state = {
            "subjective_assessments": {
                "design_coherence": {
                    "score": 75.0,
                    "needs_review_refresh": True,
                    "refresh_reason": "mechanical_findings_changed",
                    "stale_since": "2025-01-01T00:00:00+00:00",
                },
            },
            "findings": {
                "f1": {"status": "auto_resolved", "suppressed": False},
            },
        }
        reminders = _stale_assessment_reminder(state)
        assert len(reminders) == 1
        assert reminders[0]["type"] == "stale_assessments"
