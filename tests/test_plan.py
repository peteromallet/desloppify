"""Tests for desloppify.plan — plan generation, tier sections, and next-item priority."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from desloppify.plan import (
    CONFIDENCE_ORDER,
    TIER_LABELS,
    _plan_dimension_table,
    _plan_header,
    _plan_tier_sections,
    generate_plan_md,
    get_next_item,
    get_next_items,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(fid, *, detector="det", file="a.py", tier=1,
             confidence="high", summary="something wrong",
             status="open", detail=None, note=None):
    """Build a minimal finding dict."""
    return {
        "id": fid,
        "detector": detector,
        "file": file,
        "tier": tier,
        "confidence": confidence,
        "summary": summary,
        "status": status,
        "detail": detail or {},
        "note": note,
    }


def _state(findings_list=None, *, score=0, stats=None,
           objective_score=None, objective_strict=None,
           dimension_scores=None, codebase_metrics=None):
    """Build a minimal state dict."""
    findings = {}
    for f in (findings_list or []):
        findings[f["id"]] = f
    return {
        "score": score,
        "objective_score": objective_score,
        "objective_strict": objective_strict,
        "stats": stats or {},
        "findings": findings,
        "dimension_scores": dimension_scores or {},
        "codebase_metrics": codebase_metrics or {},
    }


# ===========================================================================
# TIER_LABELS and CONFIDENCE_ORDER constants
# ===========================================================================

class TestConstants:
    def test_tier_labels_covers_1_through_4(self):
        assert set(TIER_LABELS.keys()) == {1, 2, 3, 4}

    def test_confidence_order_ranking(self):
        assert CONFIDENCE_ORDER["high"] < CONFIDENCE_ORDER["medium"]
        assert CONFIDENCE_ORDER["medium"] < CONFIDENCE_ORDER["low"]


# ===========================================================================
# _plan_header
# ===========================================================================

class TestPlanHeader:
    def test_includes_today_date(self):
        st = _state()
        lines = _plan_header(st, {})
        header = lines[0]
        assert date.today().isoformat() in header

    def test_objective_score_format(self):
        st = _state(objective_score=87.5, objective_strict=82.3)
        lines = _plan_header(st, {})
        score_line = lines[2]
        assert "87.5" in score_line
        assert "82.3" in score_line
        assert "Health:" in score_line

    def test_fallback_score_when_no_objective(self):
        st = _state(score=42)
        lines = _plan_header(st, {})
        score_line = lines[2]
        assert "Score: 42.0/100" in score_line

    def test_stats_in_header(self):
        stats = {"open": 10, "fixed": 5, "wontfix": 3, "auto_resolved": 2}
        st = _state(stats=stats)
        lines = _plan_header(st, stats)
        score_line = lines[2]
        assert "10 open" in score_line
        assert "5 fixed" in score_line
        assert "3 wontfix" in score_line
        assert "2 auto-resolved" in score_line

    def test_codebase_metrics_included_when_present(self):
        st = _state(codebase_metrics={
            "python": {"total_files": 50, "total_loc": 3000, "total_directories": 8},
        })
        lines = _plan_header(st, {})
        joined = "\n".join(lines)
        assert "50 files" in joined
        assert "3,000 LOC" in joined
        assert "8 directories" in joined

    def test_codebase_metrics_compact_loc(self):
        """LOC >= 10000 should render as e.g. '15K' instead of '15,000'."""
        st = _state(codebase_metrics={
            "ts": {"total_files": 100, "total_loc": 15000, "total_directories": 20},
        })
        lines = _plan_header(st, {})
        joined = "\n".join(lines)
        assert "15K" in joined

    def test_no_codebase_metrics_line_when_zero_files(self):
        st = _state(codebase_metrics={})
        lines = _plan_header(st, {})
        joined = "\n".join(lines)
        assert "files" not in joined.lower() or "0 open" in joined


# ===========================================================================
# _plan_dimension_table
# ===========================================================================

class TestPlanDimensionTable:
    def test_returns_empty_when_no_dimension_scores(self):
        st = _state()
        assert _plan_dimension_table(st) == []

    def test_includes_table_header(self):
        st = _state(dimension_scores={
            "Import hygiene": {"checks": 10, "issues": 2, "score": 80.0, "strict": 75.0},
        })
        lines = _plan_dimension_table(st)
        assert any("Dimension" in line and "Health" in line for line in lines)

    def test_bold_when_score_below_93(self):
        st = _state(dimension_scores={
            "Import hygiene": {"checks": 10, "issues": 2, "score": 90.0, "strict": 85.0},
        })
        lines = _plan_dimension_table(st)
        row_lines = [l for l in lines if "Import hygiene" in l]
        assert len(row_lines) == 1
        assert "**Import hygiene**" in row_lines[0]

    def test_no_bold_when_score_at_or_above_93(self):
        st = _state(dimension_scores={
            "Import hygiene": {"checks": 100, "issues": 1, "score": 99.0, "strict": 98.0},
        })
        lines = _plan_dimension_table(st)
        row_lines = [l for l in lines if "Import hygiene" in l]
        assert len(row_lines) == 1
        assert "**Import hygiene**" not in row_lines[0]
        assert "Import hygiene" in row_lines[0]


# ===========================================================================
# _plan_tier_sections
# ===========================================================================

class TestPlanTierSections:
    def test_empty_findings_produces_no_sections(self):
        assert _plan_tier_sections({}) == []

    def test_groups_by_tier(self):
        findings = {
            "a": _finding("a", tier=1, file="x.py"),
            "b": _finding("b", tier=2, file="y.py"),
        }
        lines = _plan_tier_sections(findings)
        joined = "\n".join(lines)
        assert "Tier 1:" in joined
        assert "Tier 2:" in joined

    def test_skips_non_open_findings(self):
        findings = {
            "a": _finding("a", tier=1, status="fixed"),
            "b": _finding("b", tier=1, status="wontfix"),
        }
        lines = _plan_tier_sections(findings)
        assert lines == []

    def test_files_sorted_by_finding_count_descending(self):
        findings = {
            "a1": _finding("a1", tier=1, file="few.py"),
            "b1": _finding("b1", tier=1, file="many.py"),
            "b2": _finding("b2", tier=1, file="many.py"),
            "b3": _finding("b3", tier=1, file="many.py"),
        }
        lines = _plan_tier_sections(findings)
        # Find the file header lines
        file_headers = [l for l in lines if l.startswith("### ")]
        # "many.py" should come before "few.py"
        assert "many.py" in file_headers[0]
        assert "few.py" in file_headers[1]

    def test_findings_sorted_by_confidence_within_file(self):
        findings = {
            "lo": _finding("lo", tier=1, file="a.py", confidence="low"),
            "hi": _finding("hi", tier=1, file="a.py", confidence="high"),
            "md": _finding("md", tier=1, file="a.py", confidence="medium"),
        }
        lines = _plan_tier_sections(findings)
        bullet_lines = [l.strip() for l in lines if l.strip().startswith("- [ ]")]
        assert "[high]" in bullet_lines[0]
        assert "[medium]" in bullet_lines[1]
        assert "[low]" in bullet_lines[2]

    def test_finding_id_shown_below_summary(self):
        findings = {
            "det::f.py::x": _finding("det::f.py::x", tier=1, file="f.py"),
        }
        lines = _plan_tier_sections(findings)
        id_lines = [l for l in lines if "det::f.py::x" in l]
        assert len(id_lines) >= 1

    def test_tier_count_in_header(self):
        findings = {
            "a": _finding("a", tier=2, file="x.py"),
            "b": _finding("b", tier=2, file="y.py"),
            "c": _finding("c", tier=2, file="y.py"),
        }
        lines = _plan_tier_sections(findings)
        tier_header = [l for l in lines if l.startswith("## Tier 2:")]
        assert len(tier_header) == 1
        assert "3 open" in tier_header[0]


# ===========================================================================
# generate_plan_md
# ===========================================================================

class TestGeneratePlanMd:
    def test_returns_string(self):
        st = _state()
        md = generate_plan_md(st)
        assert isinstance(md, str)
        assert "Desloppify Plan" in md

    def test_includes_tier_breakdown(self):
        st = _state(stats={
            "by_tier": {
                "1": {"open": 5, "fixed": 3},
                "2": {"open": 2},
            },
        })
        md = generate_plan_md(st)
        assert "Tier 1" in md
        assert "Tier 2" in md

    def test_includes_addressed_section(self):
        f_fixed = _finding("a", status="fixed", tier=1)
        f_wontfix = _finding("b", status="wontfix", tier=1, note="intentional")
        st = _state([f_fixed, f_wontfix])
        md = generate_plan_md(st)
        assert "## Addressed" in md
        assert "fixed" in md
        assert "wontfix" in md

    def test_wontfix_with_notes_listed(self):
        f = _finding("det::f.py::x", status="wontfix", tier=1,
                      note="We need this for backwards compat")
        st = _state([f])
        md = generate_plan_md(st)
        assert "backwards compat" in md
        assert "det::f.py::x" in md


# ===========================================================================
# get_next_item / get_next_items
# ===========================================================================

class TestGetNextItem:
    def test_returns_none_when_no_open_findings(self):
        st = _state([_finding("a", status="fixed")])
        assert get_next_item(st) is None

    def test_returns_none_for_empty_findings(self):
        st = _state()
        assert get_next_item(st) is None

    def test_returns_highest_priority_item(self):
        f1 = _finding("lo_tier", tier=3, confidence="low")
        f2 = _finding("hi_tier", tier=1, confidence="high")
        st = _state([f1, f2])
        result = get_next_item(st)
        assert result["id"] == "hi_tier"

    def test_confidence_breaks_tier_tie(self):
        f1 = _finding("low", tier=2, confidence="low")
        f2 = _finding("high", tier=2, confidence="high")
        st = _state([f1, f2])
        result = get_next_item(st)
        assert result["id"] == "high"

    def test_detail_count_breaks_confidence_tie(self):
        f1 = _finding("few", tier=1, confidence="high", detail={"count": 1})
        f2 = _finding("many", tier=1, confidence="high", detail={"count": 10})
        st = _state([f1, f2])
        result = get_next_item(st)
        assert result["id"] == "many"

    def test_tier_filter(self):
        f1 = _finding("t1", tier=1, confidence="high")
        f2 = _finding("t3", tier=3, confidence="high")
        st = _state([f1, f2])
        result = get_next_item(st, tier=3)
        assert result["id"] == "t3"

    def test_tier_filter_returns_none_if_no_match(self):
        f = _finding("t1", tier=1)
        st = _state([f])
        assert get_next_item(st, tier=4) is None


class TestGetNextItems:
    def test_returns_multiple_items(self):
        findings = [_finding(f"f{i}", tier=2) for i in range(5)]
        st = _state(findings)
        items = get_next_items(st, count=3)
        assert len(items) == 3

    def test_returns_fewer_than_count_when_not_enough(self):
        st = _state([_finding("a", tier=1)])
        items = get_next_items(st, count=10)
        assert len(items) == 1

    def test_returns_empty_list_when_no_open(self):
        st = _state([_finding("a", status="fixed")])
        items = get_next_items(st, count=5)
        assert items == []

    def test_sorted_by_priority(self):
        f1 = _finding("t3_lo", tier=3, confidence="low")
        f2 = _finding("t1_hi", tier=1, confidence="high")
        f3 = _finding("t2_md", tier=2, confidence="medium")
        st = _state([f1, f2, f3])
        items = get_next_items(st, count=3)
        assert items[0]["id"] == "t1_hi"
        assert items[1]["id"] == "t2_md"
        assert items[2]["id"] == "t3_lo"

    def test_tier_filter_with_count(self):
        findings = [_finding(f"f{i}", tier=2) for i in range(5)]
        findings += [_finding(f"other{i}", tier=3) for i in range(5)]
        st = _state(findings)
        items = get_next_items(st, tier=2, count=3)
        assert len(items) == 3
        assert all(item["tier"] == 2 for item in items)

    def test_id_tiebreaker_is_stable(self):
        """When tier, confidence, and detail count are all the same, sort by ID."""
        f1 = _finding("zzz", tier=1, confidence="high")
        f2 = _finding("aaa", tier=1, confidence="high")
        st = _state([f1, f2])
        items = get_next_items(st, count=2)
        assert items[0]["id"] == "aaa"
        assert items[1]["id"] == "zzz"

    def test_scan_path_filters_findings(self):
        """scan_path limits results to findings within that path."""
        f1 = _finding("in_scope", file="src/foo.py", tier=1)
        f2 = _finding("out_scope", file="other/bar.py", tier=1)
        st = _state([f1, f2])
        st["scan_path"] = "src"
        items = get_next_items(st, scan_path="src")
        assert len(items) == 1
        assert items[0]["id"] == "in_scope"

    def test_scan_path_none_returns_all(self):
        """scan_path=None returns all findings."""
        f1 = _finding("a", file="src/a.py", tier=1)
        f2 = _finding("b", file="other/b.py", tier=1)
        st = _state([f1, f2])
        items = get_next_items(st, scan_path=None, count=10)
        assert len(items) == 2

    def test_scan_path_dot_returns_all(self):
        """scan_path='.' returns all findings."""
        f1 = _finding("a", file="src/a.py", tier=1)
        f2 = _finding("b", file="other/b.py", tier=1)
        st = _state([f1, f2])
        items = get_next_items(st, scan_path=".", count=10)
        assert len(items) == 2

    def test_get_next_item_with_scan_path(self):
        """get_next_item respects scan_path."""
        f1 = _finding("out", file="other/a.py", tier=1)
        f2 = _finding("in", file="src/b.py", tier=1)
        st = _state([f1, f2])
        result = get_next_item(st, scan_path="src")
        assert result["id"] == "in"

    def test_scan_path_includes_holistic(self):
        """Holistic findings (file='.') are always included regardless of scan_path."""
        f1 = _finding("holistic", file=".", tier=4)
        f2 = _finding("in_scope", file="src/a.py", tier=1)
        f3 = _finding("out_scope", file="other/b.py", tier=1)
        st = _state([f1, f2, f3])
        items = get_next_items(st, scan_path="src", count=10)
        assert len(items) == 2
        ids = {i["id"] for i in items}
        assert ids == {"holistic", "in_scope"}
