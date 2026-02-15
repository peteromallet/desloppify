"""Tests for desloppify.issues — state-backed review findings work queue."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(
    fid: str = "review::.::holistic::abstraction_fitness::base_py_overloaded::55b6ae6d",
    *,
    detector: str = "review",
    file: str = ".",
    status: str = "open",
    confidence: str = "medium",
    summary: str = "base.py mixes concerns",
    holistic: bool = True,
    dimension: str = "abstraction_fitness",
    related_files: list[str] | None = None,
    evidence: list[str] | None = None,
    suggestion: str = "Extract functions",
    reasoning: str = "Reduces coupling",
    evidence_lines: list[str] | None = None,
    last_seen: str | None = None,
) -> dict:
    """Build a minimal finding dict for testing."""
    detail: dict = {
        "dimension": dimension,
        "evidence": evidence or ["ev1"],
        "suggestion": suggestion,
        "reasoning": reasoning,
    }
    if holistic:
        detail["holistic"] = True
        detail["related_files"] = related_files or ["src/a.py", "src/b.py"]
    if evidence_lines:
        detail["evidence_lines"] = evidence_lines
    return {
        "id": fid,
        "detector": detector,
        "file": file,
        "status": status,
        "confidence": confidence,
        "summary": summary,
        "detail": detail,
        "tier": 3,
        "note": None,
        "first_seen": "2026-01-01T00:00:00+00:00",
        "last_seen": last_seen or "2026-01-01T00:00:00+00:00",
        "resolved_at": None,
        "reopen_count": 0,
    }


def _per_file_finding(
    fid: str = "review::src/foo.ts::naming_quality::bad_names::aabb1122",
    *,
    file: str = "src/foo.ts",
    dimension: str = "naming_quality",
    confidence: str = "high",
    summary: str = "Bad variable names",
    evidence_lines: list[str] | None = None,
    suggestion: str = "Rename variables",
) -> dict:
    return _finding(
        fid,
        detector="review",
        file=file,
        status="open",
        confidence=confidence,
        summary=summary,
        holistic=False,
        dimension=dimension,
        suggestion=suggestion,
        evidence_lines=evidence_lines or ["line 10: x = complicated()"],
    )


def _state_with(*findings):
    """Build a minimal state dict from findings."""
    return {"findings": {f["id"]: f for f in findings}}


# ---------------------------------------------------------------------------
# finding_weight
# ---------------------------------------------------------------------------

class TestFindingWeight:
    def test_holistic_high_confidence(self):
        from desloppify.issues import finding_weight
        f = _finding(confidence="high")
        weight, pts, fid = finding_weight(f)
        assert weight == 10.0  # 1.0 * HOLISTIC_MULTIPLIER (10)

    def test_holistic_low_confidence(self):
        from desloppify.issues import finding_weight
        f = _finding(confidence="low")
        weight, pts, fid = finding_weight(f)
        assert weight == 3.0  # 0.3 * 10

    def test_per_file_high_confidence(self):
        from desloppify.issues import finding_weight
        f = _per_file_finding(confidence="high")
        weight, pts, fid = finding_weight(f)
        assert weight == 1.0

    def test_per_file_medium_confidence(self):
        from desloppify.issues import finding_weight
        f = _per_file_finding(confidence="medium")
        weight, pts, fid = finding_weight(f)
        assert weight == 0.7

    def test_returns_finding_id_as_tiebreaker(self):
        from desloppify.issues import finding_weight
        f = _finding(confidence="high")
        _, _, fid = finding_weight(f)
        assert fid == f["id"]


# ---------------------------------------------------------------------------
# impact_label
# ---------------------------------------------------------------------------

class TestImpactLabel:
    def test_high_impact(self):
        from desloppify.issues import impact_label
        assert impact_label(10.0) == "+++"

    def test_medium_impact(self):
        from desloppify.issues import impact_label
        assert impact_label(5.0) == "++"

    def test_low_impact(self):
        from desloppify.issues import impact_label
        assert impact_label(1.0) == "+"


# ---------------------------------------------------------------------------
# list_open_review_findings
# ---------------------------------------------------------------------------

class TestListOpenReviewFindings:
    def test_returns_only_open_review(self):
        from desloppify.issues import list_open_review_findings
        f1 = _finding(status="open")
        f2 = _finding(fid="review::.::holistic::other::x::y", status="fixed")
        f3 = _per_file_finding(fid="smells::src/foo.ts::async_no_await")
        f3["detector"] = "smells"
        state = _state_with(f1, f2, f3)
        result = list_open_review_findings(state)
        assert len(result) == 1
        assert result[0]["id"] == f1["id"]

    def test_sorted_by_weight_desc(self):
        from desloppify.issues import list_open_review_findings
        f_high = _finding(fid="review::.::holistic::a::x::1", confidence="high")
        f_low = _finding(fid="review::.::holistic::b::y::2", confidence="low")
        state = _state_with(f_high, f_low)
        result = list_open_review_findings(state)
        assert result[0]["confidence"] == "high"
        assert result[1]["confidence"] == "low"

    def test_empty_state(self):
        from desloppify.issues import list_open_review_findings
        assert list_open_review_findings({"findings": {}}) == []

    def test_deterministic_ordering(self):
        """Same-weight findings should sort by finding ID for stability."""
        from desloppify.issues import list_open_review_findings
        # Three findings with same confidence — order should be deterministic
        f_a = _per_file_finding(fid="review::src/c.ts::dim::c::1111", confidence="high")
        f_b = _per_file_finding(fid="review::src/a.ts::dim::a::2222", confidence="high")
        f_c = _per_file_finding(fid="review::src/b.ts::dim::b::3333", confidence="high")
        state = _state_with(f_a, f_b, f_c)
        result1 = list_open_review_findings(state)
        result2 = list_open_review_findings(state)
        # Should be identical across calls
        assert [f["id"] for f in result1] == [f["id"] for f in result2]
        # Should be sorted by ID (ascending) within same weight
        ids = [f["id"] for f in result1]
        assert ids == sorted(ids)

    def test_includes_per_file_review(self):
        from desloppify.issues import list_open_review_findings
        f = _per_file_finding()
        state = _state_with(f)
        result = list_open_review_findings(state)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# update_investigation
# ---------------------------------------------------------------------------

class TestUpdateInvestigation:
    def test_stores_investigation(self):
        from desloppify.issues import update_investigation
        f = _finding()
        state = _state_with(f)
        ok = update_investigation(state, f["id"], "Analysis text here")
        assert ok is True
        detail = state["findings"][f["id"]]["detail"]
        assert detail["investigation"] == "Analysis text here"
        assert "investigated_at" in detail

    def test_returns_false_for_missing(self):
        from desloppify.issues import update_investigation
        state = {"findings": {}}
        assert update_investigation(state, "nonexistent", "text") is False

    def test_returns_false_for_resolved(self):
        from desloppify.issues import update_investigation
        f = _finding(status="fixed")
        state = _state_with(f)
        assert update_investigation(state, f["id"], "text") is False

    def test_overwrites_previous_investigation(self):
        from desloppify.issues import update_investigation
        f = _finding()
        f["detail"]["investigation"] = "old analysis"
        state = _state_with(f)
        update_investigation(state, f["id"], "new analysis")
        assert state["findings"][f["id"]]["detail"]["investigation"] == "new analysis"


# ---------------------------------------------------------------------------
# expire_stale_holistic
# ---------------------------------------------------------------------------

class TestExpireStaleHolistic:
    def test_expires_old_holistic(self):
        from desloppify.issues import expire_stale_holistic
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        f = _finding(last_seen=old_date)
        state = _state_with(f)
        expired = expire_stale_holistic(state, max_age_days=30)
        assert f["id"] in expired
        assert state["findings"][f["id"]]["status"] == "auto_resolved"
        assert "expired" in state["findings"][f["id"]]["note"]

    def test_keeps_recent_holistic(self):
        from desloppify.issues import expire_stale_holistic
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        f = _finding(last_seen=recent)
        state = _state_with(f)
        expired = expire_stale_holistic(state, max_age_days=30)
        assert expired == []
        assert state["findings"][f["id"]]["status"] == "open"

    def test_ignores_per_file_findings(self):
        from desloppify.issues import expire_stale_holistic
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        f = _per_file_finding()
        f["last_seen"] = old_date
        state = _state_with(f)
        expired = expire_stale_holistic(state, max_age_days=30)
        assert expired == []
        assert state["findings"][f["id"]]["status"] == "open"

    def test_ignores_non_review_findings(self):
        from desloppify.issues import expire_stale_holistic
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        f = _finding(last_seen=old_date)
        f["detector"] = "smells"
        state = _state_with(f)
        expired = expire_stale_holistic(state, max_age_days=30)
        assert expired == []

    def test_ignores_already_resolved(self):
        from desloppify.issues import expire_stale_holistic
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        f = _finding(status="fixed", last_seen=old_date)
        state = _state_with(f)
        expired = expire_stale_holistic(state, max_age_days=30)
        assert expired == []

    def test_custom_max_age(self):
        from desloppify.issues import expire_stale_holistic
        date_15d = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        f = _finding(last_seen=date_15d)
        state = _state_with(f)
        # 10-day max: should expire
        expired = expire_stale_holistic(state, max_age_days=10)
        assert len(expired) == 1
        # Reset
        state["findings"][f["id"]]["status"] = "open"
        # 20-day max: should NOT expire
        expired = expire_stale_holistic(state, max_age_days=20)
        assert expired == []

    def test_empty_state(self):
        from desloppify.issues import expire_stale_holistic
        assert expire_stale_holistic({"findings": {}}) == []


# ---------------------------------------------------------------------------
# render_issue_detail
# ---------------------------------------------------------------------------

class TestRenderIssueDetail:
    def test_holistic_doc_has_all_sections(self):
        from desloppify.issues import render_issue_detail
        f = _finding()
        doc = render_issue_detail(f, "python")
        assert "# abstraction fitness:" in doc
        assert "**Finding**:" in doc
        assert f["id"] in doc
        assert "## Problem" in doc
        assert "## Evidence" in doc
        assert "## Suggested Fix" in doc
        assert "## Files" in doc
        assert "## Why This Matters" in doc
        assert "## Status: Needs Investigation" in doc
        assert "issues update" in doc

    def test_per_file_doc_shows_why_when_reasoning_present(self):
        from desloppify.issues import render_issue_detail
        f = _per_file_finding()
        doc = render_issue_detail(f, "typescript")
        assert "## Problem" in doc
        assert "## Status: Needs Investigation" in doc
        # Per-file findings now show "Why This Matters" when reasoning is present
        assert "## Why This Matters" in doc
        assert "--lang typescript" in doc

    def test_per_file_doc_no_why_without_reasoning(self):
        from desloppify.issues import render_issue_detail
        f = _per_file_finding()
        f["detail"]["reasoning"] = ""
        doc = render_issue_detail(f, "typescript")
        assert "## Why This Matters" not in doc

    def test_per_file_doc_shows_file(self):
        from desloppify.issues import render_issue_detail
        f = _per_file_finding(file="src/components/Button.tsx")
        doc = render_issue_detail(f, "typescript")
        assert "`src/components/Button.tsx`" in doc

    def test_holistic_doc_shows_related_files(self):
        from desloppify.issues import render_issue_detail
        f = _finding(related_files=["src/a.py", "src/b.py", "src/c.py"])
        doc = render_issue_detail(f, "python")
        assert "`src/a.py`" in doc
        assert "`src/b.py`" in doc
        assert "`src/c.py`" in doc

    def test_evidence_lines_in_per_file(self):
        from desloppify.issues import render_issue_detail
        f = _per_file_finding(evidence_lines=["line 5: bad = True", "line 10: worse = True"])
        doc = render_issue_detail(f, "typescript")
        assert "line 5: bad = True" in doc
        assert "line 10: worse = True" in doc

    def test_investigated_shows_investigation_section(self):
        from desloppify.issues import render_issue_detail
        f = _finding()
        f["detail"]["investigation"] = "Detailed analysis here."
        f["detail"]["investigated_at"] = "2026-02-14T12:00:00+00:00"
        doc = render_issue_detail(f, "python")
        assert "## Investigation (2026-02-14)" in doc
        assert "Detailed analysis here." in doc
        assert "## Ready to Fix" in doc
        assert "resolve fixed" in doc
        assert "## Status: Needs Investigation" not in doc

    def test_uninvestigated_shows_needs_investigation(self):
        from desloppify.issues import render_issue_detail
        f = _finding()
        doc = render_issue_detail(f, "python", number=3)
        assert "## Status: Needs Investigation" in doc
        assert "resolve fixed" in doc
        assert "--note" in doc
        assert "issues update 3" in doc  # secondary path still shown
        assert "## Ready to Fix" not in doc

    def test_uninvestigated_without_number(self):
        from desloppify.issues import render_issue_detail
        f = _finding()
        doc = render_issue_detail(f, "python")
        assert "issues update <number>" in doc
        assert "resolve fixed" in doc


# ---------------------------------------------------------------------------
# Command integration: issues_cmd
# ---------------------------------------------------------------------------

class TestCmdIssues:
    def _make_args(self, state, state_path=None, issues_action=None,
                   number=None, file=None, lang=None):
        """Build a minimal args namespace."""
        import argparse
        args = argparse.Namespace(
            _preloaded_state=state,
            _state_path=state_path,
            issues_action=issues_action,
            number=number,
            file=file,
            lang=lang or "python",
            exclude=None,
        )
        return args

    def test_list_shows_findings(self, capsys):
        from desloppify.commands.issues_cmd import _list_issues
        from unittest.mock import patch
        f1 = _finding(confidence="high")
        f2 = _per_file_finding()
        state = _state_with(f1, f2)
        args = self._make_args(state)
        with patch("desloppify.commands.issues_cmd._write_query"):
            _list_issues(args)
        out = capsys.readouterr().out
        assert "2 open review finding" in out
        assert "abstraction fitness" in out

    def test_list_empty(self, capsys):
        from desloppify.commands.issues_cmd import _list_issues
        from unittest.mock import patch
        state = {"findings": {}}
        args = self._make_args(state)
        with patch("desloppify.commands.issues_cmd._write_query"):
            _list_issues(args)
        out = capsys.readouterr().out
        assert "No review findings open" in out

    def test_show_renders_detail(self, capsys):
        from desloppify.commands.issues_cmd import _show_issue
        from unittest.mock import patch
        f = _finding()
        state = _state_with(f)
        args = self._make_args(state, number=1)
        with patch("desloppify.commands.issues_cmd._write_query"), \
             patch("desloppify.commands._helpers.resolve_lang") as mock_lang:
            mock_lang.return_value = type("L", (), {"name": "python"})()
            _show_issue(args)
        out = capsys.readouterr().out
        assert "abstraction fitness" in out
        assert "## Problem" in out

    def test_show_out_of_range(self, capsys):
        from desloppify.commands.issues_cmd import _show_issue
        f = _finding()
        state = _state_with(f)
        args = self._make_args(state, number=5)
        _show_issue(args)
        err = capsys.readouterr().err
        assert "out of range" in err

    def test_update_stores_investigation(self, tmp_path, capsys):
        from desloppify.commands.issues_cmd import _update_issue
        from unittest.mock import patch

        analysis_file = tmp_path / "analysis.md"
        analysis_file.write_text("My investigation notes")

        f = _finding()
        state = _state_with(f)
        args = self._make_args(state, state_path=None, number=1,
                               file=str(analysis_file))

        with patch("desloppify.state.save_state"), \
             patch("desloppify.commands._helpers.resolve_lang") as mock_lang:
            mock_lang.return_value = type("L", (), {"name": "python"})()
            _update_issue(args)

        out = capsys.readouterr().out
        assert "Investigation saved" in out
        assert "resolve fixed" in out
        assert state["findings"][f["id"]]["detail"]["investigation"] == "My investigation notes"

    def test_update_missing_file(self, capsys):
        from desloppify.commands.issues_cmd import _update_issue
        f = _finding()
        state = _state_with(f)
        args = self._make_args(state, number=1, file="/nonexistent/file.md")
        _update_issue(args)
        err = capsys.readouterr().err
        assert "File not found" in err


# ---------------------------------------------------------------------------
# Code References header (was duplicate ## Evidence)
# ---------------------------------------------------------------------------

class TestCodeReferencesHeader:
    """evidence_lines should render as '## Code References', not '## Evidence'."""

    def test_evidence_lines_header(self):
        from desloppify.issues import render_issue_detail
        f = _per_file_finding(
            evidence_lines=["line 10: x = 1", "line 20: y = 2"],
        )
        output = render_issue_detail(f, "typescript")
        assert "## Code References" in output
        # evidence field uses ## Evidence
        assert output.count("## Evidence") == 1
        assert output.count("## Code References") == 1

    def test_no_evidence_lines_no_code_references(self):
        from desloppify.issues import render_issue_detail
        f = _finding()  # holistic, no evidence_lines
        output = render_issue_detail(f, "python")
        assert "## Code References" not in output
