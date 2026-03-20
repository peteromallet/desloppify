"""Tests for desloppify.plan — plan generation, item sections, and next-item priority."""

from __future__ import annotations

from datetime import date

import pytest

from desloppify.engine.planning import (
    CONFIDENCE_ORDER,
    generate_plan_md,
    get_next_item,
    get_next_items,
)
from desloppify.engine.planning.render import (
    _plan_dimension_table,
    _plan_header,
    _plan_item_sections,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue(
    fid,
    *,
    detector="det",
    file="a.py",
    tier=1,
    confidence="high",
    summary="something wrong",
    status="open",
    detail=None,
    note=None,
):
    """Build a minimal issue dict."""
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


def _state(
    issues_list=None,
    *,
    overall_score=None,
    objective_score=None,
    strict_score=None,
    stats=None,
    dimension_scores=None,
    codebase_metrics=None,
    subjective_assessments=None,
):
    """Build a minimal state dict."""
    issues = {}
    for f in issues_list or []:
        issues[f["id"]] = f
    return {
        "overall_score": overall_score,
        "objective_score": objective_score,
        "strict_score": strict_score,
        "stats": stats or {},
        "issues": issues,
        "dimension_scores": dimension_scores or {},
        "codebase_metrics": codebase_metrics or {},
        "subjective_assessments": subjective_assessments or {},
    }


# ===========================================================================
# CONFIDENCE_ORDER constant
# ===========================================================================


class TestConstants:
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
        st = _state(overall_score=90.0, objective_score=87.5, strict_score=82.3)
        lines = _plan_header(st, {})
        score_line = lines[2]
        assert "87.5" in score_line
        assert "82.3" in score_line
        assert "Health:" in score_line

    def test_fallback_score_when_only_overall(self):
        st = _state(overall_score=42)
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
        st = _state(
            codebase_metrics={
                "python": {
                    "total_files": 50,
                    "total_loc": 3000,
                    "total_directories": 8,
                },
            }
        )
        lines = _plan_header(st, {})
        joined = "\n".join(lines)
        assert "50 files" in joined
        assert "3,000 LOC" in joined
        assert "8 directories" in joined

    def test_codebase_metrics_compact_loc(self):
        """LOC >= 10000 should render as e.g. '15K' instead of '15,000'."""
        st = _state(
            codebase_metrics={
                "ts": {"total_files": 100, "total_loc": 15000, "total_directories": 20},
            }
        )
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
        st = _state(
            dimension_scores={
                "Import hygiene": {
                    "checks": 10,
                    "failing": 2,
                    "score": 80.0,
                    "strict": 75.0,
                },
            }
        )
        lines = _plan_dimension_table(st)
        assert any("Dimension" in line and "Health" in line for line in lines)

    def test_bold_when_score_below_93(self):
        st = _state(
            dimension_scores={
                "Import hygiene": {
                    "checks": 10,
                    "failing": 2,
                    "score": 90.0,
                    "strict": 85.0,
                },
            }
        )
        lines = _plan_dimension_table(st)
        row_lines = [line for line in lines if "Import hygiene" in line]
        assert len(row_lines) == 1
        assert "**Import hygiene**" in row_lines[0]

    def test_no_bold_when_score_at_or_above_93(self):
        st = _state(
            dimension_scores={
                "Import hygiene": {
                    "checks": 100,
                    "failing": 1,
                    "score": 99.0,
                    "strict": 98.0,
                },
            }
        )
        lines = _plan_dimension_table(st)
        row_lines = [line for line in lines if "Import hygiene" in line]
        assert len(row_lines) == 1
        assert "**Import hygiene**" not in row_lines[0]
        assert "Import hygiene" in row_lines[0]


# ===========================================================================
# _plan_item_sections
# ===========================================================================


class TestPlanItemSections:
    def test_empty_issues_produces_no_sections(self):
        assert _plan_item_sections({}) == []

    def test_groups_by_file(self):
        issues = {
            "a": _issue("a", tier=1, file="x.py"),
            "b": _issue("b", tier=2, file="y.py"),
        }
        lines = _plan_item_sections(issues)
        joined = "\n".join(lines)
        assert "x.py" in joined
        assert "y.py" in joined

    def test_skips_non_open_issues(self):
        issues = {
            "a": _issue("a", tier=1, status="fixed"),
            "b": _issue("b", tier=1, status="wontfix"),
        }
        lines = _plan_item_sections(issues)
        assert lines == []

    def test_files_sorted_by_issue_count_descending(self):
        issues = {
            "a1": _issue("a1", tier=1, file="few.py"),
            "b1": _issue("b1", tier=1, file="many.py"),
            "b2": _issue("b2", tier=1, file="many.py"),
            "b3": _issue("b3", tier=1, file="many.py"),
        }
        lines = _plan_item_sections(issues)
        # Find the file header lines
        file_headers = [line for line in lines if line.startswith("### ")]
        # "many.py" should come before "few.py"
        assert "many.py" in file_headers[0]
        assert "few.py" in file_headers[1]

    def test_issues_sorted_by_confidence_within_file(self):
        issues = {
            "lo": _issue("lo", tier=1, file="a.py", confidence="low"),
            "hi": _issue("hi", tier=1, file="a.py", confidence="high"),
            "md": _issue("md", tier=1, file="a.py", confidence="medium"),
        }
        lines = _plan_item_sections(issues)
        bullet_lines = [
            line.strip() for line in lines if line.strip().startswith("- [ ]")
        ]
        assert "[high]" in bullet_lines[0]
        assert "[medium]" in bullet_lines[1]
        assert "[low]" in bullet_lines[2]

    def test_issue_id_shown_below_summary(self):
        issues = {
            "det::f.py::x": _issue("det::f.py::x", tier=1, file="f.py"),
        }
        lines = _plan_item_sections(issues)
        id_lines = [line for line in lines if "det::f.py::x" in line]
        assert len(id_lines) >= 1

    def test_open_count_in_header(self):
        issues = {
            "a": _issue("a", tier=2, file="x.py"),
            "b": _issue("b", tier=2, file="y.py"),
            "c": _issue("c", tier=2, file="y.py"),
        }
        lines = _plan_item_sections(issues)
        section_header = [line for line in lines if line.startswith("## Open Items")]
        assert len(section_header) == 1
        assert "3" in section_header[0]

    def test_review_issues_render(self):
        issues = {
            "review::src/a.py::naming": _issue(
                "review::src/a.py::naming",
                detector="review",
                tier=2,
                file="src/a.py",
                detail={"dimension": "naming_quality"},
            ),
        }
        lines = _plan_item_sections(
            issues, state={"issues": issues, "dimension_scores": {}}
        )
        joined = "\n".join(lines)
        assert "review::src/a.py::naming" in joined

    def test_subjective_dimensions_show_up(self):
        issues: dict[str, dict] = {}
        state = {
            "issues": issues,
            "dimension_scores": {
                "Naming quality": {"score": 84.0, "strict": 84.0, "failing": 2, "stale": True}
            },
        }
        lines = _plan_item_sections(issues, state=state)
        joined = "\n".join(lines)
        assert "subjective::naming_quality" in joined


# ===========================================================================
# generate_plan_md
# ===========================================================================


class TestGeneratePlanMd:
    def test_returns_string(self):
        st = _state()
        md = generate_plan_md(st)
        assert isinstance(md, str)
        assert "Desloppify Plan" in md

    def test_includes_summary(self):
        st = _state(
            stats={"open": 7, "fixed": 3, "wontfix": 0, "auto_resolved": 0},
        )
        md = generate_plan_md(st)
        assert "7 open" in md

    def test_includes_addressed_section(self):
        f_fixed = _issue("a", status="fixed", tier=1)
        f_wontfix = _issue("b", status="wontfix", tier=1, note="intentional")
        st = _state([f_fixed, f_wontfix])
        md = generate_plan_md(st)
        assert "## Addressed" in md
        assert "fixed" in md
        assert "wontfix" in md

    def test_wontfix_with_notes_listed(self):
        f = _issue(
            "det::f.py::x",
            status="wontfix",
            tier=1,
            note="We need this for backwards compat",
        )
        st = _state([f])
        md = generate_plan_md(st)
        assert "backwards compat" in md
        assert "det::f.py::x" in md


# ===========================================================================
# get_next_item / get_next_items
# ===========================================================================


class TestGetNextItem:
    def test_returns_none_when_no_open_issues(self):
        st = _state([_issue("a", status="fixed")])
        assert get_next_item(st) is None

    def test_returns_none_for_empty_issues(self):
        st = _state()
        assert get_next_item(st) is None

    def test_returns_highest_priority_item(self):
        f1 = _issue("lo_conf", tier=3, confidence="low")
        f2 = _issue("hi_conf", tier=1, confidence="high")
        st = _state([f1, f2])
        result = get_next_item(st)
        assert result["id"] == "hi_conf"

    def test_confidence_breaks_tie(self):
        f1 = _issue("low", tier=2, confidence="low")
        f2 = _issue("high", tier=2, confidence="high")
        st = _state([f1, f2])
        result = get_next_item(st)
        assert result["id"] == "high"

    def test_detail_count_breaks_confidence_tie(self):
        f1 = _issue("few", tier=1, confidence="high", detail={"count": 1})
        f2 = _issue("many", tier=1, confidence="high", detail={"count": 10})
        st = _state([f1, f2])
        result = get_next_item(st)
        assert result["id"] == "many"

    def test_tier_param_is_rejected(self):
        f1 = _issue("t1", tier=1, confidence="high")
        f2 = _issue("t3", tier=3, confidence="high")
        st = _state([f1, f2])
        with pytest.raises(TypeError):
            get_next_item(st, tier=3)


class TestGetNextItems:
    def test_returns_multiple_items(self):
        issues = [_issue(f"f{i}", tier=2) for i in range(5)]
        st = _state(issues)
        items = get_next_items(st, count=3)
        assert len(items) == 3

    def test_returns_fewer_than_count_when_not_enough(self):
        st = _state([_issue("a", tier=1)])
        items = get_next_items(st, count=10)
        assert len(items) == 1

    def test_returns_empty_list_when_no_open(self):
        st = _state([_issue("a", status="fixed")])
        items = get_next_items(st, count=5)
        assert items == []

    def test_sorted_by_confidence(self):
        f1 = _issue("lo", tier=3, confidence="low")
        f2 = _issue("hi", tier=1, confidence="high")
        f3 = _issue("md", tier=2, confidence="medium")
        st = _state([f1, f2, f3])
        items = get_next_items(st, count=3)
        assert items[0]["id"] == "hi"
        assert items[1]["id"] == "md"
        assert items[2]["id"] == "lo"

    def test_count_limits_results(self):
        issues = [_issue(f"f{i}", tier=2) for i in range(5)]
        issues += [_issue(f"other{i}", tier=3) for i in range(5)]
        st = _state(issues)
        items = get_next_items(st, count=3)
        assert len(items) == 3

    def test_id_tiebreaker_is_stable(self):
        """When tier, confidence, and detail count are all the same, sort by ID."""
        f1 = _issue("zzz", tier=1, confidence="high")
        f2 = _issue("aaa", tier=1, confidence="high")
        st = _state([f1, f2])
        items = get_next_items(st, count=2)
        assert items[0]["id"] == "aaa"
        assert items[1]["id"] == "zzz"

    def test_scan_path_filters_issues(self):
        """scan_path limits results to issues within that path."""
        f1 = _issue("in_scope", file="src/foo.py", tier=1)
        f2 = _issue("out_scope", file="other/bar.py", tier=1)
        st = _state([f1, f2])
        st["scan_path"] = "src"
        items = get_next_items(st, scan_path="src")
        assert len(items) == 1
        assert items[0]["id"] == "in_scope"

    def test_scan_path_none_returns_all(self):
        """scan_path=None returns all issues."""
        f1 = _issue("a", file="src/a.py", tier=1)
        f2 = _issue("b", file="other/b.py", tier=1)
        st = _state([f1, f2])
        items = get_next_items(st, scan_path=None, count=10)
        assert len(items) == 2

    def test_scan_path_dot_returns_all(self):
        """scan_path='.' returns all issues."""
        f1 = _issue("a", file="src/a.py", tier=1)
        f2 = _issue("b", file="other/b.py", tier=1)
        st = _state([f1, f2])
        items = get_next_items(st, scan_path=".", count=10)
        assert len(items) == 2

    def test_get_next_item_with_scan_path(self):
        """get_next_item respects scan_path."""
        f1 = _issue("out", file="other/a.py", tier=1)
        f2 = _issue("in", file="src/b.py", tier=1)
        st = _state([f1, f2])
        result = get_next_item(st, scan_path="src")
        assert result["id"] == "in"

    def test_scan_path_includes_holistic(self):
        """Holistic issues (file='.') are always included regardless of scan_path."""
        f1 = _issue("holistic", file=".", tier=4)
        f2 = _issue("in_scope", file="src/a.py", tier=1)
        f3 = _issue("out_scope", file="other/b.py", tier=1)
        st = _state([f1, f2, f3])
        items = get_next_items(st, scan_path="src", count=10)
        assert len(items) == 2
        ids = {i["id"] for i in items}
        assert ids == {"holistic", "in_scope"}

    def test_review_issues_appear_in_queue(self):
        review = _issue(
            "review_item",
            detector="review",
            tier=3,
            confidence="high",
            detail={"dimension": "naming_quality"},
        )
        # Review is non-objective — only surfaces when no objective items remain.
        st = _state(
            [review],
            subjective_assessments={"naming_quality": {"score": 92}},
        )
        items = get_next_items(st, count=2)
        ids = {item["id"] for item in items}
        assert "review_item" in ids

    def test_review_issues_reorder_by_confidence_then_review_weight(self):
        standard = _issue(
            "a_review_mild",
            detector="review",
            tier=3,
            confidence="high",
            detail={"dimension": "naming_quality"},
        )
        holistic = _issue(
            "z_review_critical",
            detector="review",
            tier=3,
            confidence="low",
            detail={"dimension": "logic_clarity", "holistic": True},
        )
        st = _state(
            [standard, holistic],
            dimension_scores={
                "Naming quality": {"score": 92.0, "strict": 92.0, "failing": 2},
                "Logic clarity": {"score": 88.0, "strict": 88.0, "failing": 3},
            },
        )
        items = get_next_items(st, count=2)
        # Confidence takes precedence: high before low
        assert [item["id"] for item in items] == ["a_review_mild", "z_review_critical"]

    def test_mechanical_and_review_both_in_queue(self):
        urgent = _issue("urgent", detector="security", tier=1, confidence="high")
        review_low = _issue(
            "review_low",
            detector="review",
            tier=3,
            confidence="high",
            detail={"dimension": "naming_quality"},
        )
        st = _state(
            [review_low, urgent],
            subjective_assessments={"naming_quality": {"score": 80}},
        )
        items = get_next_items(st, count=2)
        ids = {item["id"] for item in items}
        # Review is non-objective — filtered when objective items exist
        assert "urgent" in ids
        assert "review_low" not in ids
