"""Tests for concern generators (mechanical → subjective bridge)."""

from __future__ import annotations

from desloppify.core.registry import JUDGMENT_DETECTORS
from desloppify.engine.concerns import (
    _build_evidence,
    _build_question,
    _build_summary,
    _classify,
    _cross_file_patterns,
    _extract_signals,
    _file_concerns,
    _fingerprint,
    _group_by_file,
    _has_elevated_signals,
    _is_dismissed,
    _open_findings,
    cleanup_stale_dismissals,
    generate_concerns,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_finding(
    detector: str,
    file: str,
    name: str,
    *,
    detail: dict | None = None,
    status: str = "open",
) -> dict:
    fid = f"{detector}::{file}::{name}"
    return {
        "id": fid,
        "detector": detector,
        "file": file,
        "tier": 3,
        "confidence": "high",
        "summary": f"test finding {name}",
        "detail": detail or {},
        "status": status,
        "note": None,
        "first_seen": "2026-01-01T00:00:00+00:00",
        "last_seen": "2026-01-01T00:00:00+00:00",
        "resolved_at": None,
        "reopen_count": 0,
    }


def _state_with_findings(*findings: dict) -> dict:
    return {"findings": {f["id"]: f for f in findings}}


# ── Elevated single-detector signals ─────────────────────────────────


class TestElevatedSignals:
    """Files with a single judgment detector but strong signals get flagged."""

    def test_monster_function_flags(self):
        f = _make_finding(
            "smells", "app/big.py", "monster",
            detail={"smell_id": "monster_function", "function": "do_everything", "loc": 200},
        )
        concerns = generate_concerns(_state_with_findings(f))
        assert len(concerns) == 1
        c = concerns[0]
        assert c.type == "structural_complexity"
        assert c.file == "app/big.py"
        assert "do_everything" in c.summary
        assert "200" in c.summary

    def test_high_params_flags(self):
        f = _make_finding(
            "structural", "app/service.py", "struct",
            detail={"signals": {"max_params": 12}},
        )
        concerns = generate_concerns(_state_with_findings(f))
        assert len(concerns) == 1
        assert concerns[0].type == "interface_design"
        assert "12" in concerns[0].summary

    def test_deep_nesting_flags(self):
        f = _make_finding(
            "structural", "app/nested.py", "struct",
            detail={"signals": {"max_nesting": 8}},
        )
        concerns = generate_concerns(_state_with_findings(f))
        assert len(concerns) == 1
        assert concerns[0].type == "structural_complexity"
        assert "8" in concerns[0].summary

    def test_large_file_flags(self):
        f = _make_finding(
            "structural", "app/huge.py", "struct",
            detail={"signals": {"loc": 500}},
        )
        concerns = generate_concerns(_state_with_findings(f))
        assert len(concerns) == 1

    def test_duplication_flags(self):
        f = _make_finding("dupes", "app/dup.py", "dup1")
        concerns = generate_concerns(_state_with_findings(f))
        assert len(concerns) == 1
        assert concerns[0].type == "duplication_design"

    def test_coupling_flags(self):
        f = _make_finding("coupling", "app/coupled.py", "coupling1")
        concerns = generate_concerns(_state_with_findings(f))
        assert len(concerns) == 1
        assert concerns[0].type == "coupling_design"

    def test_responsibility_cohesion_flags(self):
        f = _make_finding("responsibility_cohesion", "app/mixed.py", "resp1")
        concerns = generate_concerns(_state_with_findings(f))
        assert len(concerns) == 1
        assert concerns[0].type == "mixed_responsibilities"


# ── Non-elevated single-detector — no flag ───────────────────────────


class TestNonElevatedSkipped:
    """A single judgment detector without elevated signals is NOT flagged."""

    def test_single_naming_not_flagged(self):
        f = _make_finding("naming", "app/file.py", "name1")
        assert generate_concerns(_state_with_findings(f)) == []

    def test_single_patterns_not_flagged(self):
        f = _make_finding("patterns", "app/file.py", "pat1")
        assert generate_concerns(_state_with_findings(f)) == []

    def test_moderate_structural_not_flagged(self):
        f = _make_finding(
            "structural", "app/ok.py", "struct",
            detail={"signals": {"loc": 150, "max_params": 5, "max_nesting": 3}},
        )
        assert generate_concerns(_state_with_findings(f)) == []

    def test_non_monster_smell_not_flagged(self):
        f = _make_finding(
            "smells", "app/file.py", "smell",
            detail={"smell_id": "dead_useeffect"},
        )
        assert generate_concerns(_state_with_findings(f)) == []


# ── Clear-cut detectors — never flagged alone ────────────────────────


class TestClearCutDetectorsSkipped:
    """Auto-fixable / clear-cut detectors don't generate concerns."""

    def test_unused_not_flagged(self):
        f = _make_finding("unused", "app/file.py", "unused1")
        assert generate_concerns(_state_with_findings(f)) == []

    def test_logs_not_flagged(self):
        f = _make_finding("logs", "app/file.py", "log1")
        assert generate_concerns(_state_with_findings(f)) == []

    def test_security_not_flagged(self):
        f = _make_finding("security", "app/file.py", "sec1")
        assert generate_concerns(_state_with_findings(f)) == []

    def test_two_clearcut_not_flagged(self):
        """Two clear-cut detectors on the same file: no concern."""
        findings = [
            _make_finding("unused", "app/file.py", "unused1"),
            _make_finding("logs", "app/file.py", "log1"),
        ]
        assert generate_concerns(_state_with_findings(*findings)) == []


# ── Multi-detector files ─────────────────────────────────────────────


class TestMultiDetector:
    """Files with 2+ judgment detectors get flagged."""

    def test_two_judgment_detectors_flag(self):
        findings = [
            _make_finding("naming", "app/file.py", "name1"),
            _make_finding("patterns", "app/file.py", "pat1"),
        ]
        concerns = generate_concerns(_state_with_findings(*findings))
        assert len(concerns) == 1
        assert concerns[0].file == "app/file.py"

    def test_three_detectors_is_mixed_responsibilities(self):
        findings = [
            _make_finding("smells", "app/god.py", "smell1"),
            _make_finding("naming", "app/god.py", "name1"),
            _make_finding("structural", "app/god.py", "struct1"),
        ]
        concerns = generate_concerns(_state_with_findings(*findings))
        assert len(concerns) == 1
        assert concerns[0].type == "mixed_responsibilities"
        assert "3" in concerns[0].summary

    def test_judgment_plus_clearcut_not_flagged(self):
        """One judgment + one clear-cut detector = only 1 judgment, not enough."""
        findings = [
            _make_finding("naming", "app/file.py", "name1"),
            _make_finding("unused", "app/file.py", "unused1"),
        ]
        assert generate_concerns(_state_with_findings(*findings)) == []


# ── Evidence and questions ───────────────────────────────────────────


class TestEvidenceAndQuestions:
    """Concerns bundle full context for the LLM."""

    def test_evidence_includes_all_findings(self):
        findings = [
            _make_finding("smells", "app/f.py", "s1"),
            _make_finding("naming", "app/f.py", "n1"),
        ]
        concerns = generate_concerns(_state_with_findings(*findings))
        assert len(concerns) == 1
        evidence = concerns[0].evidence
        # Should include detector list and individual finding summaries.
        assert any("Flagged by:" in e for e in evidence)
        assert any("[smells]" in e for e in evidence)
        assert any("[naming]" in e for e in evidence)

    def test_evidence_includes_signals(self):
        f = _make_finding(
            "structural", "app/f.py", "struct",
            detail={"signals": {"max_params": 15, "max_nesting": 9, "loc": 400}},
        )
        concerns = generate_concerns(_state_with_findings(f))
        evidence = concerns[0].evidence
        assert any("15" in e and "parameters" in e.lower() for e in evidence)
        assert any("9" in e and "nesting" in e.lower() for e in evidence)
        assert any("400" in e for e in evidence)

    def test_question_mentions_monster_function(self):
        f = _make_finding(
            "smells", "app/f.py", "m",
            detail={"smell_id": "monster_function", "function": "big_func", "loc": 200},
        )
        concerns = generate_concerns(_state_with_findings(f))
        assert "big_func" in concerns[0].question

    def test_question_mentions_params(self):
        f = _make_finding(
            "structural", "app/f.py", "s",
            detail={"signals": {"max_params": 10}},
        )
        concerns = generate_concerns(_state_with_findings(f))
        assert "parameter" in concerns[0].question.lower()

    def test_question_mentions_nesting(self):
        f = _make_finding(
            "structural", "app/f.py", "s",
            detail={"signals": {"max_nesting": 7}},
        )
        concerns = generate_concerns(_state_with_findings(f))
        assert "nesting" in concerns[0].question.lower()

    def test_question_mentions_duplication(self):
        f = _make_finding("dupes", "app/f.py", "d")
        concerns = generate_concerns(_state_with_findings(f))
        assert "duplication" in concerns[0].question.lower()

    def test_question_mentions_coupling(self):
        f = _make_finding("coupling", "app/f.py", "c")
        concerns = generate_concerns(_state_with_findings(f))
        assert "coupling" in concerns[0].question.lower()

    def test_question_mentions_orphaned(self):
        findings = [
            _make_finding("orphaned", "app/f.py", "o"),
            _make_finding("naming", "app/f.py", "n"),
        ]
        concerns = generate_concerns(_state_with_findings(*findings))
        assert any("dead" in concerns[0].question.lower() or
                    "orphan" in concerns[0].question.lower()
                    for _ in [1])


# ── Cross-file systemic patterns ─────────────────────────────────────


class TestSystemicPatterns:
    """3+ files with the same detector combo → systemic pattern."""

    def test_three_files_same_combo_flagged(self):
        findings = []
        for fname in ("a.py", "b.py", "c.py"):
            findings.append(_make_finding("smells", fname, "s"))
            findings.append(_make_finding("naming", fname, "n"))
        concerns = generate_concerns(_state_with_findings(*findings))
        systemic = [c for c in concerns if c.type == "systemic_pattern"]
        assert len(systemic) == 1
        assert "3 files" in systemic[0].summary

    def test_two_files_same_combo_not_flagged(self):
        findings = []
        for fname in ("a.py", "b.py"):
            findings.append(_make_finding("smells", fname, "s"))
            findings.append(_make_finding("naming", fname, "n"))
        concerns = generate_concerns(_state_with_findings(*findings))
        systemic = [c for c in concerns if c.type == "systemic_pattern"]
        assert len(systemic) == 0

    def test_systemic_plus_per_file(self):
        """Systemic patterns coexist with per-file concerns."""
        findings = []
        for fname in ("a.py", "b.py", "c.py"):
            findings.append(_make_finding("smells", fname, "s"))
            findings.append(_make_finding("naming", fname, "n"))
        concerns = generate_concerns(_state_with_findings(*findings))
        # Should have per-file concerns AND a systemic pattern.
        per_file = [c for c in concerns if c.type != "systemic_pattern"]
        systemic = [c for c in concerns if c.type == "systemic_pattern"]
        assert len(per_file) == 3
        assert len(systemic) == 1


# ── Dismissal tracking ──────────────────────────────────────────────


class TestDismissals:
    def test_dismissed_concern_suppressed(self):
        f = _make_finding(
            "smells", "app/big.py", "monster",
            detail={"smell_id": "monster_function", "function": "f", "loc": 200},
        )
        state = _state_with_findings(f)
        concerns = generate_concerns(state)
        assert len(concerns) == 1
        fp = concerns[0].fingerprint

        state["concern_dismissals"] = {
            fp: {
                "dismissed_at": "2026-01-01T00:00:00+00:00",
                "reasoning": "Single responsibility",
                "source_finding_ids": [f["id"]],
            }
        }
        assert generate_concerns(state) == []

    def test_dismissed_with_source_ids_suppresses(self):
        """Dismissals with matching source_finding_ids suppress the concern."""
        f = _make_finding(
            "smells", "app/big.py", "monster",
            detail={"smell_id": "monster_function", "function": "f", "loc": 200},
        )
        state = _state_with_findings(f)
        concerns = generate_concerns(state)
        assert len(concerns) == 1
        fp = concerns[0].fingerprint

        # Dismissal with correct source IDs suppresses.
        state["concern_dismissals"] = {
            fp: {
                "dismissed_at": "2026-01-01T00:00:00+00:00",
                "reasoning": "Acceptable complexity",
                "source_finding_ids": [f["id"]],
            }
        }
        assert generate_concerns(state) == []

    def test_stale_dismissal_cleaned_up(self):
        """Dismissals whose source findings are all gone get removed."""
        f = _make_finding(
            "smells", "app/big.py", "monster",
            detail={"smell_id": "monster_function", "function": "f", "loc": 200},
        )
        state = _state_with_findings(f)
        concerns = generate_concerns(state)
        fp = concerns[0].fingerprint

        # Create a dismissal referencing findings that no longer exist.
        state["concern_dismissals"] = {
            "stale_fp_abc123": {
                "dismissed_at": "2026-01-01T00:00:00+00:00",
                "reasoning": "Old dismissal",
                "source_finding_ids": ["gone::finding::1", "gone::finding::2"],
            },
            fp: {
                "dismissed_at": "2026-01-01T00:00:00+00:00",
                "reasoning": "Still valid",
                "source_finding_ids": [f["id"]],
            },
        }
        removed = cleanup_stale_dismissals(state)
        # Stale dismissal removed, valid one stays.
        assert removed == 1
        assert "stale_fp_abc123" not in state["concern_dismissals"]
        assert fp in state["concern_dismissals"]

    def test_stale_dismissal_without_source_ids_not_cleaned(self):
        """Dismissals without source_finding_ids are preserved (legacy)."""
        f = _make_finding(
            "smells", "app/big.py", "monster",
            detail={"smell_id": "monster_function", "function": "f", "loc": 200},
        )
        state = _state_with_findings(f)
        state["concern_dismissals"] = {
            "legacy_fp": {
                "dismissed_at": "2026-01-01T00:00:00+00:00",
                "reasoning": "Legacy dismissal",
            },
        }
        removed = cleanup_stale_dismissals(state)
        # Legacy dismissal without source_finding_ids is NOT cleaned up.
        assert removed == 0
        assert "legacy_fp" in state["concern_dismissals"]

    def test_cleanup_on_empty_state(self):
        """cleanup_stale_dismissals on empty state is a no-op."""
        assert cleanup_stale_dismissals({}) == 0
        assert cleanup_stale_dismissals({"concern_dismissals": {}}) == 0

    def test_generate_concerns_does_not_mutate_dismissals(self):
        """generate_concerns is a pure query — no side effects on state."""
        f = _make_finding(
            "smells", "app/big.py", "monster",
            detail={"smell_id": "monster_function", "function": "f", "loc": 200},
        )
        state = _state_with_findings(f)
        state["concern_dismissals"] = {
            "stale_fp": {
                "dismissed_at": "2026-01-01T00:00:00+00:00",
                "reasoning": "Old",
                "source_finding_ids": ["gone::id"],
            },
        }
        generate_concerns(state)
        # generate_concerns must NOT remove stale dismissals.
        assert "stale_fp" in state["concern_dismissals"]

    def test_dismissed_resurfaces_on_changed_findings(self):
        f = _make_finding(
            "smells", "app/big.py", "monster",
            detail={"smell_id": "monster_function", "function": "f", "loc": 200},
        )
        state = _state_with_findings(f)
        concerns = generate_concerns(state)
        fp = concerns[0].fingerprint

        state["concern_dismissals"] = {
            fp: {
                "dismissed_at": "2026-01-01T00:00:00+00:00",
                "reasoning": "Was fine",
                "source_finding_ids": ["other::finding::id"],
            }
        }
        assert len(generate_concerns(state)) == 1


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_state(self):
        assert generate_concerns({}) == []
        assert generate_concerns({"findings": {}}) == []

    def test_non_open_findings_ignored(self):
        f = _make_finding(
            "smells", "app/big.py", "monster",
            detail={"smell_id": "monster_function", "function": "f", "loc": 200},
            status="fixed",
        )
        assert generate_concerns(_state_with_findings(f)) == []

    def test_holistic_file_ignored(self):
        """File '.' (holistic findings) should not generate concerns."""
        findings = [
            _make_finding("smells", ".", "s"),
            _make_finding("naming", ".", "n"),
            _make_finding("structural", ".", "st"),
            _make_finding("patterns", ".", "p"),
        ]
        assert generate_concerns(_state_with_findings(*findings)) == []

    def test_results_sorted_by_type_then_file(self):
        findings = [
            _make_finding("dupes", "z_file.py", "d"),
            _make_finding(
                "smells", "a_file.py", "m",
                detail={"smell_id": "monster_function", "function": "f", "loc": 150},
            ),
        ]
        concerns = generate_concerns(_state_with_findings(*findings))
        assert len(concerns) == 2
        for a, b in zip(concerns, concerns[1:], strict=False):
            assert (a.type, a.file) <= (b.type, b.file)

    def test_no_duplicate_fingerprints(self):
        findings = [
            _make_finding("smells", "a.py", "s"),
            _make_finding("naming", "a.py", "n"),
        ]
        concerns = generate_concerns(_state_with_findings(*findings))
        fps = [c.fingerprint for c in concerns]
        assert len(fps) == len(set(fps))


# ── Fingerprint stability ───────────────────────────────────────────


class TestFingerprint:
    def test_deterministic(self):
        fp1 = _fingerprint("t", "f.py", ("x", "y"))
        fp2 = _fingerprint("t", "f.py", ("y", "x"))
        assert fp1 == fp2

    def test_different_type_different_fingerprint(self):
        fp1 = _fingerprint("a", "f.py", ("x",))
        fp2 = _fingerprint("b", "f.py", ("x",))
        assert fp1 != fp2


# ── Registry integration ─────────────────────────────────────────


class TestRegistryIntegration:
    """JUDGMENT_DETECTORS derived from registry replaces hardcoded set."""

    def test_judgment_detectors_includes_cycles(self):
        assert "cycles" in JUDGMENT_DETECTORS

    def test_judgment_detectors_excludes_clearcut(self):
        for det in ("unused", "logs", "exports", "deprecated", "security",
                     "test_coverage", "stale_exclude"):
            assert det not in JUDGMENT_DETECTORS

    def test_judgment_detectors_includes_expected(self):
        expected = {
            "structural", "smells", "dupes", "boilerplate_duplication",
            "coupling", "cycles", "props", "react", "orphaned", "naming",
            "patterns", "facade", "single_use", "responsibility_cohesion",
            "signature", "dict_keys", "flat_dirs", "global_mutable_config",
            "private_imports", "layer_violation",
        }
        assert expected.issubset(JUDGMENT_DETECTORS)


# ── Targeted _extract_signals tests ──────────────────────────────────


class TestExtractSignals:
    """Boundary conditions for _extract_signals."""

    def test_empty_findings(self):
        assert _extract_signals([]) == {}

    def test_structural_signals_extracted(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"max_params": 10, "max_nesting": 5, "loc": 200, "function_count": 15}},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals["max_params"] == 10
        assert signals["max_nesting"] == 5
        assert signals["loc"] == 200
        assert signals["function_count"] == 15

    def test_structural_signals_take_max_across_findings(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s1",
                detail={"signals": {"max_params": 5, "loc": 100}},
            ),
            _make_finding(
                "structural", "f.py", "s2",
                detail={"signals": {"max_params": 12, "loc": 80}},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals["max_params"] == 12
        assert signals["loc"] == 100

    def test_zero_and_negative_values_ignored(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"max_params": 0, "max_nesting": -1, "loc": 0}},
            ),
        ]
        signals = _extract_signals(findings)
        assert "max_params" not in signals
        assert "max_nesting" not in signals
        assert "loc" not in signals

    def test_non_numeric_signal_values_ignored(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"max_params": "high", "loc": None}},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals == {}

    def test_signals_not_a_dict_ignored(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": "not_a_dict"},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals == {}

    def test_monster_function_extracted(self):
        findings = [
            _make_finding(
                "smells", "f.py", "m",
                detail={"smell_id": "monster_function", "function": "big_one", "loc": 300},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals["monster_loc"] == 300
        assert signals["monster_funcs"] == ["big_one"]

    def test_multiple_monster_functions_takes_max_loc(self):
        findings = [
            _make_finding(
                "smells", "f.py", "m1",
                detail={"smell_id": "monster_function", "function": "f1", "loc": 100},
            ),
            _make_finding(
                "smells", "f.py", "m2",
                detail={"smell_id": "monster_function", "function": "f2", "loc": 250},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals["monster_loc"] == 250
        assert signals["monster_funcs"] == ["f1", "f2"]

    def test_monster_without_function_name(self):
        findings = [
            _make_finding(
                "smells", "f.py", "m",
                detail={"smell_id": "monster_function", "loc": 200},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals["monster_loc"] == 200
        assert "monster_funcs" not in signals

    def test_monster_without_loc(self):
        findings = [
            _make_finding(
                "smells", "f.py", "m",
                detail={"smell_id": "monster_function", "function": "f"},
            ),
        ]
        signals = _extract_signals(findings)
        assert "monster_loc" not in signals
        assert signals["monster_funcs"] == ["f"]

    def test_non_monster_smells_produce_no_signals(self):
        findings = [
            _make_finding(
                "smells", "f.py", "s",
                detail={"smell_id": "star_import"},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals == {}

    def test_non_structural_non_smell_detectors_ignored(self):
        findings = [
            _make_finding("coupling", "f.py", "c1"),
            _make_finding("dupes", "f.py", "d1"),
            _make_finding("naming", "f.py", "n1"),
        ]
        signals = _extract_signals(findings)
        assert signals == {}

    def test_mixed_structural_and_monster(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"max_params": 9, "loc": 350}},
            ),
            _make_finding(
                "smells", "f.py", "m",
                detail={"smell_id": "monster_function", "function": "do_all", "loc": 180},
            ),
        ]
        signals = _extract_signals(findings)
        assert signals["max_params"] == 9
        assert signals["loc"] == 350
        assert signals["monster_loc"] == 180
        assert signals["monster_funcs"] == ["do_all"]


# ── Targeted _has_elevated_signals tests ─────────────────────────────


class TestHasElevatedSignals:
    """Boundary conditions for threshold checks."""

    def test_params_at_boundary_7_not_elevated(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"max_params": 7}},
            ),
        ]
        assert _has_elevated_signals(findings) is False

    def test_params_at_boundary_8_is_elevated(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"max_params": 8}},
            ),
        ]
        assert _has_elevated_signals(findings) is True

    def test_nesting_at_boundary_5_not_elevated(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"max_nesting": 5}},
            ),
        ]
        assert _has_elevated_signals(findings) is False

    def test_nesting_at_boundary_6_is_elevated(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"max_nesting": 6}},
            ),
        ]
        assert _has_elevated_signals(findings) is True

    def test_loc_at_boundary_299_not_elevated(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"loc": 299}},
            ),
        ]
        assert _has_elevated_signals(findings) is False

    def test_loc_at_boundary_300_is_elevated(self):
        findings = [
            _make_finding(
                "structural", "f.py", "s",
                detail={"signals": {"loc": 300}},
            ),
        ]
        assert _has_elevated_signals(findings) is True

    def test_boilerplate_duplication_is_elevated(self):
        findings = [_make_finding("boilerplate_duplication", "f.py", "bd")]
        assert _has_elevated_signals(findings) is True

    def test_responsibility_cohesion_is_elevated(self):
        findings = [_make_finding("responsibility_cohesion", "f.py", "rc")]
        assert _has_elevated_signals(findings) is True

    def test_empty_findings_not_elevated(self):
        assert _has_elevated_signals([]) is False

    def test_naming_alone_not_elevated(self):
        findings = [_make_finding("naming", "f.py", "n")]
        assert _has_elevated_signals(findings) is False


# ── Targeted _classify tests ─────────────────────────────────────────


class TestClassify:
    """Concern type classification priority."""

    def test_three_detectors_is_mixed_responsibilities(self):
        assert _classify({"a", "b", "c"}, {}) == "mixed_responsibilities"

    def test_dupes_wins_over_coupling(self):
        assert _classify({"dupes", "coupling"}, {}) == "duplication_design"

    def test_boilerplate_duplication_classified(self):
        assert _classify({"boilerplate_duplication"}, {}) == "duplication_design"

    def test_monster_loc_is_structural_complexity(self):
        assert _classify({"smells"}, {"monster_loc": 200}) == "structural_complexity"

    def test_coupling_alone(self):
        assert _classify({"coupling"}, {}) == "coupling_design"

    def test_high_params_is_interface_design(self):
        assert _classify({"structural"}, {"max_params": 8}) == "interface_design"

    def test_deep_nesting_is_structural_complexity(self):
        assert _classify({"structural"}, {"max_nesting": 6}) == "structural_complexity"

    def test_responsibility_cohesion_alone(self):
        assert _classify({"responsibility_cohesion"}, {}) == "mixed_responsibilities"

    def test_fallback_is_design_concern(self):
        assert _classify({"naming"}, {}) == "design_concern"

    def test_priority_three_detectors_beats_dupes(self):
        """3+ detectors wins even when dupes is present."""
        assert _classify({"dupes", "naming", "coupling"}, {}) == "mixed_responsibilities"


# ── Targeted _build_summary tests ────────────────────────────────────


class TestBuildSummary:
    """Summary text for each concern type."""

    def test_mixed_responsibilities_summary(self):
        s = _build_summary("mixed_responsibilities", {"a", "b", "c"}, {})
        assert "3 detectors" in s
        assert "responsibilities" in s

    def test_structural_complexity_monster(self):
        s = _build_summary(
            "structural_complexity", {"smells"}, {"monster_loc": 200, "monster_funcs": ["f1", "f2"]}
        )
        assert "200" in s
        assert "f1" in s
        assert "monster" in s.lower()

    def test_structural_complexity_nesting(self):
        s = _build_summary("structural_complexity", {"structural"}, {"max_nesting": 7})
        assert "nesting" in s.lower()
        assert "7" in s

    def test_structural_complexity_params(self):
        s = _build_summary("structural_complexity", {"structural"}, {"max_params": 10})
        assert "10" in s
        assert "parameter" in s.lower()

    def test_structural_complexity_no_parts_fallback(self):
        s = _build_summary("structural_complexity", set(), {})
        assert "elevated signals" in s

    def test_duplication_design_summary(self):
        s = _build_summary("duplication_design", {"dupes"}, {})
        assert "duplication" in s.lower()

    def test_coupling_design_summary(self):
        s = _build_summary("coupling_design", {"coupling"}, {})
        assert "coupling" in s.lower()

    def test_interface_design_summary(self):
        s = _build_summary("interface_design", {"structural"}, {"max_params": 15})
        assert "15" in s
        assert "parameter" in s.lower()

    def test_default_summary_lists_detectors(self):
        s = _build_summary("design_concern", {"naming", "patterns"}, {})
        assert "naming" in s
        assert "patterns" in s


# ── Targeted _build_evidence tests ───────────────────────────────────


class TestBuildEvidence:
    """Evidence tuple construction."""

    def test_empty_findings_minimal_evidence(self):
        evidence = _build_evidence([], {})
        assert len(evidence) >= 1
        assert "Flagged by:" in evidence[0]

    def test_monster_func_names_capped_at_3(self):
        signals = {
            "monster_loc": 200,
            "monster_funcs": ["f1", "f2", "f3", "f4", "f5"],
        }
        evidence = _build_evidence([], signals)
        monster_ev = [e for e in evidence if "Monster" in e]
        assert len(monster_ev) == 1
        # Only first 3 function names
        assert "f1" in monster_ev[0]
        assert "f3" in monster_ev[0]
        assert "f4" not in monster_ev[0]

    def test_finding_summaries_capped_at_10(self):
        findings = [
            _make_finding("smells", "f.py", f"s{i}") for i in range(15)
        ]
        evidence = _build_evidence(findings, {})
        summary_entries = [e for e in evidence if e.startswith("[")]
        assert len(summary_entries) == 10

    def test_signals_below_threshold_omitted(self):
        """Params < 8 and nesting < 6 not included in evidence."""
        signals = {"max_params": 5, "max_nesting": 4, "loc": 100}
        evidence = _build_evidence([], signals)
        assert any("100" in e for e in evidence)  # loc included
        assert not any("parameters" in e.lower() for e in evidence)
        assert not any("nesting" in e.lower() for e in evidence)


# ── Targeted _build_question tests ───────────────────────────────────


class TestBuildQuestion:
    """Question construction for each signal type."""

    def test_no_signals_fallback_question(self):
        q = _build_question(set(), {})
        assert "review" in q.lower()

    def test_multiple_signal_types_combined(self):
        """Question includes all applicable parts."""
        q = _build_question(
            {"dupes", "coupling", "orphaned", "responsibility_cohesion"},
            {"monster_funcs": ["big"], "max_params": 10, "max_nesting": 7},
        )
        assert "duplication" in q.lower()
        assert "coupling" in q.lower()
        assert "dead" in q.lower() or "orphan" in q.lower()
        assert "parameter" in q.lower()
        assert "nesting" in q.lower()
        assert "big" in q
        assert "responsibilit" in q.lower()


# ── Targeted _group_by_file and _open_findings tests ─────────────────


class TestGroupByFileAndOpenFindings:
    """Filtering and grouping helpers."""

    def test_open_findings_filters_non_open(self):
        state = _state_with_findings(
            _make_finding("smells", "a.py", "s1", status="open"),
            _make_finding("smells", "b.py", "s2", status="fixed"),
            _make_finding("smells", "c.py", "s3", status="wontfix"),
        )
        result = _open_findings(state)
        assert len(result) == 1
        assert result[0]["file"] == "a.py"

    def test_open_findings_empty_state(self):
        assert _open_findings({}) == []
        assert _open_findings({"findings": {}}) == []

    def test_open_findings_skips_non_dict(self):
        state = {"findings": {"id1": "not_a_dict", "id2": 42}}
        assert _open_findings(state) == []

    def test_group_by_file_excludes_dot_file(self):
        state = _state_with_findings(
            _make_finding("smells", ".", "holistic"),
            _make_finding("smells", "a.py", "s1"),
        )
        grouped = _group_by_file(state)
        assert "." not in grouped
        assert "a.py" in grouped

    def test_group_by_file_excludes_empty_file(self):
        f = _make_finding("smells", "a.py", "s1")
        f["file"] = ""
        state = {"findings": {f["id"]: f}}
        grouped = _group_by_file(state)
        assert "" not in grouped

    def test_group_by_file_groups_correctly(self):
        state = _state_with_findings(
            _make_finding("smells", "a.py", "s1"),
            _make_finding("naming", "a.py", "n1"),
            _make_finding("smells", "b.py", "s2"),
        )
        grouped = _group_by_file(state)
        assert len(grouped["a.py"]) == 2
        assert len(grouped["b.py"]) == 1


# ── Targeted _is_dismissed tests ─────────────────────────────────────


class TestIsDismissed:
    """Dismissal matching logic."""

    def test_not_dismissed_when_no_entry(self):
        assert _is_dismissed({}, "fp123", ("id1",)) is False

    def test_not_dismissed_when_entry_is_not_dict(self):
        assert _is_dismissed({"fp123": "invalid"}, "fp123", ("id1",)) is False
        assert _is_dismissed({"fp123": None}, "fp123", ("id1",)) is False

    def test_dismissed_when_source_ids_match(self):
        dismissals = {"fp123": {"source_finding_ids": ["id1", "id2"]}}
        assert _is_dismissed(dismissals, "fp123", ("id2", "id1")) is True

    def test_not_dismissed_when_source_ids_differ(self):
        dismissals = {"fp123": {"source_finding_ids": ["id1"]}}
        assert _is_dismissed(dismissals, "fp123", ("id1", "id_new")) is False

    def test_dismissed_with_empty_sources_matches_empty(self):
        dismissals = {"fp123": {"source_finding_ids": []}}
        assert _is_dismissed(dismissals, "fp123", ()) is True


# ── Targeted _file_concerns generator tests ──────────────────────────


class TestFileConcernsGenerator:
    """Direct tests for the _file_concerns generator."""

    def test_single_judgment_below_threshold_no_concern(self):
        """One judgment detector, no elevated signals: skipped."""
        state = _state_with_findings(
            _make_finding("naming", "a.py", "n1"),
        )
        assert _file_concerns(state, {}) == []

    def test_two_judgment_detectors_generates_concern(self):
        state = _state_with_findings(
            _make_finding("naming", "a.py", "n1"),
            _make_finding("patterns", "a.py", "p1"),
        )
        concerns = _file_concerns(state, {})
        assert len(concerns) == 1
        assert concerns[0].file == "a.py"

    def test_clearcut_findings_excluded_from_judgment_count(self):
        """Clear-cut detectors don't count toward the 2-detector threshold,
        but 1 judgment + 2 mechanical findings does trigger the lowered threshold."""
        state = _state_with_findings(
            _make_finding("naming", "a.py", "n1"),
            _make_finding("unused", "a.py", "u1"),
            _make_finding("logs", "a.py", "l1"),
        )
        # 1 judgment (naming) + 2 mechanical (unused, logs) = 3 total → triggers
        concerns = _file_concerns(state, {})
        assert len(concerns) == 1
        assert concerns[0].file == "a.py"

    def test_dismissal_suppresses_file_concern(self):
        state = _state_with_findings(
            _make_finding("naming", "a.py", "n1"),
            _make_finding("patterns", "a.py", "p1"),
        )
        # Generate to get the fingerprint
        concerns = _file_concerns(state, {})
        fp = concerns[0].fingerprint
        src_ids = concerns[0].source_findings

        dismissals = {fp: {"source_finding_ids": list(src_ids)}}
        assert _file_concerns(state, dismissals) == []

    def test_multiple_files_each_get_concern(self):
        state = _state_with_findings(
            _make_finding("naming", "a.py", "n1"),
            _make_finding("patterns", "a.py", "p1"),
            _make_finding("naming", "b.py", "n2"),
            _make_finding("coupling", "b.py", "c2"),
        )
        concerns = _file_concerns(state, {})
        files = {c.file for c in concerns}
        assert files == {"a.py", "b.py"}

    def test_concern_bundles_all_judgment_findings(self):
        """The concern's source_findings includes ALL judgment findings for the file."""
        state = _state_with_findings(
            _make_finding("naming", "a.py", "n1"),
            _make_finding("patterns", "a.py", "p1"),
            _make_finding("smells", "a.py", "s1"),
        )
        concerns = _file_concerns(state, {})
        assert len(concerns) == 1
        assert len(concerns[0].source_findings) == 3


# ── Targeted _cross_file_patterns generator tests ────────────────────


class TestCrossFilePatternsGenerator:
    """Direct tests for the _cross_file_patterns generator."""

    def test_exactly_3_files_triggers_pattern(self):
        state = _state_with_findings(
            *[
                f
                for fname in ("a.py", "b.py", "c.py")
                for f in (
                    _make_finding("smells", fname, "s"),
                    _make_finding("naming", fname, "n"),
                )
            ]
        )
        patterns = _cross_file_patterns(state, {})
        assert len(patterns) == 1
        assert patterns[0].type == "systemic_pattern"
        assert "3 files" in patterns[0].summary

    def test_exactly_2_files_below_threshold(self):
        state = _state_with_findings(
            *[
                f
                for fname in ("a.py", "b.py")
                for f in (
                    _make_finding("smells", fname, "s"),
                    _make_finding("naming", fname, "n"),
                )
            ]
        )
        patterns = _cross_file_patterns(state, {})
        assert patterns == []

    def test_single_detector_per_file_no_pattern(self):
        """Files need 2+ judgment detectors each for cross-file patterns."""
        state = _state_with_findings(
            *[_make_finding("naming", f"file{i}.py", "n") for i in range(5)]
        )
        patterns = _cross_file_patterns(state, {})
        assert patterns == []

    def test_different_combos_no_pattern(self):
        """Files with different detector combos don't form a pattern."""
        state = _state_with_findings(
            _make_finding("smells", "a.py", "s"),
            _make_finding("naming", "a.py", "n"),
            _make_finding("coupling", "b.py", "c"),
            _make_finding("patterns", "b.py", "p"),
            _make_finding("dupes", "c.py", "d"),
            _make_finding("structural", "c.py", "st"),
        )
        patterns = _cross_file_patterns(state, {})
        assert patterns == []

    def test_pattern_evidence_lists_files(self):
        state = _state_with_findings(
            *[
                f
                for fname in ("alpha.py", "beta.py", "gamma.py", "delta.py")
                for f in (
                    _make_finding("coupling", fname, "c"),
                    _make_finding("structural", fname, "s"),
                )
            ]
        )
        patterns = _cross_file_patterns(state, {})
        assert len(patterns) == 1
        assert "4 files" in patterns[0].summary
        # Evidence should list affected files
        assert any("alpha.py" in e for e in patterns[0].evidence)

    def test_pattern_dismissal_suppresses(self):
        state = _state_with_findings(
            *[
                f
                for fname in ("a.py", "b.py", "c.py")
                for f in (
                    _make_finding("smells", fname, "s"),
                    _make_finding("naming", fname, "n"),
                )
            ]
        )
        patterns = _cross_file_patterns(state, {})
        assert len(patterns) == 1
        fp = patterns[0].fingerprint
        src_ids = patterns[0].source_findings

        dismissals = {fp: {"source_finding_ids": list(src_ids)}}
        assert _cross_file_patterns(state, dismissals) == []

    def test_multiple_distinct_patterns(self):
        """Two different detector combos each appearing in 3+ files."""
        findings = []
        for fname in ("a.py", "b.py", "c.py"):
            findings.append(_make_finding("smells", fname, "s"))
            findings.append(_make_finding("naming", fname, "n"))
        for fname in ("x.py", "y.py", "z.py"):
            findings.append(_make_finding("coupling", fname, "c"))
            findings.append(_make_finding("structural", fname, "st"))
        state = _state_with_findings(*findings)
        patterns = _cross_file_patterns(state, {})
        assert len(patterns) == 2
        types = {p.type for p in patterns}
        assert types == {"systemic_pattern"}

    def test_empty_state_no_patterns(self):
        assert _cross_file_patterns({}, {}) == []
        assert _cross_file_patterns({"findings": {}}, {}) == []

    def test_pattern_fingerprint_stable_across_file_order(self):
        """Fingerprint is the same regardless of finding insertion order."""
        findings_a = [
            _make_finding("smells", "c.py", "s"),
            _make_finding("naming", "c.py", "n"),
            _make_finding("smells", "a.py", "s"),
            _make_finding("naming", "a.py", "n"),
            _make_finding("smells", "b.py", "s"),
            _make_finding("naming", "b.py", "n"),
        ]
        findings_b = [
            _make_finding("smells", "b.py", "s"),
            _make_finding("naming", "b.py", "n"),
            _make_finding("smells", "a.py", "s"),
            _make_finding("naming", "a.py", "n"),
            _make_finding("smells", "c.py", "s"),
            _make_finding("naming", "c.py", "n"),
        ]
        p1 = _cross_file_patterns(_state_with_findings(*findings_a), {})
        p2 = _cross_file_patterns(_state_with_findings(*findings_b), {})
        assert len(p1) == 1 and len(p2) == 1
        assert p1[0].fingerprint == p2[0].fingerprint
