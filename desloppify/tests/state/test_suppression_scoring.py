"""Tests for suppressed-finding filtering in scoring, stats, and merge paths."""

from __future__ import annotations

from desloppify.engine._scoring.detection import _iter_scoring_candidates
from desloppify.engine._state.filtering import (
    open_scope_breakdown,
    remove_ignored_findings,
)
from desloppify.engine._state.merge_findings import upsert_findings
from desloppify.engine._state.scoring import _count_findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(
    finding_id: str,
    *,
    status: str = "open",
    detector: str = "unused",
    file: str = "src/a.ts",
    tier: int = 2,
    confidence: str = "high",
    suppressed: bool = False,
) -> dict:
    return {
        "id": finding_id,
        "detector": detector,
        "file": file,
        "tier": tier,
        "confidence": confidence,
        "summary": f"test finding {finding_id}",
        "detail": {},
        "status": status,
        "note": None,
        "first_seen": "2025-01-01T00:00:00Z",
        "last_seen": "2025-01-01T00:00:00Z",
        "resolved_at": None,
        "reopen_count": 0,
        "suppressed": suppressed,
    }


def _minimal_state(findings: dict | None = None) -> dict:
    return {
        "findings": findings or {},
        "stats": {},
        "scan_count": 1,
        "last_scan": "2025-01-01T00:00:00Z",
        "scan_path": ".",
        "potentials": {},
        "dimension_scores": {},
        "overall_score": 50.0,
        "objective_score": 48.0,
        "strict_score": 40.0,
        "verified_strict_score": 39.0,
    }


# ---------------------------------------------------------------------------
# _count_findings excludes suppressed
# ---------------------------------------------------------------------------


class TestCountFindingsExcludesSuppressed:
    def test_suppressed_not_counted(self):
        findings = {
            "f1": _make_finding("f1", status="open"),
            "f2": _make_finding("f2", status="open", suppressed=True),
        }
        counters, _ = _count_findings(findings)
        assert counters["open"] == 1

    def test_all_suppressed_gives_zero(self):
        findings = {
            "f1": _make_finding("f1", status="open", suppressed=True),
        }
        counters, _ = _count_findings(findings)
        assert counters["open"] == 0

    def test_unsuppressed_counted_normally(self):
        findings = {
            "f1": _make_finding("f1", status="open"),
            "f2": _make_finding("f2", status="fixed"),
        }
        counters, _ = _count_findings(findings)
        assert counters["open"] == 1
        assert counters["fixed"] == 1

    def test_tier_stats_exclude_suppressed(self):
        findings = {
            "f1": _make_finding("f1", status="open", tier=1),
            "f2": _make_finding("f2", status="open", tier=1, suppressed=True),
        }
        _, tier_stats = _count_findings(findings)
        assert tier_stats[1]["open"] == 1


# ---------------------------------------------------------------------------
# _iter_scoring_candidates excludes suppressed
# ---------------------------------------------------------------------------


class TestScoringCandidatesExcludesSuppressed:
    def test_suppressed_skipped(self):
        findings = {
            "f1": _make_finding("f1", detector="unused"),
            "f2": _make_finding("f2", detector="unused", suppressed=True),
        }
        candidates = list(
            _iter_scoring_candidates("unused", findings, frozenset())
        )
        assert len(candidates) == 1
        assert candidates[0]["id"] == "f1"

    def test_no_candidates_when_all_suppressed(self):
        findings = {
            "f1": _make_finding("f1", detector="unused", suppressed=True),
        }
        candidates = list(
            _iter_scoring_candidates("unused", findings, frozenset())
        )
        assert candidates == []


# ---------------------------------------------------------------------------
# open_scope_breakdown excludes suppressed
# ---------------------------------------------------------------------------


class TestOpenScopeBreakdownExcludesSuppressed:
    def test_suppressed_open_not_counted(self):
        findings = {
            "f1": _make_finding("f1", status="open"),
            "f2": _make_finding("f2", status="open", suppressed=True),
        }
        result = open_scope_breakdown(findings, ".")
        assert result["global"] == 1

    def test_all_suppressed_gives_zero(self):
        findings = {
            "f1": _make_finding("f1", status="open", suppressed=True),
        }
        result = open_scope_breakdown(findings, ".")
        assert result["global"] == 0


# ---------------------------------------------------------------------------
# remove_ignored_findings preserves resolved status (no reopen)
# ---------------------------------------------------------------------------


class TestRemoveIgnoredPreservesStatus:
    def test_fixed_stays_fixed(self):
        findings = {
            "unused::src/a.ts::foo": _make_finding(
                "unused::src/a.ts::foo",
                status="fixed",
                file="src/a.ts",
            ),
        }
        state = _minimal_state(findings)
        removed = remove_ignored_findings(state, "src/a.ts")
        assert removed == 1
        f = state["findings"]["unused::src/a.ts::foo"]
        assert f["suppressed"] is True
        assert f["status"] == "fixed"  # NOT reopened to "open"

    def test_auto_resolved_stays_auto_resolved(self):
        findings = {
            "unused::src/a.ts::bar": _make_finding(
                "unused::src/a.ts::bar",
                status="auto_resolved",
                file="src/a.ts",
            ),
        }
        state = _minimal_state(findings)
        remove_ignored_findings(state, "src/a.ts")
        f = state["findings"]["unused::src/a.ts::bar"]
        assert f["suppressed"] is True
        assert f["status"] == "auto_resolved"

    def test_false_positive_stays_false_positive(self):
        findings = {
            "unused::src/a.ts::baz": _make_finding(
                "unused::src/a.ts::baz",
                status="false_positive",
                file="src/a.ts",
            ),
        }
        state = _minimal_state(findings)
        remove_ignored_findings(state, "src/a.ts")
        f = state["findings"]["unused::src/a.ts::baz"]
        assert f["suppressed"] is True
        assert f["status"] == "false_positive"


# ---------------------------------------------------------------------------
# upsert_findings preserves resolved status when ignored
# ---------------------------------------------------------------------------


class TestUpsertPreservesResolvedStatus:
    def test_existing_fixed_stays_fixed_when_ignored(self):
        existing = {
            "unused::src/a.ts::foo": _make_finding(
                "unused::src/a.ts::foo",
                status="fixed",
                file="src/a.ts",
            ),
        }
        current = [
            _make_finding("unused::src/a.ts::foo", file="src/a.ts"),
        ]
        _, new, reopened, _, ignored, _ = upsert_findings(
            existing, current, ["src/a.ts"], "2025-06-01T00:00:00Z", lang=None
        )
        f = existing["unused::src/a.ts::foo"]
        assert f["suppressed"] is True
        assert f["status"] == "fixed"  # NOT reopened
        assert reopened == 0

    def test_existing_auto_resolved_stays_when_ignored(self):
        existing = {
            "unused::src/a.ts::foo": _make_finding(
                "unused::src/a.ts::foo",
                status="auto_resolved",
                file="src/a.ts",
            ),
        }
        current = [
            _make_finding("unused::src/a.ts::foo", file="src/a.ts"),
        ]
        _, _, reopened, _, _, _ = upsert_findings(
            existing, current, ["src/a.ts"], "2025-06-01T00:00:00Z", lang=None
        )
        f = existing["unused::src/a.ts::foo"]
        assert f["suppressed"] is True
        assert f["status"] == "auto_resolved"
        assert reopened == 0


# ---------------------------------------------------------------------------
# End-to-end: ignore pattern does not corrupt score
# ---------------------------------------------------------------------------


class TestIgnoreDoesNotCorruptScore:
    def test_suppressed_findings_invisible_to_scoring(self):
        """After suppression, _count_findings and _iter_scoring_candidates
        both exclude the finding — no phantom open debt."""
        findings = {
            "unused::src/a.ts::foo": _make_finding(
                "unused::src/a.ts::foo",
                status="fixed",
                file="src/a.ts",
            ),
        }
        state = _minimal_state(findings)

        # Simulate ignore: suppress the finding
        remove_ignored_findings(state, "src/a.ts")

        f = state["findings"]["unused::src/a.ts::foo"]
        assert f["suppressed"] is True
        assert f["status"] == "fixed"  # preserved

        # _count_findings should not see it
        counters, _ = _count_findings(state["findings"])
        assert counters.get("open", 0) == 0
        assert counters.get("fixed", 0) == 0  # suppressed => invisible

        # _iter_scoring_candidates should not yield it
        candidates = list(
            _iter_scoring_candidates("unused", state["findings"], frozenset())
        )
        assert candidates == []

        # open_scope_breakdown should not count it
        breakdown = open_scope_breakdown(state["findings"], ".")
        assert breakdown["global"] == 0
